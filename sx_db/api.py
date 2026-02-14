from __future__ import annotations

import mimetypes
import re
import json
from datetime import datetime
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from sx.paths import PathResolver

from .db import connect, init_db
from .markdown import TEMPLATE_VERSION, render_note
from .search import search as search_fn
from .settings import Settings


class MetaIn(BaseModel):
    rating: int | None = None
    status: str | None = None
    statuses: list[str] | str | None = None
    tags: str | None = None
    notes: str | None = None
    product_link: str | None = None
    author_links: list[str] | str | None = None
    platform_targets: str | None = None
    workflow_log: str | None = None
    post_url: str | None = None
    published_time: str | None = None


class MetaOut(MetaIn):
    video_id: str
    updated_at: str | None = None


class NoteIn(BaseModel):
    markdown: str
    template_version: str | None = None


class DangerFilters(BaseModel):
    q: str | None = ""
    bookmarked_only: bool = False
    author_unique_id: str | None = None
    author_id: str | None = None
    status: str | None = None
    rating_min: float | None = None
    rating_max: float | None = None
    tag: str | None = None
    has_notes: bool | None = None


class DangerResetIn(BaseModel):
    """Danger Zone reset request.

    This endpoint is intended for explicit user-initiated recovery actions.
    It supports a dry-run preview by default.
    """

    apply: bool = False
    confirm: str = ""
    filters: DangerFilters = DangerFilters()

    reset_user_meta: bool = True
    reset_user_notes: bool = False
    reset_cached_notes: bool = False


def create_app(settings: Settings) -> FastAPI:
    app = FastAPI(title="sx_obsidian SQLite API", version="0.1.0")

    if settings.SX_API_CORS_ALLOW_ALL:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=False,
            allow_methods=["*"] ,
            allow_headers=["*"],
        )

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.get("/")
    def root():
        return {
            "service": "sx_obsidian SQLite API",
            "ok": True,
            "endpoints": {
                "health": "/health",
                "stats": "/stats",
                "search": "/search?q=...",
                "item": "/items/{id}",
                "note": "/items/{id}/note",
                "docs": "/docs",
            },
        }

    @app.get("/stats")
    def stats():
        """Lightweight DB stats for troubleshooting and plugin UX."""
        conn = connect(settings.SX_DB_PATH)
        init_db(conn, enable_fts=settings.SX_DB_ENABLE_FTS)

        total = conn.execute("SELECT COUNT(*) AS n FROM videos").fetchone()[0]
        bookmarked = conn.execute(
            "SELECT COUNT(*) AS n FROM videos WHERE bookmarked=1"
        ).fetchone()[0]
        authors = conn.execute(
            """
            SELECT COUNT(DISTINCT author_unique_id) AS n
            FROM videos
            WHERE author_unique_id IS NOT NULL AND author_unique_id != ''
            """
        ).fetchone()[0]
        last_updated_at = conn.execute(
            "SELECT MAX(updated_at) AS t FROM videos"
        ).fetchone()[0]

        has_fts = bool(
            conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='videos_fts'"
            ).fetchone()
        )
        fts_rows = (
            conn.execute("SELECT COUNT(*) FROM videos_fts").fetchone()[0] if has_fts else None
        )

        return {
            "db_path": str(settings.SX_DB_PATH),
            "fts_enabled": bool(settings.SX_DB_ENABLE_FTS),
            "has_fts_table": has_fts,
            "counts": {
                "items": int(total),
                "bookmarked": int(bookmarked),
                "authors": int(authors),
                "fts_rows": int(fts_rows) if fts_rows is not None else None,
            },
            "last_updated_at": last_updated_at,
        }

    @app.get("/search")
    def search(q: str = "", limit: int = 50, offset: int = 0):
        conn = connect(settings.SX_DB_PATH)
        init_db(conn, enable_fts=settings.SX_DB_ENABLE_FTS)
        results = search_fn(conn, q, limit=limit, offset=offset)
        return {"results": results, "limit": limit, "offset": offset}

    def _conn():
        conn = connect(settings.SX_DB_PATH)
        init_db(conn, enable_fts=settings.SX_DB_ENABLE_FTS)
        return conn

    def _normalize_status_list(v: object) -> list[str]:
        """Accept a scalar, list, or comma-separated string and return a de-duped list."""

        if v is None:
            return []
        if isinstance(v, list):
            parts = [str(x).strip() for x in v]
        else:
            s = str(v).strip()
            if not s:
                return []
            parts = [p.strip() for p in s.split(",")]

        out: list[str] = []
        seen: set[str] = set()
        for p in parts:
            if not p:
                continue
            if p in seen:
                continue
            seen.add(p)
            out.append(p)
        return out

    def _pack_statuses(statuses: list[str]) -> str | None:
        if not statuses:
            return None
        # Store with boundary markers for reliable LIKE matching.
        # Example: |raw|reviewing|
        return "|" + "|".join(statuses) + "|"

    def _unpack_statuses(packed: object) -> list[str]:
        s = str(packed or "").strip()
        if not s:
            return []
        if s.startswith("|") and s.endswith("|"):
            parts = [p.strip() for p in s.split("|") if p.strip()]
            return _normalize_status_list(parts)
        # Fallback: accept comma-separated legacy formats.
        return _normalize_status_list(s)

    def _primary_status_from_list(statuses: list[str]) -> str | None:
        if not statuses:
            return None
        # Prefer the most "advanced" status for consistent sorting.
        try:
            from .markdown import WORKFLOW_STATUSES
        except Exception:
            WORKFLOW_STATUSES = []  # type: ignore

        if WORKFLOW_STATUSES:
            ranked = [s for s in WORKFLOW_STATUSES if s in statuses]
            if ranked:
                return ranked[-1]
        return statuses[0]

    def _normalize_url_list(v: object) -> list[str]:
        """Accept list/JSON/csv/newline input and return de-duped URLs."""

        if v is None:
            return []

        raw_items: list[str]
        if isinstance(v, list):
            raw_items = [str(x).strip() for x in v]
        else:
            s = str(v).strip()
            if not s:
                return []
            # Try JSON array first.
            if s.startswith("[") and s.endswith("]"):
                try:
                    obj = json.loads(s)
                    if isinstance(obj, list):
                        raw_items = [str(x).strip() for x in obj]
                    else:
                        raw_items = [s]
                except Exception:
                    raw_items = [p.strip() for p in re.split(r"[,\n]", s)]
            else:
                raw_items = [p.strip() for p in re.split(r"[,\n]", s)]

        out: list[str] = []
        seen: set[str] = set()
        for x in raw_items:
            if not x:
                continue
            if x in seen:
                continue
            seen.add(x)
            out.append(x)
        return out

    def _pack_url_list(urls: list[str]) -> str | None:
        if not urls:
            return None
        return json.dumps(urls, ensure_ascii=False)

    def _unpack_url_list(raw: object) -> list[str]:
        return _normalize_url_list(raw)

    def _parse_advanced_terms(raw: str) -> tuple[list[str], list[str]]:
        """Parse a simple "advanced" query string into include/exclude terms.

        Supports:
        - words: furniture chair
        - quoted phrases: "mid century"
        - exclusion: -broken

        This is intentionally conservative (LIKE-based) and works even when FTS is disabled.
        """

        s = (raw or "").strip()
        if not s:
            return [], []

        include: list[str] = []
        exclude: list[str] = []

        # Extract quoted phrases or bare tokens.
        for m in re.finditer(r'"([^"]+)"|(\S+)', s):
            term = (m.group(1) or m.group(2) or "").strip()
            if not term:
                continue
            if term.startswith("-") and len(term) > 1:
                t = term[1:].strip()
                if t:
                    exclude.append(t)
                continue
            include.append(term)

        # De-dupe while preserving order.
        def _dedupe(xs: list[str]) -> list[str]:
            seen: set[str] = set()
            out: list[str] = []
            for x in xs:
                if x in seen:
                    continue
                seen.add(x)
                out.append(x)
            return out

        return _dedupe(include), _dedupe(exclude)

    def _build_where_for_filters(f: DangerFilters) -> tuple[str, list[object]]:
        """Build WHERE clause + params for filters that may reference user_meta."""

        where: list[str] = []
        params: list[object] = []

        if f.bookmarked_only:
            where.append("v.bookmarked=1")

        if f.author_unique_id:
            ids = [a.strip() for a in (f.author_unique_id or "").split(",") if a.strip()]
            if ids:
                where.append("v.author_unique_id IN (" + ",".join(["?"] * len(ids)) + ")")
                params.extend(ids)

        if f.author_id:
            ids = [a.strip() for a in (f.author_id or "").split(",") if a.strip()]
            if ids:
                where.append("v.author_id IN (" + ",".join(["?"] * len(ids)) + ")")
                params.extend(ids)

        if f.status is not None:
            parts = [p.strip() for p in (f.status or "").split(",")]
            parts = [p for p in parts if p is not None]
            wants_unassigned = any(p == "" for p in parts)
            vals = [p for p in parts if p != ""]

            clauses: list[str] = []
            if wants_unassigned:
                clauses.append("((m.status IS NULL OR m.status='') AND (m.statuses IS NULL OR m.statuses=''))")
            if vals:
                clauses.append("m.status IN (" + ",".join(["?"] * len(vals)) + ")")
                params.extend(vals)
                like_clauses = []
                for v in vals:
                    like_clauses.append("COALESCE(m.statuses, '') LIKE ?")
                    params.append(f"%|{v}|%")
                clauses.append("(" + " OR ".join(like_clauses) + ")")
            if clauses:
                where.append("(" + " OR ".join(clauses) + ")")

        if f.rating_min is not None:
            where.append("m.rating IS NOT NULL AND m.rating >= ?")
            params.append(float(f.rating_min))

        if f.rating_max is not None:
            where.append("m.rating IS NOT NULL AND m.rating <= ?")
            params.append(float(f.rating_max))

        if f.has_notes is not None:
            if f.has_notes:
                where.append("COALESCE(TRIM(m.notes), '') <> ''")
            else:
                where.append("COALESCE(TRIM(m.notes), '') = ''")

        if f.tag:
            tags = [t.strip().lower() for t in (f.tag or "").split(",") if t.strip()]
            if tags:
                clauses = []
                for t in tags:
                    clauses.append("(',' || LOWER(COALESCE(m.tags, '')) || ',') LIKE ?")
                    params.append(f"%,{t},%")
                where.append("(" + " OR ".join(clauses) + ")")

        q = (f.q or "").strip()
        if q:
            like = f"%{q}%"
            where.append(
                "(v.caption LIKE ? OR v.author_unique_id LIKE ? OR v.author_name LIKE ? OR v.id LIKE ?)"
            )
            params.extend([like, like, like, like])

        where_sql = ("WHERE " + " AND ".join(where)) if where else ""
        return where_sql, params

    @app.post("/danger/reset")
    def danger_reset(payload: DangerResetIn = Body(...)) -> dict:
        """Danger Zone reset.

        Supports dry-run previews (default). On apply:
        - reset_user_meta deletes rows from user_meta
        - reset_user_notes deletes rows from video_notes where template_version='user'
        - reset_cached_notes deletes rows from video_notes where template_version!='user'

        Scope is controlled by `filters` (same semantics as /items).
        """

        conn = _conn()
        f = payload.filters or DangerFilters()
        where_sql, params = _build_where_for_filters(f)

        # Subquery for the target set
        subq = f"SELECT v.id FROM videos v LEFT JOIN user_meta m ON m.video_id=v.id {where_sql}"

        matched = conn.execute(
            f"SELECT COUNT(*) FROM videos v LEFT JOIN user_meta m ON m.video_id=v.id {where_sql}",
            tuple(params),
        ).fetchone()[0]

        meta_to_delete = 0
        user_notes_to_delete = 0
        cached_notes_to_delete = 0

        if payload.reset_user_meta:
            meta_to_delete = conn.execute(
                f"SELECT COUNT(*) FROM user_meta WHERE video_id IN ({subq})",
                tuple(params),
            ).fetchone()[0]

        if payload.reset_user_notes:
            user_notes_to_delete = conn.execute(
                f"SELECT COUNT(*) FROM video_notes WHERE template_version='user' AND video_id IN ({subq})",
                tuple(params),
            ).fetchone()[0]

        if payload.reset_cached_notes:
            cached_notes_to_delete = conn.execute(
                f"SELECT COUNT(*) FROM video_notes WHERE template_version!='user' AND video_id IN ({subq})",
                tuple(params),
            ).fetchone()[0]

        # Dry run preview
        if not payload.apply:
            return {
                "ok": True,
                "apply": False,
                "matched": int(matched),
                "would_delete": {
                    "user_meta": int(meta_to_delete),
                    "user_notes": int(user_notes_to_delete),
                    "cached_notes": int(cached_notes_to_delete),
                },
            }

        if (payload.confirm or "").strip() != "RESET":
            raise HTTPException(status_code=400, detail="Missing confirmation. Set confirm='RESET' to apply.")

        if not (payload.reset_user_meta or payload.reset_user_notes or payload.reset_cached_notes):
            raise HTTPException(status_code=400, detail="No reset operations selected")

        if payload.reset_user_meta:
            conn.execute(
                f"DELETE FROM user_meta WHERE video_id IN ({subq})",
                tuple(params),
            )

        if payload.reset_user_notes:
            conn.execute(
                f"DELETE FROM video_notes WHERE template_version='user' AND video_id IN ({subq})",
                tuple(params),
            )

        if payload.reset_cached_notes:
            conn.execute(
                f"DELETE FROM video_notes WHERE template_version!='user' AND video_id IN ({subq})",
                tuple(params),
            )

        conn.commit()

        return {
            "ok": True,
            "apply": True,
            "matched": int(matched),
            "deleted": {
                "user_meta": int(meta_to_delete) if payload.reset_user_meta else 0,
                "user_notes": int(user_notes_to_delete) if payload.reset_user_notes else 0,
                "cached_notes": int(cached_notes_to_delete) if payload.reset_cached_notes else 0,
            },
        }

    def _note_resolver() -> PathResolver:
        # Build a resolver using generator-style config.
        config = {
            "path_style": settings.PATH_STYLE,
            "vault": settings.VAULT_default,
            "vault_windows": settings.VAULT_WINDOWS_default,
            "data_dir": settings.DATA_DIR,
        }
        return PathResolver(config)

    def _canonical_media_paths(*, item_id: str, bookmarked: object, author_id: object) -> tuple[str, str]:
        """Derive canonical relative media paths from minimal fields.

        This keeps the API usable even for older DBs or importers where
        `videos.video_path` / `videos.cover_path` were not persisted.
        """

        if isinstance(bookmarked, bool):
            is_bookmarked = bookmarked
        elif isinstance(bookmarked, int):
            is_bookmarked = bool(bookmarked)
        else:
            b = str(bookmarked or "").strip().lower()
            if b in {"1", "true", "yes", "y"}:
                is_bookmarked = True
            elif b in {"0", "false", "no", "n", ""}:
                is_bookmarked = False
            else:
                is_bookmarked = bool(bookmarked)
        aid = str(author_id or "").strip() or None
        base = "Favorites" if is_bookmarked else (f"Following/{aid}" if aid else "Following")
        return (f"{base}/videos/{item_id}.mp4", f"{base}/covers/{item_id}.jpg")

    def _ensure_media_paths(video: dict) -> dict:
        item_id = str(video.get("id") or "").strip()
        if not item_id:
            return video

        vp = video.get("video_path")
        cp = video.get("cover_path")
        if vp and cp:
            return video

        derived_vp, derived_cp = _canonical_media_paths(
            item_id=item_id,
            bookmarked=video.get("bookmarked"),
            author_id=video.get("author_id"),
        )
        if not vp:
            video["video_path"] = derived_vp
        if not cp:
            video["cover_path"] = derived_cp
        return video

    def _fetch_video_with_meta(conn, item_id: str) -> dict | None:
        row = conn.execute(
            """
            SELECT
              v.*, 
                            m.rating, m.status, m.statuses, m.tags, m.notes,
                                                        m.product_link, m.author_links, m.platform_targets, m.workflow_log, m.post_url, m.published_time
            FROM videos v
            LEFT JOIN user_meta m ON m.video_id = v.id
            WHERE v.id=?
            """,
            (item_id,),
        ).fetchone()
        return dict(row) if row else None

    def _get_cached_note(conn, item_id: str) -> tuple[str, str | None] | None:
        """Return cached markdown from DB.

        Notes are user-owned once persisted: if a user edits the synced .md in Obsidian
        and pushes it back, we must not discard it just because the template version changed.
        Use `force=true` to regenerate from the latest template.
        """

        row = conn.execute(
            "SELECT markdown, template_version FROM video_notes WHERE video_id=?",
            (item_id,),
        ).fetchone()
        if not row:
            return None
        return (row[0], row[1])

    def _render_and_cache_note(conn, video: dict) -> str:
        _ensure_media_paths(video)

        resolver = _note_resolver()

        # When media isn't present on disk, returning a note can be useful for
        # diagnostics (it will include `media_missing: true`), but caching it
        # into the DB tends to create confusing "phantom" notes. Treat such
        # notes as ephemeral by default.
        vp = video.get("video_path")
        cp = video.get("cover_path")
        media_present = True
        if hasattr(resolver, "exists"):
            media_present = bool(vp) and resolver.exists(vp) and (not cp or resolver.exists(cp))

        md = render_note(video, resolver=resolver)

        if not media_present:
            return md

        now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        conn.execute(
            """
            INSERT INTO video_notes(video_id, markdown, template_version, updated_at)
            VALUES(?, ?, ?, ?)
            ON CONFLICT(video_id) DO UPDATE SET
              markdown=excluded.markdown,
              template_version=excluded.template_version,
              updated_at=excluded.updated_at
            """,
            (str(video["id"]), md, TEMPLATE_VERSION, now),
        )
        conn.commit()
        return md

    @app.get("/authors")
    def list_authors(
        q: str = "",
        limit: int = Query(200, ge=1, le=2000),
        offset: int = Query(0, ge=0),
        bookmarked_only: bool = False,
        order: str = Query("count", pattern="^(count|bookmarked|name)$"),
    ):
        """List authors with counts for UI filtering.

        Returns a stable mapping so the UI can show:
        - author_unique_id (handle) and author_name (display)
        - author_id (raw platform id, if present)
        - item counts and bookmarked counts
        """

        conn = _conn()

        where = ["(v.author_unique_id IS NOT NULL AND v.author_unique_id != '')"]
        params: list[object] = []

        if bookmarked_only:
            where.append("v.bookmarked=1")

        q = (q or "").strip()
        if q:
            like = f"%{q}%"
            where.append(
                "(v.author_unique_id LIKE ? OR v.author_name LIKE ? OR v.author_id LIKE ?)"
            )
            params.extend([like, like, like])

        where_sql = "WHERE " + " AND ".join(where)

        order_sql = {
            "count": "ORDER BY items_count DESC, author_unique_id ASC",
            "bookmarked": "ORDER BY bookmarked_count DESC, items_count DESC, author_unique_id ASC",
            "name": "ORDER BY author_unique_id ASC",
        }[order]

        rows = conn.execute(
            f"""
            SELECT
              v.author_id,
              v.author_unique_id,
              v.author_name,
              COUNT(*) AS items_count,
              SUM(CASE WHEN v.bookmarked=1 THEN 1 ELSE 0 END) AS bookmarked_count
            FROM videos v
            {where_sql}
            GROUP BY v.author_id, v.author_unique_id, v.author_name
            {order_sql}
            LIMIT ? OFFSET ?
            """,
            (*params, limit, offset),
        ).fetchall()

        total = conn.execute(
            f"""
            SELECT COUNT(*)
            FROM (
              SELECT 1
              FROM videos v
              {where_sql}
              GROUP BY v.author_id, v.author_unique_id, v.author_name
            )
            """,
            tuple(params),
        ).fetchone()[0]

        return {
            "authors": [dict(r) for r in rows],
            "limit": limit,
            "offset": offset,
            "total": int(total),
        }

    @app.get("/items")
    def list_items(
        q: str = "",
        caption_q: str | None = None,
        # SX Library can request large pages (e.g. 1000). Keep a sane upper bound.
        limit: int = Query(50, ge=1, le=2000),
        offset: int = Query(0, ge=0),
        bookmarked_only: bool = False,
        bookmark_from: str | None = None,
        bookmark_to: str | None = None,
        author_unique_id: str | None = None,
        author_id: str | None = None,
        status: str | None = None,
        rating_min: float | None = Query(None, ge=0, le=5),
        rating_max: float | None = Query(None, ge=0, le=5),
        tag: str | None = None,
        has_notes: bool | None = None,
        order: str = Query("recent", pattern="^(recent|bookmarked|author|status|rating)$"),
    ):
        """Paged list for a table/grid UI.

        - `q` filters caption/author/id (LIKE based; fast enough for paging)
        - `caption_q` filters caption only (supports simple advanced syntax)
        - `bookmarked_only` limits to bookmarked items
        - `order=recent` sorts by updated_at desc
        - `order=bookmarked` sorts bookmarked first
        """
        conn = _conn()

        where = []
        params: list[object] = []

        if bookmarked_only:
            where.append("v.bookmarked=1")

        # Optional: bookmark date window.
        # `videos.bookmark_timestamp` is stored as ISO-8601 text (or null).
        # We compare on `date(...)` so callers can pass YYYY-MM-DD.
        # Note: This filter is meaningful when `bookmarked_only=true`.
        if bookmark_from:
            where.append(
                "v.bookmark_timestamp IS NOT NULL AND v.bookmark_timestamp != '' AND date(v.bookmark_timestamp) >= date(?)"
            )
            params.append(str(bookmark_from))
        if bookmark_to:
            where.append(
                "v.bookmark_timestamp IS NOT NULL AND v.bookmark_timestamp != '' AND date(v.bookmark_timestamp) <= date(?)"
            )
            params.append(str(bookmark_to))

        if author_unique_id:
            ids = [a.strip() for a in (author_unique_id or "").split(",") if a.strip()]
            if ids:
                where.append("v.author_unique_id IN (" + ",".join(["?"] * len(ids)) + ")")
                params.extend(ids)

        if author_id:
            ids = [a.strip() for a in (author_id or "").split(",") if a.strip()]
            if ids:
                where.append("v.author_id IN (" + ",".join(["?"] * len(ids)) + ")")
                params.extend(ids)

        if status is not None:
            # Filter by user-owned meta status.
            # Supports:
            # - single value: status=reviewing
            # - multiple values: status=reviewing,reviewed
            # - blank value to mean 'unassigned': status=
            raw = status
            parts = [p.strip() for p in (raw or "").split(",")]
            parts = [p for p in parts if p is not None]
            wants_unassigned = any(p == "" for p in parts)
            vals = [p for p in parts if p != ""]

            clauses: list[str] = []
            if wants_unassigned:
                clauses.append("((m.status IS NULL OR m.status='') AND (m.statuses IS NULL OR m.statuses=''))")
            if vals:
                clauses.append("m.status IN (" + ",".join(["?"] * len(vals)) + ")")
                params.extend(vals)
                like_clauses = []
                for v in vals:
                    like_clauses.append("COALESCE(m.statuses, '') LIKE ?")
                    params.append(f"%|{v}|%")
                clauses.append("(" + " OR ".join(like_clauses) + ")")

            if clauses:
                where.append("(" + " OR ".join(clauses) + ")")

        if rating_min is not None:
            where.append("m.rating IS NOT NULL AND m.rating >= ?")
            params.append(float(rating_min))

        if rating_max is not None:
            where.append("m.rating IS NOT NULL AND m.rating <= ?")
            params.append(float(rating_max))

        if has_notes is not None:
            if has_notes:
                where.append("COALESCE(TRIM(m.notes), '') <> ''")
            else:
                where.append("COALESCE(TRIM(m.notes), '') = ''")

        if tag:
            # Tags are stored as comma-separated values (user-controlled). We match on
            # whole-tag boundaries by wrapping both sides with commas.
            tags = [t.strip().lower() for t in (tag or "").split(",") if t.strip()]
            if tags:
                clauses = []
                for t in tags:
                    clauses.append("(',' || LOWER(COALESCE(m.tags, '')) || ',') LIKE ?")
                    params.append(f"%,{t},%")
                where.append("(" + " OR ".join(clauses) + ")")

        q = (q or "").strip()
        if q:
            like = f"%{q}%"
            where.append(
                "(v.caption LIKE ? OR v.author_unique_id LIKE ? OR v.author_name LIKE ? OR v.id LIKE ?)"
            )
            params.extend([like, like, like, like])

        caption_q = (caption_q or "").strip()
        if caption_q:
            inc, exc = _parse_advanced_terms(caption_q)
            for t in inc:
                where.append("COALESCE(v.caption, '') LIKE ?")
                params.append(f"%{t}%")
            for t in exc:
                where.append("(v.caption IS NULL OR v.caption NOT LIKE ?)")
                params.append(f"%{t}%")

        where_sql = ("WHERE " + " AND ".join(where)) if where else ""
        if order == "recent":
            order_sql = "ORDER BY v.updated_at DESC"
        elif order == "bookmarked":
            order_sql = "ORDER BY v.bookmarked DESC, COALESCE(v.bookmark_timestamp, '') DESC, v.updated_at DESC"
        elif order == "author":
            order_sql = "ORDER BY COALESCE(v.author_unique_id, v.author_name, '') ASC, v.updated_at DESC"
        elif order == "status":
            order_sql = "ORDER BY COALESCE(m.status, '') ASC, v.updated_at DESC"
        elif order == "rating":
            order_sql = "ORDER BY COALESCE(m.rating, -1) DESC, v.updated_at DESC"
        else:
            order_sql = "ORDER BY v.updated_at DESC"

        rows = conn.execute(
            f"""
            SELECT
                            v.id, v.platform, v.author_id, v.author_unique_id, v.author_name, v.caption, v.bookmarked,
              v.video_path, v.cover_path, v.updated_at,
                            m.rating, m.status, m.statuses, m.tags, m.notes,
                            m.product_link, m.author_links, m.platform_targets, m.workflow_log, m.post_url, m.published_time,
                            m.updated_at as meta_updated_at
            FROM videos v
            LEFT JOIN user_meta m ON m.video_id = v.id
            {where_sql}
            {order_sql}
            LIMIT ? OFFSET ?
            """,
            (*params, limit, offset),
        ).fetchall()

        total = conn.execute(
            f"SELECT COUNT(*) FROM videos v LEFT JOIN user_meta m ON m.video_id=v.id {where_sql}",
            tuple(params),
        ).fetchone()[0]

        items = []
        for r in rows:
            d = dict(r)
            _ensure_media_paths(d)
            packed = d.pop("statuses")
            statuses_list = _unpack_statuses(packed)
            if not statuses_list:
                # Back-compat: derive list from primary status if present.
                s = (d.get("status") or "").strip()
                statuses_list = [s] if s else []
            d["meta"] = {
                "rating": d.pop("rating"),
                "status": d.pop("status"),
                "statuses": statuses_list,
                "tags": d.pop("tags"),
                "notes": d.pop("notes"),
                "product_link": d.pop("product_link"),
                "author_links": _unpack_url_list(d.pop("author_links")),
                "platform_targets": d.pop("platform_targets"),
                "workflow_log": d.pop("workflow_log"),
                "post_url": d.pop("post_url"),
                "published_time": d.pop("published_time"),
                "updated_at": d.pop("meta_updated_at"),
            }
            items.append(d)

        return {"items": items, "limit": limit, "offset": offset, "total": int(total)}

    @app.get("/items/{item_id}/meta")
    def get_meta(item_id: str) -> dict:
        conn = _conn()
        row = conn.execute(
            "SELECT video_id, rating, status, statuses, tags, notes, product_link, author_links, platform_targets, workflow_log, post_url, published_time, updated_at FROM user_meta WHERE video_id=?",
            (item_id,),
        ).fetchone()
        if not row:
            return {
                "meta": {
                    "video_id": item_id,
                    "rating": None,
                    "status": None,
                    "statuses": [],
                    "tags": None,
                    "notes": None,
                    "product_link": None,
                    "author_links": [],
                    "platform_targets": None,
                    "workflow_log": None,
                    "post_url": None,
                    "published_time": None,
                    "updated_at": None,
                }
            }

        d = dict(row)
        d["statuses"] = _unpack_statuses(d.get("statuses"))
        d["author_links"] = _unpack_url_list(d.get("author_links"))
        if not d["statuses"] and (d.get("status") or "").strip():
            d["statuses"] = [(d.get("status") or "").strip()]
        return {"meta": d}

    @app.put("/items/{item_id}/meta")
    def put_meta(item_id: str, meta: MetaIn = Body(...)) -> dict:
        conn = _conn()
        exists = conn.execute("SELECT 1 FROM videos WHERE id=?", (item_id,)).fetchone()
        if not exists:
            raise HTTPException(status_code=404, detail="Not found")

        now = datetime.utcnow().isoformat(timespec="seconds") + "Z"

        # Normalize multi-status input:
        # - Accept meta.statuses (preferred)
        # - Accept meta.status as a comma-separated fallback
        statuses_list = _normalize_status_list(meta.statuses)
        if not statuses_list:
            statuses_list = _normalize_status_list(meta.status)

        packed_statuses = _pack_statuses(statuses_list)
        primary_status = _primary_status_from_list(statuses_list) or (meta.status or None)

        provided_fields = set(getattr(meta, "model_fields_set", set()) or set())
        author_links_was_provided = "author_links" in provided_fields
        if author_links_was_provided:
            author_links_list = _normalize_url_list(meta.author_links)
        else:
            existing_links_row = conn.execute(
                "SELECT author_links FROM user_meta WHERE video_id=?",
                (item_id,),
            ).fetchone()
            author_links_list = _unpack_url_list(existing_links_row[0] if existing_links_row else None)
        packed_author_links = _pack_url_list(author_links_list)

        author_row = conn.execute(
            "SELECT author_unique_id, author_name FROM videos WHERE id=?",
            (item_id,),
        ).fetchone()
        author_uid = str((author_row[0] if author_row else "") or "").strip()
        author_name = str((author_row[1] if author_row else "") or "").strip()

        conn.execute(
            """
            INSERT INTO user_meta(
                video_id, rating, status, statuses, tags, notes,
                product_link, author_links, platform_targets, workflow_log, post_url, published_time,
                updated_at
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(video_id) DO UPDATE SET
              rating=excluded.rating,
              status=excluded.status,
              statuses=excluded.statuses,
              tags=excluded.tags,
              notes=excluded.notes,
              product_link=excluded.product_link,
              author_links=excluded.author_links,
              platform_targets=excluded.platform_targets,
              workflow_log=excluded.workflow_log,
              post_url=excluded.post_url,
              published_time=excluded.published_time,
              updated_at=excluded.updated_at
            """,
            (
                item_id,
                meta.rating,
                primary_status,
                packed_statuses,
                meta.tags,
                meta.notes,
                meta.product_link,
                packed_author_links,
                meta.platform_targets,
                meta.workflow_log,
                meta.post_url,
                meta.published_time,
                now,
            ),
        )

        # Author-scoped propagation: keep author_links consistent for all items by the same author.
        # Priority: author_unique_id; fallback: author_name when unique_id is missing.
        if author_links_was_provided and author_uid:
            conn.execute(
                """
                INSERT INTO user_meta(video_id, author_links, updated_at)
                SELECT v.id, ?, ?
                FROM videos v
                WHERE v.author_unique_id = ?
                ON CONFLICT(video_id) DO UPDATE SET
                  author_links=excluded.author_links,
                  updated_at=excluded.updated_at
                """,
                (packed_author_links, now, author_uid),
            )
        elif author_links_was_provided and author_name:
            conn.execute(
                """
                INSERT INTO user_meta(video_id, author_links, updated_at)
                SELECT v.id, ?, ?
                FROM videos v
                WHERE (v.author_unique_id IS NULL OR TRIM(v.author_unique_id) = '')
                  AND COALESCE(TRIM(v.author_name), '') = ?
                ON CONFLICT(video_id) DO UPDATE SET
                  author_links=excluded.author_links,
                  updated_at=excluded.updated_at
                """,
                (packed_author_links, now, author_name),
            )
        conn.commit()

        dumped = meta.model_dump()
        # Ensure response reflects normalized state.
        dumped["statuses"] = statuses_list
        dumped["status"] = primary_status
        dumped["author_links"] = author_links_list
        out = {"video_id": item_id, **dumped, "updated_at": now}
        return {"meta": out}

    def _safe_media_path(relative_path: str) -> Path:
        if not relative_path:
            raise HTTPException(status_code=404, detail="No media path for item")

        if not settings.SX_MEDIA_VAULT:
            raise HTTPException(status_code=500, detail="SX_MEDIA_VAULT/VAULT_default is not configured")

        # Resolve absolute path in a filesystem-friendly style (usually linux for WSL).
        resolver = PathResolver(
            {
                "path_style": settings.SX_MEDIA_STYLE,
                "vault": settings.SX_MEDIA_VAULT,
                "data_dir": settings.SX_MEDIA_DATA_DIR or settings.DATA_DIR,
            }
        )
        abs_str = resolver.resolve_absolute(relative_path)
        abs_path = Path(abs_str)

        # Basic traversal safety: ensure resolved path stays inside vault/data_dir root.
        base_root = Path(resolver.resolve_absolute("__sx_base__")).parent
        try:
            abs_resolved = abs_path.resolve()
            base_resolved = base_root.resolve()
            abs_resolved.relative_to(base_resolved)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid media path")

        if not abs_resolved.exists():
            raise HTTPException(status_code=404, detail="Media file not found")

        return abs_resolved

    @app.get("/media/cover/{item_id}")
    def media_cover(item_id: str):
        conn = _conn()
        row = conn.execute(
            "SELECT cover_path, bookmarked, author_id FROM videos WHERE id=?",
            (item_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Not found")
        cover_path = row[0] or ""
        if not cover_path:
            _, derived_cp = _canonical_media_paths(item_id=item_id, bookmarked=row[1], author_id=row[2])
            cover_path = derived_cp
        path = _safe_media_path(cover_path)
        media_type, _ = mimetypes.guess_type(str(path))
        return FileResponse(path, media_type=media_type or "image/jpeg")

    @app.get("/media/video/{item_id}")
    def media_video(item_id: str):
        conn = _conn()
        row = conn.execute(
            "SELECT video_path, bookmarked, author_id FROM videos WHERE id=?",
            (item_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Not found")
        video_path = row[0] or ""
        if not video_path:
            derived_vp, _ = _canonical_media_paths(item_id=item_id, bookmarked=row[1], author_id=row[2])
            video_path = derived_vp
        path = _safe_media_path(video_path)
        media_type, _ = mimetypes.guess_type(str(path))
        # Starlette's FileResponse supports Range requests (important for video preview).
        return FileResponse(path, media_type=media_type or "video/mp4")

    @app.get("/items/{item_id}/links")
    def get_item_links(item_id: str) -> dict:
        """Return protocol links for opening/revealing local media.

        This is intended for the Obsidian plugin's Open/Reveal buttons.
        It avoids depending on cached note frontmatter (which may be missing
        in older notes or user-edited YAML).
        """

        conn = _conn()
        row = conn.execute(
            "SELECT id, video_path, cover_path, bookmarked, author_id FROM videos WHERE id=?",
            (item_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Not found")

        d = dict(row)
        _ensure_media_paths(d)

        resolver = _note_resolver()

        vp = d.get("video_path") or ""
        cp = d.get("cover_path") or ""
        v_abs = resolver.resolve_absolute(vp) if vp else ""
        c_abs = resolver.resolve_absolute(cp) if cp else ""

        return {
            "id": item_id,
            "video_path": vp,
            "cover_path": cp,
            "video_abs": v_abs,
            "cover_abs": c_abs,
            "sxopen_video": resolver.format_protocol("sxopen", v_abs) if v_abs else "",
            "sxreveal_video": resolver.format_protocol("sxreveal", v_abs) if v_abs else "",
            "sxopen_cover": resolver.format_protocol("sxopen", c_abs) if c_abs else "",
            "sxreveal_cover": resolver.format_protocol("sxreveal", c_abs) if c_abs else "",
        }

    @app.get("/items/{item_id}")
    def get_item(item_id: str):
        conn = _conn()
        row = conn.execute("SELECT * FROM videos WHERE id=?", (item_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Not found")
        return {"item": dict(row)}

    @app.get("/items/{item_id}/raw")
    def get_item_raw(item_id: str):
        """Return full-fidelity raw CSV rows stored in the DB.

        This is intentionally separate from /items/{id} so normal UI flows stay light.
        """

        conn = _conn()
        item = conn.execute(
            "SELECT id, author_id, bookmarked FROM videos WHERE id=?",
            (item_id,),
        ).fetchone()
        if not item:
            raise HTTPException(status_code=404, detail="Not found")

        consolidated = conn.execute(
            "SELECT row_json, csv_row_hash, imported_at FROM csv_consolidated_raw WHERE video_id=?",
            (item_id,),
        ).fetchone()

        bookmark = conn.execute(
            "SELECT row_json, imported_at FROM csv_bookmarks_raw WHERE video_id=?",
            (item_id,),
        ).fetchone()

        author_id = (item["author_id"] or "").strip()
        author = None
        if author_id:
            author = conn.execute(
                "SELECT row_json, imported_at FROM csv_authors_raw WHERE author_id=?",
                (author_id,),
            ).fetchone()

        return {
            "id": item_id,
            "raw": {
                "consolidated": dict(consolidated) if consolidated else None,
                "bookmark": dict(bookmark) if bookmark else None,
                "author": dict(author) if author else None,
            },
        }

    @app.get("/items/{item_id}/note")
    def get_item_note(item_id: str, force: bool = False):
        conn = _conn()
        cached = _get_cached_note(conn, item_id)
        if cached:
            md, tv = cached

            # If the user pushed their own note content, never overwrite it
            # unless we add an explicit override flag in the future.
            if tv == "user":
                return {
                    "id": item_id,
                    "markdown": md,
                    "cached": True,
                    "template_version": tv,
                    "stale": False,
                }

            if not force:
                return {
                    "id": item_id,
                    "markdown": md,
                    "cached": True,
                    "template_version": tv,
                    "stale": bool(tv and tv != TEMPLATE_VERSION),
                }

        video = _fetch_video_with_meta(conn, item_id)
        if not video:
            raise HTTPException(status_code=404, detail="Not found")

        _ensure_media_paths(video)

        md = _render_and_cache_note(conn, video)
        return {"id": item_id, "markdown": md, "cached": False, "template_version": TEMPLATE_VERSION, "stale": False}

    @app.put("/items/{item_id}/note-md")
    def put_item_note_md(item_id: str, payload: NoteIn = Body(...)) -> dict:
        """Upsert markdown note content into `video_notes`.

        Used when the user edits synced notes in Obsidian and wants to persist those edits.
        """

        conn = _conn()
        exists = conn.execute("SELECT 1 FROM videos WHERE id=?", (item_id,)).fetchone()
        if not exists:
            raise HTTPException(status_code=404, detail="Not found")

        md = (payload.markdown or "").strip("\ufeff")
        if not md:
            raise HTTPException(status_code=400, detail="Empty markdown")

        tv = payload.template_version or "user"
        now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        conn.execute(
            """
            INSERT INTO video_notes(video_id, markdown, template_version, updated_at)
            VALUES(?, ?, ?, ?)
            ON CONFLICT(video_id) DO UPDATE SET
              markdown=excluded.markdown,
              template_version=excluded.template_version,
              updated_at=excluded.updated_at
            """,
            (item_id, md, tv, now),
        )
        conn.commit()
        return {"ok": True, "id": item_id, "template_version": tv, "updated_at": now}

    @app.get("/notes")
    def bulk_notes(
        q: str = "",
        caption_q: str | None = None,
        limit: int = Query(200, ge=1, le=500),
        offset: int = Query(0, ge=0),
        bookmarked_only: bool = False,
        bookmark_from: str | None = None,
        bookmark_to: str | None = None,
        author_unique_id: str | None = None,
        author_id: str | None = None,
        status: str | None = None,
        rating_min: float | None = Query(None, ge=0, le=5),
        rating_max: float | None = Query(None, ge=0, le=5),
        tag: str | None = None,
        has_notes: bool | None = None,
        force: bool = False,
        order: str = Query("recent", pattern="^(recent|bookmarked|author|status|rating)$"),
    ):
        """Return rendered markdown notes for syncing into the vault.

        Notes are persisted in `video_notes` so subsequent syncs can be fast.
        """
        conn = _conn()

        where = []
        params: list[object] = []

        if bookmarked_only:
            where.append("v.bookmarked=1")

        if bookmark_from:
            where.append(
                "v.bookmark_timestamp IS NOT NULL AND v.bookmark_timestamp != '' AND date(v.bookmark_timestamp) >= date(?)"
            )
            params.append(str(bookmark_from))
        if bookmark_to:
            where.append(
                "v.bookmark_timestamp IS NOT NULL AND v.bookmark_timestamp != '' AND date(v.bookmark_timestamp) <= date(?)"
            )
            params.append(str(bookmark_to))

        if author_unique_id:
            ids = [a.strip() for a in (author_unique_id or "").split(",") if a.strip()]
            if ids:
                where.append("v.author_unique_id IN (" + ",".join(["?"] * len(ids)) + ")")
                params.extend(ids)

        if author_id:
            ids = [a.strip() for a in (author_id or "").split(",") if a.strip()]
            if ids:
                where.append("v.author_id IN (" + ",".join(["?"] * len(ids)) + ")")
                params.extend(ids)

        if status is not None:
            raw = status
            parts = [p.strip() for p in (raw or "").split(",")]
            parts = [p for p in parts if p is not None]
            wants_unassigned = any(p == "" for p in parts)
            vals = [p for p in parts if p != ""]

            clauses: list[str] = []
            if wants_unassigned:
                clauses.append("((m.status IS NULL OR m.status='') AND (m.statuses IS NULL OR m.statuses=''))")
            if vals:
                clauses.append("m.status IN (" + ",".join(["?"] * len(vals)) + ")")
                params.extend(vals)

                like_clauses = []
                for v in vals:
                    like_clauses.append("COALESCE(m.statuses, '') LIKE ?")
                    params.append(f"%|{v}|%")
                clauses.append("(" + " OR ".join(like_clauses) + ")")

            if clauses:
                where.append("(" + " OR ".join(clauses) + ")")

        if rating_min is not None:
            where.append("m.rating IS NOT NULL AND m.rating >= ?")
            params.append(float(rating_min))

        if rating_max is not None:
            where.append("m.rating IS NOT NULL AND m.rating <= ?")
            params.append(float(rating_max))

        if has_notes is not None:
            if has_notes:
                where.append("COALESCE(TRIM(m.notes), '') <> ''")
            else:
                where.append("COALESCE(TRIM(m.notes), '') = ''")

        if tag:
            tags = [t.strip().lower() for t in (tag or "").split(",") if t.strip()]
            if tags:
                clauses = []
                for t in tags:
                    clauses.append("(',' || LOWER(COALESCE(m.tags, '')) || ',') LIKE ?")
                    params.append(f"%,{t},%")
                where.append("(" + " OR ".join(clauses) + ")")

        q = (q or "").strip()
        if q:
            like = f"%{q}%"
            where.append(
                "(v.caption LIKE ? OR v.author_unique_id LIKE ? OR v.author_name LIKE ? OR v.id LIKE ?)"
            )
            params.extend([like, like, like, like])

        caption_q = (caption_q or "").strip()
        if caption_q:
            inc, exc = _parse_advanced_terms(caption_q)
            for t in inc:
                where.append("COALESCE(v.caption, '') LIKE ?")
                params.append(f"%{t}%")
            for t in exc:
                where.append("(v.caption IS NULL OR v.caption NOT LIKE ?)")
                params.append(f"%{t}%")

        where_sql = ("WHERE " + " AND ".join(where)) if where else ""
        if order == "recent":
            order_sql = "ORDER BY v.updated_at DESC"
        elif order == "bookmarked":
            order_sql = "ORDER BY v.bookmarked DESC, COALESCE(v.bookmark_timestamp, '') DESC, v.updated_at DESC"
        elif order == "author":
            order_sql = "ORDER BY COALESCE(v.author_unique_id, v.author_name, '') ASC, v.updated_at DESC"
        elif order == "status":
            order_sql = "ORDER BY COALESCE(m.status, '') ASC, v.updated_at DESC"
        elif order == "rating":
            order_sql = "ORDER BY COALESCE(m.rating, -1) DESC, v.updated_at DESC"
        else:
            order_sql = "ORDER BY v.updated_at DESC"

        rows = conn.execute(
            f"""
            SELECT
              v.*, 
                                                        m.rating, m.status, m.statuses, m.tags, m.notes,
                                                        m.product_link, m.author_links, m.platform_targets, m.workflow_log, m.post_url, m.published_time
            FROM videos v
            LEFT JOIN user_meta m ON m.video_id = v.id
            {where_sql}
            {order_sql}
            LIMIT ? OFFSET ?
            """,
            (*params, limit, offset),
        ).fetchall()

        total = conn.execute(
            f"SELECT COUNT(*) FROM videos v LEFT JOIN user_meta m ON m.video_id=v.id {where_sql}",
            tuple(params),
        ).fetchone()[0]

        out = []
        for r in rows:
            v = dict(r)
            _ensure_media_paths(v)
            vid = str(v["id"])
            md = None
            cached = _get_cached_note(conn, vid)
            if cached:
                cached_md, cached_tv = cached
                if cached_tv == "user":
                    md = cached_md
                elif not force:
                    md = cached_md
            if md is None:
                md = _render_and_cache_note(conn, v)

            out.append(
                {
                    "id": vid,
                    "bookmarked": bool(v.get("bookmarked")),
                    "author_unique_id": v.get("author_unique_id"),
                    "author_name": v.get("author_name"),
                    "markdown": md,
                }
            )

        return {"notes": out, "limit": limit, "offset": offset, "total": int(total)}

    return app
