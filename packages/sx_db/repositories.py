from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from .db import (
    connect,
    ensure_source,
    get_default_source_id,
    init_db,
    list_sources,
    set_default_source,
)
from .settings import Settings


class Repository(Protocol):
    backend_name: str

    def get_health(self, source_id: str) -> dict[str, Any]: ...

    def list_sources(self) -> dict[str, Any]: ...

    def list_items(self, source_id: str, *, limit: int = 50, offset: int = 0) -> dict[str, Any]: ...

    def get_item(self, source_id: str, item_id: str) -> dict[str, Any] | None: ...

    def write_item(self, source_id: str, payload: dict[str, Any]) -> dict[str, Any]: ...

    def init_schema(self, source_id: str) -> dict[str, Any]: ...


_SAFE_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def sanitize_source_id(v: object, fallback: str = "default") -> str:
    raw = str(v or "").strip() or str(fallback or "default").strip()
    cleaned = re.sub(r"[^a-zA-Z0-9._-]", "", raw)
    return cleaned or "default"


def safe_ident(name: str) -> str:
    s = str(name or "").strip()
    if not _SAFE_IDENT.match(s):
        raise ValueError(f"invalid SQL identifier: {name!r}")
    return s


def _extract_trailing_profile_index(value: str) -> int | None:
    s = str(value or "").strip().lower()
    if not s:
        return None
    m = re.search(r"(?:^|[_-])(?:p)?(\d{1,2})$", s)
    if not m:
        return None
    try:
        n = int(m.group(1))
    except Exception:
        return None
    return n if n >= 1 else None


def _extract_schema_profile_index(schema_name: str) -> int | None:
    s = str(schema_name or "").strip().lower()
    if not s:
        return None
    # Unified schema convention examples:
    # - sx_p01_assets_1
    # - myprefix_p02
    m = re.search(r"(?:^|_)p(\d{2})(?:_|$)", s)
    if not m:
        return None
    try:
        n = int(m.group(1))
    except Exception:
        return None
    return n if n >= 1 else None


class SqliteRepository:
    backend_name = "sqlite"

    def __init__(self, settings: Settings):
        self.settings = settings

    def _conn(self):
        conn = connect(self.settings.SX_DB_PATH)
        init_db(conn, enable_fts=self.settings.SX_DB_ENABLE_FTS)
        return conn

    def init_schema(self, source_id: str) -> dict[str, Any]:
        sid = sanitize_source_id(source_id, fallback=self.settings.SX_DEFAULT_SOURCE_ID)
        conn = self._conn()
        ensure_source(conn, sid, label=sid)
        conn.commit()
        return {"ok": True, "source_id": sid, "backend": self.backend_name}

    def get_health(self, source_id: str) -> dict[str, Any]:
        sid = sanitize_source_id(source_id, fallback=self.settings.SX_DEFAULT_SOURCE_ID)
        conn = self._conn()
        ensure_source(conn, sid, label=sid)
        conn.commit()
        return {
            "ok": True,
            "backend": "sqlite",
            "active": True,
            "source_id": sid,
        }

    def list_sources(self) -> dict[str, Any]:
        conn = self._conn()
        default_sid = sanitize_source_id(self.settings.SX_DEFAULT_SOURCE_ID)
        ensure_source(conn, default_sid, label=default_sid)
        if not conn.execute("SELECT 1 FROM sources WHERE is_default=1 LIMIT 1").fetchone():
            set_default_source(conn, default_sid)
        conn.commit()
        return {
            "sources": list_sources(conn),
            "default_source_id": get_default_source_id(conn, fallback=default_sid),
        }

    def list_items(self, source_id: str, *, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        sid = sanitize_source_id(source_id, fallback=self.settings.SX_DEFAULT_SOURCE_ID)
        conn = self._conn()
        rows = conn.execute(
            """
            SELECT id, platform, author_id, author_unique_id, author_name, caption,
                   bookmarked, video_path, cover_path, updated_at
            FROM videos
            WHERE source_id=?
            ORDER BY updated_at DESC
            LIMIT ? OFFSET ?
            """,
            (sid, limit, offset),
        ).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM videos WHERE source_id=?", (sid,)).fetchone()[0]
        return {"items": [dict(r) for r in rows], "total": int(total), "limit": limit, "offset": offset}

    def get_item(self, source_id: str, item_id: str) -> dict[str, Any] | None:
        sid = sanitize_source_id(source_id, fallback=self.settings.SX_DEFAULT_SOURCE_ID)
        conn = self._conn()
        row = conn.execute("SELECT * FROM videos WHERE source_id=? AND id=?", (sid, item_id)).fetchone()
        return dict(row) if row else None

    def write_item(self, source_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        sid = sanitize_source_id(source_id, fallback=self.settings.SX_DEFAULT_SOURCE_ID)
        item_id = str(payload.get("id") or "").strip()
        if not item_id:
            raise ValueError("payload.id is required")

        now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        conn = self._conn()
        conn.execute(
            """
            INSERT INTO videos(source_id, id, platform, caption, bookmarked, updated_at)
            VALUES(?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_id, id) DO UPDATE SET
              platform=excluded.platform,
              caption=excluded.caption,
              bookmarked=excluded.bookmarked,
              updated_at=excluded.updated_at
            """,
            (
                sid,
                item_id,
                payload.get("platform") or "tiktok",
                payload.get("caption") or "",
                int(payload.get("bookmarked") or 0),
                now,
            ),
        )
        conn.commit()
        return {"ok": True, "id": item_id, "source_id": sid, "updated_at": now}


@dataclass
class _FakeCursor:
    _one: Any = None
    _many: list[Any] | None = None

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._many or []


class CompatRow(Mapping[str, Any]):
    def __init__(self, data: dict[str, Any]):
        self._data = dict(data)
        self._keys = list(self._data.keys())
        self._vals = [self._data[k] for k in self._keys]

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._vals[key]
        return self._data[key]

    def __iter__(self):
        return iter(self._data)

    def __len__(self):
        return len(self._data)


class CompatCursor:
    def __init__(self, cur):
        self._cur = cur

    @property
    def rowcount(self) -> int:
        return int(getattr(self._cur, "rowcount", -1))

    def fetchone(self):
        row = self._cur.fetchone()
        if row is None:
            return None
        if isinstance(row, Mapping):
            return CompatRow(dict(row))
        return row

    def fetchall(self):
        rows = self._cur.fetchall() or []
        out = []
        for row in rows:
            if isinstance(row, Mapping):
                out.append(CompatRow(dict(row)))
            else:
                out.append(row)
        return out


class CompatConnection:
    """A small compatibility wrapper so existing sqlite-style query code works on psycopg.

    Supports:
    - positional placeholders `?` → `%s`
    - named placeholders `:name` → `%(name)s`
    - sqlite-master FTS probes (returns no rows in postgres mode)
    """

    def __init__(self, pg_conn):
        self._pg_conn = pg_conn

    def _adapt_sql(self, sql: str, params: Any) -> str:
        s = sql
        if isinstance(params, Mapping):
            s = re.sub(r"(?<!:):([A-Za-z_][A-Za-z0-9_]*)", r"%(\1)s", s)
        else:
            if "?" in s:
                s = s.replace("?", "%s")
        return s

    def execute(self, sql: str, params: Any = ()):
        if "sqlite_master" in sql and "videos_fts" in sql:
            return _FakeCursor(None, [])
        cur = self._pg_conn.cursor()
        cur.execute(self._adapt_sql(sql, params), params)
        return CompatCursor(cur)

    def executemany(self, sql: str, seq_of_params):
        cur = self._pg_conn.cursor()
        adapted = None
        for params in seq_of_params:
            if adapted is None:
                adapted = self._adapt_sql(sql, params)
            cur.execute(adapted, params)
        return CompatCursor(cur)

    def commit(self) -> None:
        self._pg_conn.commit()

    def rollback(self) -> None:
        self._pg_conn.rollback()

    def close(self) -> None:
        self._pg_conn.close()


class PostgresRepository:
    backend_name = "postgres_primary"

    def __init__(self, settings: Settings):
        self.settings = settings
        self._dsn = str(settings.SX_POSTGRES_DSN or "").strip()
        self._schema_prefix = safe_ident(str(settings.SX_POSTGRES_SCHEMA_PREFIX or "sx"))
        self._registry_table = safe_ident(str(settings.SX_POSTGRES_REGISTRY_TABLE or "sx_source_registry"))

    def _require_psycopg(self):
        try:
            import psycopg  # type: ignore
            from psycopg.rows import dict_row  # type: ignore
        except Exception as e:  # pragma: no cover
            raise RuntimeError(f"psycopg is required for POSTGRES_PRIMARY: {e}")
        if not self._dsn:
            raise RuntimeError("SX_POSTGRES_DSN is required for POSTGRES_PRIMARY")
        return psycopg, dict_row

    def _connect(self):
        psycopg, dict_row = self._require_psycopg()
        return psycopg.connect(self._dsn, row_factory=dict_row)

    def schema_name_for_source(self, source_id: str) -> str:
        sid = sanitize_source_id(source_id, fallback=self.settings.SX_DEFAULT_SOURCE_ID)
        raw = f"{self._schema_prefix}_{sid}".replace(".", "_").replace("-", "_")
        return safe_ident(raw)

    def _assert_schema_index_guard(self, source_id: str, schema_name: str) -> None:
        if not bool(getattr(self.settings, "SX_SCHEMA_INDEX_GUARD", True)):
            return

        sid = sanitize_source_id(source_id, fallback=self.settings.SX_DEFAULT_SOURCE_ID)
        schema = safe_ident(schema_name)

        schema_idx = _extract_schema_profile_index(schema)
        # Guard is only enforced for unified indexed schemas (sx_pNN_* style).
        if schema_idx is None:
            return

        source_idx = _extract_trailing_profile_index(sid)
        profile_idx = _extract_trailing_profile_index(str(getattr(self.settings, "SX_PROFILE_INDEX", "") or ""))

        if source_idx is not None and profile_idx is not None and source_idx != profile_idx:
            raise RuntimeError(
                "Schema-index safety guard blocked request: "
                f"source_id={sid!r} implies profile #{source_idx}, "
                f"but selected SX_PROFILE_INDEX is #{profile_idx}."
            )

        expected_idx = source_idx if source_idx is not None else profile_idx
        if expected_idx is None:
            return

        if schema_idx != expected_idx:
            raise RuntimeError(
                "Schema-index safety guard blocked request: "
                f"schema={schema!r} is profile #{schema_idx}, "
                f"but expected profile #{expected_idx} for source_id={sid!r}."
            )

    def _ensure_global_tables(self, conn) -> None:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS public.sources (
                    id TEXT PRIMARY KEY,
                    label TEXT,
                    kind TEXT,
                    description TEXT,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    is_default INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT,
                    updated_at TEXT
                )
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_sources_enabled ON public.sources(enabled)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_sources_default ON public.sources(is_default)")
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS public.{self._registry_table} (
                    source_id TEXT PRIMARY KEY,
                    schema_name TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
        conn.commit()

    def _create_schema_objects(self, conn, schema: str) -> None:
        safe_schema = safe_ident(schema)
        with conn.cursor() as cur:
            cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{safe_schema}"')
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS "{safe_schema}".videos (
                    source_id TEXT NOT NULL DEFAULT 'default',
                    id TEXT NOT NULL,
                    platform TEXT,
                    author_id TEXT,
                    author_unique_id TEXT,
                    author_name TEXT,
                    followers INTEGER,
                    hearts INTEGER,
                    videos_count INTEGER,
                    signature TEXT,
                    is_private INTEGER,
                    caption TEXT,
                    bookmarked INTEGER DEFAULT 0,
                    bookmark_timestamp TEXT,
                    video_path TEXT,
                    cover_path TEXT,
                    csv_row_hash TEXT,
                    updated_at TEXT,
                    PRIMARY KEY(source_id, id)
                )
                """
            )
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS "{safe_schema}".user_meta (
                    source_id TEXT NOT NULL DEFAULT 'default',
                    video_id TEXT NOT NULL,
                    rating INTEGER,
                    status TEXT,
                    statuses TEXT,
                    tags TEXT,
                    notes TEXT,
                    product_link TEXT,
                    author_links TEXT,
                    platform_targets TEXT,
                    workflow_log TEXT,
                    post_url TEXT,
                    published_time TEXT,
                    updated_at TEXT,
                    PRIMARY KEY(source_id, video_id)
                )
                """
            )
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS "{safe_schema}".video_notes (
                    source_id TEXT NOT NULL DEFAULT 'default',
                    video_id TEXT NOT NULL,
                    markdown TEXT NOT NULL,
                    template_version TEXT,
                    updated_at TEXT,
                    PRIMARY KEY(source_id, video_id)
                )
                """
            )
            # Add sqlite-parity FKs using NOT VALID so existing legacy rows don't block bootstrapping.
            # They still protect all newly-written rows; explicit validation can be done later if desired.
            cur.execute(
                f"""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1
                        FROM pg_constraint c
                        JOIN pg_namespace n ON n.oid = c.connamespace
                        WHERE n.nspname = '{safe_schema}'
                          AND c.conname = 'fk_user_meta_videos'
                    ) THEN
                        ALTER TABLE "{safe_schema}".user_meta
                          ADD CONSTRAINT fk_user_meta_videos
                          FOREIGN KEY (source_id, video_id)
                          REFERENCES "{safe_schema}".videos(source_id, id)
                          ON DELETE CASCADE
                          NOT VALID;
                    END IF;
                END
                $$;
                """
            )
            cur.execute(
                f"""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1
                        FROM pg_constraint c
                        JOIN pg_namespace n ON n.oid = c.connamespace
                        WHERE n.nspname = '{safe_schema}'
                          AND c.conname = 'fk_video_notes_videos'
                    ) THEN
                        ALTER TABLE "{safe_schema}".video_notes
                          ADD CONSTRAINT fk_video_notes_videos
                          FOREIGN KEY (source_id, video_id)
                          REFERENCES "{safe_schema}".videos(source_id, id)
                          ON DELETE CASCADE
                          NOT VALID;
                    END IF;
                END
                $$;
                """
            )
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS "{safe_schema}".csv_consolidated_raw (
                    source_id TEXT NOT NULL DEFAULT 'default',
                    video_id TEXT NOT NULL,
                    row_json TEXT NOT NULL,
                    csv_row_hash TEXT,
                    imported_at TEXT,
                    PRIMARY KEY(source_id, video_id)
                )
                """
            )
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS "{safe_schema}".csv_authors_raw (
                    source_id TEXT NOT NULL DEFAULT 'default',
                    author_id TEXT NOT NULL,
                    row_json TEXT NOT NULL,
                    imported_at TEXT,
                    PRIMARY KEY(source_id, author_id)
                )
                """
            )
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS "{safe_schema}".csv_bookmarks_raw (
                    source_id TEXT NOT NULL DEFAULT 'default',
                    video_id TEXT NOT NULL,
                    row_json TEXT NOT NULL,
                    imported_at TEXT,
                    PRIMARY KEY(source_id, video_id)
                )
                """
            )
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS "{safe_schema}".scheduling_artifacts (
                    source_id TEXT NOT NULL DEFAULT 'default',
                    video_id TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    artifact_json TEXT NOT NULL,
                    r2_media_url TEXT,
                    status TEXT NOT NULL DEFAULT 'draft_review',
                    created_at TEXT,
                    updated_at TEXT,
                    PRIMARY KEY(source_id, video_id, platform)
                )
                """
            )
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS "{safe_schema}".job_queue (
                    id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL DEFAULT 'default',
                    video_id TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    action TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    scheduled_time TEXT,
                    execute_after TEXT,
                    result_json TEXT,
                    error_message TEXT,
                    retry_count INTEGER DEFAULT 0,
                    created_at TEXT,
                    updated_at TEXT
                )
                """
            )
            cur.execute(f'CREATE INDEX IF NOT EXISTS idx_{safe_schema}_videos_updated ON "{safe_schema}".videos(updated_at DESC)')
            cur.execute(f'CREATE INDEX IF NOT EXISTS idx_{safe_schema}_videos_author_uid ON "{safe_schema}".videos(author_unique_id)')
            cur.execute(f'CREATE INDEX IF NOT EXISTS idx_{safe_schema}_videos_bookmarked ON "{safe_schema}".videos(bookmarked)')
            cur.execute(f'CREATE INDEX IF NOT EXISTS idx_{safe_schema}_user_meta_status ON "{safe_schema}".user_meta(status)')
            cur.execute(f'CREATE INDEX IF NOT EXISTS idx_{safe_schema}_user_meta_source_id ON "{safe_schema}".user_meta(source_id)')
            cur.execute(f'CREATE INDEX IF NOT EXISTS idx_{safe_schema}_user_meta_statuses ON "{safe_schema}".user_meta(statuses)')
            cur.execute(f'CREATE INDEX IF NOT EXISTS idx_{safe_schema}_video_notes_source_id ON "{safe_schema}".video_notes(source_id)')
            cur.execute(f'CREATE INDEX IF NOT EXISTS idx_{safe_schema}_csv_consolidated_hash ON "{safe_schema}".csv_consolidated_raw(csv_row_hash)')
        conn.commit()

    def _schema_has_required_layout(self, conn, schema: str) -> bool:
        """Return True when schema appears compatible with sx_obsidian tables.

        We only need a lightweight check to avoid writing into foreign/legacy schemas
        that reuse table names with different structures.
        """
        safe_schema = safe_ident(schema)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema=%s AND table_name='videos'
                """,
                (safe_schema,),
            )
            cols = {str(r.get("column_name")) for r in (cur.fetchall() or []) if r and r.get("column_name")}

            # If no videos table exists yet, we can safely initialize this schema.
            if not cols:
                return True

            required = {"source_id", "id", "author_unique_id", "updated_at"}
            if not required.issubset(cols):
                return False

            cur.execute(
                """
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema=%s AND table_name='csv_authors_raw'
                LIMIT 1
                """,
                (safe_schema,),
            )
            return bool(cur.fetchone())

    def resolve_schema(self, source_id: str, *, create_if_missing: bool = False) -> str:
        sid = sanitize_source_id(source_id, fallback=self.settings.SX_DEFAULT_SOURCE_ID)
        canonical_schema = self.schema_name_for_source(sid)
        with self._connect() as conn:
            self._ensure_global_tables(conn)
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT schema_name FROM public.{self._registry_table} WHERE source_id=%s",
                    (sid,),
                )
                row = cur.fetchone()
                if row and row.get("schema_name"):
                    schema = safe_ident(str(row["schema_name"]))
                    if create_if_missing:
                        # Existing mapping may point to a legacy/shared schema that is
                        # incompatible with sx_obsidian table layout. In that case,
                        # transparently remap this source to the canonical dedicated
                        # schema and initialize objects there.
                        if not self._schema_has_required_layout(conn, schema):
                            now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
                            cur.execute(
                                f"""
                                UPDATE public.{self._registry_table}
                                SET schema_name=%s, updated_at=%s
                                WHERE source_id=%s
                                """,
                                (canonical_schema, now, sid),
                            )
                            conn.commit()
                            self._create_schema_objects(conn, canonical_schema)
                            self._assert_schema_index_guard(sid, canonical_schema)
                            return canonical_schema

                        # Compatible mapped schema: ensure all required tables/indexes.
                        self._create_schema_objects(conn, schema)
                    self._assert_schema_index_guard(sid, schema)
                    return schema

                if not create_if_missing:
                    raise KeyError(f"No schema mapping for source_id={sid}")

                schema = canonical_schema
                now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
                cur.execute(
                    f"""
                    INSERT INTO public.{self._registry_table}(source_id, schema_name, created_at, updated_at)
                    VALUES(%s, %s, %s, %s)
                    ON CONFLICT(source_id) DO UPDATE SET
                      schema_name=EXCLUDED.schema_name,
                      updated_at=EXCLUDED.updated_at
                    """,
                    (sid, schema, now, now),
                )
                cur.execute(
                    """
                    INSERT INTO public.sources(id, label, enabled, is_default, created_at, updated_at)
                    VALUES(%s, %s, 1, 0, %s, %s)
                    ON CONFLICT(id) DO UPDATE SET updated_at=EXCLUDED.updated_at
                    """,
                    (sid, sid, now, now),
                )
            conn.commit()

        with self._connect() as conn2:
            self._create_schema_objects(conn2, schema)
        self._assert_schema_index_guard(sid, schema)
        return schema

    def init_schema(self, source_id: str) -> dict[str, Any]:
        sid = sanitize_source_id(source_id, fallback=self.settings.SX_DEFAULT_SOURCE_ID)
        schema = self.resolve_schema(sid, create_if_missing=True)
        return {"ok": True, "backend": self.backend_name, "source_id": sid, "schema": schema}

    def connection_for_source(self, source_id: str) -> CompatConnection:
        sid = sanitize_source_id(source_id, fallback=self.settings.SX_DEFAULT_SOURCE_ID)
        schema = self.resolve_schema(sid, create_if_missing=False)
        self._assert_schema_index_guard(sid, schema)
        conn = self._connect()
        with conn.cursor() as cur:
            cur.execute(f'SET search_path TO "{schema}", public')
        return CompatConnection(conn)

    def get_health(self, source_id: str) -> dict[str, Any]:
        sid = sanitize_source_id(source_id, fallback=self.settings.SX_DEFAULT_SOURCE_ID)
        schema = self.resolve_schema(sid, create_if_missing=False)
        return {
            "ok": True,
            "backend": self.backend_name,
            "active": True,
            "source_id": sid,
            "schema": schema,
            "search_path": f"{schema},public",
        }

    def list_sources(self) -> dict[str, Any]:
        with self._connect() as conn:
            self._ensure_global_tables(conn)
            with conn.cursor() as cur:
                cur.execute("SELECT id, label, kind, description, enabled, is_default, created_at, updated_at FROM public.sources ORDER BY id")
                rows = [dict(r) for r in (cur.fetchall() or [])]
                cur.execute("SELECT id FROM public.sources WHERE is_default=1 LIMIT 1")
                d = cur.fetchone()
                default_sid = str(d["id"]) if d and d.get("id") else sanitize_source_id(self.settings.SX_DEFAULT_SOURCE_ID)
                if not d:
                    now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
                    cur.execute(
                        """
                        INSERT INTO public.sources(id, label, enabled, is_default, created_at, updated_at)
                        VALUES(%s, %s, 1, 1, %s, %s)
                        ON CONFLICT(id) DO UPDATE SET is_default=1, updated_at=EXCLUDED.updated_at
                        """,
                        (default_sid, default_sid, now, now),
                    )
                    conn.commit()
        return {"sources": rows, "default_source_id": default_sid}

    def list_items(self, source_id: str, *, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        sid = sanitize_source_id(source_id, fallback=self.settings.SX_DEFAULT_SOURCE_ID)
        conn = self.connection_for_source(sid)
        rows = conn.execute(
            """
            SELECT id, platform, author_id, author_unique_id, author_name, caption,
                   bookmarked, video_path, cover_path, updated_at
            FROM videos
            WHERE source_id=?
            ORDER BY updated_at DESC
            LIMIT ? OFFSET ?
            """,
            (sid, limit, offset),
        ).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM videos WHERE source_id=?", (sid,)).fetchone()[0]
        conn.close()
        return {"items": [dict(r) for r in rows], "total": int(total), "limit": limit, "offset": offset}

    def get_item(self, source_id: str, item_id: str) -> dict[str, Any] | None:
        sid = sanitize_source_id(source_id, fallback=self.settings.SX_DEFAULT_SOURCE_ID)
        conn = self.connection_for_source(sid)
        row = conn.execute("SELECT * FROM videos WHERE source_id=? AND id=?", (sid, item_id)).fetchone()
        conn.close()
        return dict(row) if row else None

    def write_item(self, source_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        sid = sanitize_source_id(source_id, fallback=self.settings.SX_DEFAULT_SOURCE_ID)
        item_id = str(payload.get("id") or "").strip()
        if not item_id:
            raise ValueError("payload.id is required")

        now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        conn = self.connection_for_source(sid)
        conn.execute(
            """
            INSERT INTO videos(source_id, id, platform, caption, bookmarked, updated_at)
            VALUES(?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_id, id) DO UPDATE SET
              platform=excluded.platform,
              caption=excluded.caption,
              bookmarked=excluded.bookmarked,
              updated_at=excluded.updated_at
            """,
            (
                sid,
                item_id,
                payload.get("platform") or "tiktok",
                payload.get("caption") or "",
                int(payload.get("bookmarked") or 0),
                now,
            ),
        )
        conn.commit()
        conn.close()
        return {"ok": True, "id": item_id, "source_id": sid, "updated_at": now}


def get_repository(settings: Settings) -> Repository:
    mode = str(getattr(settings, "SX_DB_BACKEND_MODE", "SQLITE") or "SQLITE").strip().upper()
    if mode == "POSTGRES_PRIMARY":
        return PostgresRepository(settings)
    return SqliteRepository(settings)
