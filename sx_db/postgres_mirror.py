from __future__ import annotations

import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from .db import connect, ensure_source, init_db, rebuild_fts
from .settings import Settings


_LAST_SYNC: dict[tuple[str, str], float] = {}


def _safe_ident(name: str) -> str | None:
    s = str(name or "").strip()
    if not s:
        return None
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", s):
        return None
    return s


def _schema_from_pg_url(pg_url: str) -> str | None:
    if not pg_url:
        return None
    try:
        parsed = urlparse(pg_url)
        q = parse_qs(parsed.query or "")
        options_raw = ""
        if "options" in q and q["options"]:
            options_raw = q["options"][0]
        if not options_raw:
            return None
        options_decoded = unquote(options_raw)
        m = re.search(r"(?:^|\s)-c\s+search_path=([^\s]+)", options_decoded)
        if not m:
            return None
        path = m.group(1).strip()
        if not path:
            return None
        first = path.split(",", 1)[0].strip()
        return _safe_ident(first)
    except Exception:
        return None


def _sanitize_source_id(v: object, fallback: str = "default") -> str:
    raw = str(v or "").strip()
    if not raw:
        raw = fallback
    cleaned = re.sub(r"[^a-zA-Z0-9._-]", "", raw)
    return cleaned or "default"


def _to_int(value: object) -> int | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        return int(float(s))
    except Exception:
        return None


def _parse_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        key = k.strip()
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
            continue
        val = v.strip()
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            val = val[1:-1]
        out[key] = val
    return out


def _build_db_url_from_alias(env_map: dict[str, str], alias: str) -> str | None:
    alias = str(alias or "").strip()
    if not alias:
        return None
    user = env_map.get(f"{alias}_DB_USER", "")
    pwd = env_map.get(f"{alias}_DB_PASSWORD", "")
    host = env_map.get(f"{alias}_DB_HOST", "")
    port = env_map.get(f"{alias}_DB_PORT", "")
    dbn = env_map.get(f"{alias}_DB_NAME", "")
    schema = env_map.get(f"{alias}_DB_SCHEMA", "")
    if not (user and host and port and dbn):
        return None

    # Keep URL format consistent with existing project conventions.
    url = f"postgresql://{user}:{pwd}@{host}:{port}/{dbn}"
    if schema:
        url += f"?options=-c%20search_path%3D{schema}"
    return url


def _resolve_pg_url_and_mode(settings: Settings) -> tuple[str | None, str, str]:
    mode = str(getattr(settings, "SX_PIPELINE_DB_MODE", "LOCAL") or "LOCAL").strip().upper()
    backend_mode = str(getattr(settings, "SX_DB_BACKEND_MODE", "SQLITE") or "SQLITE").strip().upper()

    # Explicitly requested SQL mode means: stay purely in sqlite path.
    if mode in {"SQL", "SQLITE"}:
        return None, mode, backend_mode

    explicit_url = str(getattr(settings, "SX_PIPELINE_DATABASE_URL", "") or "").strip()
    if explicit_url:
        return explicit_url, mode, backend_mode

    env_path = Path(settings.SX_SCHEDULERX_ENV) if settings.SX_SCHEDULERX_ENV else Path("../SchedulerX/backend/pipeline/.env")
    env_map = _parse_env_file(env_path)
    idx = int(getattr(settings, "SX_PROFILE_INDEX", 1) or 1)

    explicit_alias = str(getattr(settings, "SX_PIPELINE_DB_PROFILE", "") or "").strip()
    if explicit_alias:
        return _build_db_url_from_alias(env_map, explicit_alias), mode, backend_mode

    local_alias = env_map.get(f"SRC_PATH_{idx}_DB_LOCAL") or env_map.get(f"SRC_PROFILE_{idx}_DB_LOCAL") or ""
    session_alias = env_map.get(f"SRC_PATH_{idx}_DB_SESSION") or env_map.get(f"SRC_PROFILE_{idx}_DB_SESSION") or ""
    trans_alias = env_map.get(f"SRC_PATH_{idx}_DB_TRANSACTION") or env_map.get(f"SRC_PROFILE_{idx}_DB_TRANSACTION") or ""

    if mode == "SESSION":
        alias = session_alias
    elif mode in {"TRANS", "TRANSACTION"}:
        alias = trans_alias
    else:
        alias = local_alias

    if not alias:
        alias = str(env_map.get("DB_PROFILE") or "").strip()

    return _build_db_url_from_alias(env_map, alias), mode, backend_mode


def _table_exists_in_schema(cur, schema: str, table_name: str) -> bool:
    cur.execute(
        """
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema=%s AND table_name=%s
        LIMIT 1
        """,
        (schema, table_name),
    )
    return bool(cur.fetchone())


def _sync_from_postgres(settings: Settings, source_id: str, pg_url: str) -> dict[str, Any]:
    try:
        import psycopg
    except Exception as e:  # pragma: no cover - depends on environment package set
        return {
            "backend": "sqlite",
            "active": False,
            "reason": f"psycopg unavailable: {e}",
            "mirrored": 0,
            "source_id": source_id,
        }

    sqlite_conn = connect(settings.SX_DB_PATH)
    init_db(sqlite_conn, enable_fts=settings.SX_DB_ENABLE_FTS)
    ensure_source(sqlite_conn, source_id, label=source_id)

    now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    mirrored = 0

    schema = _schema_from_pg_url(pg_url) or _safe_ident(getattr(settings, "SXCTL_SCHEMA_NAME", "") or "") or "public"
    schema = _safe_ident(schema) or "public"
    search_path = f"{schema},public"

    with psycopg.connect(pg_url) as pg_conn:
        with pg_conn.cursor() as cur:
            required_tables = ("consolidated", "authors", "bookmarks", "media")
            missing = [t for t in required_tables if not _table_exists_in_schema(cur, schema, t)]
            if missing:
                return {
                    "backend": "sqlite",
                    "active": False,
                    "reason": f"required tables missing in schema '{schema}': {', '.join(missing)}",
                    "mirrored": 0,
                    "source_id": source_id,
                    "schema": schema,
                    "search_path": search_path,
                }

            sql = f"""
                SELECT
                  c.c_videos_id::text AS id,
                  COALESCE(c.c_videos_authorid::text, a.authors_id::text) AS author_id,
                  COALESCE(NULLIF(c.c_authors_uniqueids::text, ''), NULLIF(a.authors_uniqueids::text, '')) AS author_unique_id,
                  COALESCE(NULLIF(c.c_authors_nicknames::text, ''), NULLIF(a.authors_nicknames::text, '')) AS author_name,
                  COALESCE(c.c_texts_text_content::text, '') AS caption,
                  a.authors_followercount::text AS followers_text,
                  a.authors_heartcount::text AS hearts_text,
                  a.authors_videocount::text AS videos_count_text,
                  a.authors_signature::text AS signature,
                  a.authors_privateaccount AS is_private,
                  CASE WHEN b.bookmarks_bookmark_id IS NULL THEN 0 ELSE 1 END AS bookmarked,
                  b.bookmarks_timestamp::text AS bookmark_timestamp,
                  COALESCE(NULLIF(m.local_rel_video_path::text, ''), NULLIF(m.video_path::text, '')) AS video_path,
                  COALESCE(NULLIF(m.local_rel_cover_path::text, ''), NULLIF(m.cover_path::text, '')) AS cover_path
                                FROM {schema}.consolidated c
                                LEFT JOIN {schema}.authors a
                  ON a.authors_id = c.c_videos_authorid
                                LEFT JOIN {schema}.bookmarks b
                  ON b.bookmarks_bookmark_id = c.c_videos_id
                                LEFT JOIN {schema}.media m
                  ON m.video_id = c.c_videos_id
                WHERE c.c_videos_id IS NOT NULL AND TRIM(c.c_videos_id::text) <> ''
            """
            cur.execute(sql)

            for row in cur.fetchall():
                rid = str(row[0] or "").strip()
                if not rid:
                    continue

                author_id = str(row[1] or "").strip() or None
                is_bookmarked = 1 if int(row[10] or 0) == 1 else 0

                video_path = str(row[12] or "").strip() or None
                cover_path = str(row[13] or "").strip() or None
                if not video_path or not cover_path:
                    base = "Favorites" if is_bookmarked else (f"Following/{author_id}" if author_id else "Following")
                    if not video_path:
                        video_path = f"{base}/videos/{rid}.mp4"
                    if not cover_path:
                        cover_path = f"{base}/covers/{rid}.jpg"

                is_private_raw = row[9]
                if is_private_raw is None:
                    is_private_int = None
                else:
                    is_private_int = 1 if bool(is_private_raw) else 0

                payload = {
                    "source_id": source_id,
                    "id": rid,
                    "platform": "TikTok",
                    "author_id": author_id,
                    "author_unique_id": str(row[2] or "").strip() or None,
                    "author_name": str(row[3] or "").strip() or None,
                    "followers": _to_int(row[5]),
                    "hearts": _to_int(row[6]),
                    "videos_count": _to_int(row[7]),
                    "signature": str(row[8] or "").strip() or None,
                    "is_private": is_private_int,
                    "caption": str(row[4] or ""),
                    "bookmarked": is_bookmarked,
                    "bookmark_timestamp": str(row[11] or "").strip() or None,
                    "video_path": video_path,
                    "cover_path": cover_path,
                    "csv_row_hash": "",
                    "updated_at": now,
                }

                sqlite_conn.execute(
                    """
                    INSERT INTO videos(
                      source_id, id, platform, author_id, author_unique_id, author_name,
                      followers, hearts, videos_count, signature, is_private,
                      caption, bookmarked, bookmark_timestamp, video_path, cover_path,
                      csv_row_hash, updated_at
                    ) VALUES(
                      :source_id, :id, :platform, :author_id, :author_unique_id, :author_name,
                      :followers, :hearts, :videos_count, :signature, :is_private,
                      :caption, :bookmarked, :bookmark_timestamp, :video_path, :cover_path,
                      :csv_row_hash, :updated_at
                    )
                    ON CONFLICT(source_id, id) DO UPDATE SET
                      platform=excluded.platform,
                      author_id=excluded.author_id,
                      author_unique_id=excluded.author_unique_id,
                      author_name=excluded.author_name,
                      followers=excluded.followers,
                      hearts=excluded.hearts,
                      videos_count=excluded.videos_count,
                      signature=excluded.signature,
                      is_private=excluded.is_private,
                      caption=excluded.caption,
                      bookmarked=excluded.bookmarked,
                      bookmark_timestamp=excluded.bookmark_timestamp,
                      video_path=excluded.video_path,
                      cover_path=excluded.cover_path,
                      updated_at=excluded.updated_at
                    """,
                    payload,
                )
                mirrored += 1

    sqlite_conn.commit()
    if mirrored > 0 and bool(settings.SX_DB_ENABLE_FTS):
        rebuild_fts(sqlite_conn)

    return {
        "backend": "postgres_mirror",
        "active": True,
        "mirrored": int(mirrored),
        "source_id": source_id,
        "schema": schema,
        "search_path": search_path,
        "reason": "mirrored from PostgreSQL into sqlite-compatible schema",
    }


def maybe_sync_postgres_mirror(settings: Settings, source_id: str) -> dict[str, Any]:
    sid = _sanitize_source_id(source_id, fallback=str(settings.SX_DEFAULT_SOURCE_ID or "default"))

    pg_url, mode, backend_mode = _resolve_pg_url_and_mode(settings)
    schema = _schema_from_pg_url(pg_url or "") or _safe_ident(getattr(settings, "SXCTL_SCHEMA_NAME", "") or "")
    search_path = f"{schema},public" if schema else ""
    if backend_mode not in {"POSTGRES", "POSTGRES_MIRROR"}:
        return {
            "backend": "sqlite",
            "active": False,
            "reason": f"SX_DB_BACKEND_MODE={backend_mode}",
            "source_id": sid,
            "pipeline_db_mode": mode,
            "schema": schema,
            "search_path": search_path,
        }

    if mode in {"SQL", "SQLITE"}:
        return {
            "backend": "sqlite",
            "active": False,
            "reason": f"SX_PIPELINE_DB_MODE={mode}",
            "source_id": sid,
            "pipeline_db_mode": mode,
            "schema": schema,
            "search_path": search_path,
        }

    if not pg_url:
        return {
            "backend": "sqlite",
            "active": False,
            "reason": "No PostgreSQL URL resolved from selected profile",
            "source_id": sid,
            "pipeline_db_mode": mode,
            "schema": schema,
            "search_path": search_path,
        }

    ttl = int(getattr(settings, "SX_DB_BACKEND_SYNC_TTL_SEC", 120) or 120)
    key = (sid, f"{mode}:{pg_url}")
    now = time.time()
    last = _LAST_SYNC.get(key, 0.0)
    if ttl > 0 and (now - last) < ttl:
        return {
            "backend": "postgres_mirror",
            "active": True,
            "reason": f"sync throttled by TTL ({ttl}s)",
            "source_id": sid,
            "pipeline_db_mode": mode,
            "mirrored": 0,
            "ttl_skipped": True,
            "schema": schema,
            "search_path": search_path,
        }

    out = _sync_from_postgres(settings, sid, pg_url)
    _LAST_SYNC[key] = now
    out["pipeline_db_mode"] = mode
    return out
