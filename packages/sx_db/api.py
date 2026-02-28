from __future__ import annotations

import mimetypes
import re
import json
import uuid
import logging
import os
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from sx.paths import PathResolver

from .db import connect, ensure_source, get_default_source_id, init_db, list_sources, set_default_source
from .markdown import TEMPLATE_VERSION, render_note
from .postgres_mirror import maybe_sync_postgres_mirror
from .repositories import PostgresRepository, get_repository
from .scheduler import Scheduler
from .search import search as search_fn
from .settings import Settings


_CTX_SOURCE_ID: ContextVar[str] = ContextVar("sx_source_id", default="default")
_CTX_REQUEST_ID: ContextVar[str] = ContextVar("sx_request_id", default="")
_AUDIT_LOG = logging.getLogger("sx_db.audit")
_MEDIA_LOG = logging.getLogger("sx_db.media")


def _extract_trailing_profile_index(value: object) -> int | None:
    s = str(value or "").strip().lower()
    if not s:
        return None
    m = re.search(r"(?:^|[_-])(?:p)?(\d{1,2})$", s)
    if not m:
        return None
    n = int(m.group(1))
    return n if n >= 1 else None


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


class SourceIn(BaseModel):
    id: str
    label: str | None = None
    kind: str | None = None
    description: str | None = None
    enabled: bool = True
    make_default: bool = False


class SourcePatchIn(BaseModel):
    label: str | None = None
    kind: str | None = None
    description: str | None = None
    enabled: bool | None = None


class BootstrapSchemaIn(BaseModel):
    source_id: str


class ProfileConfigIn(BaseModel):
    """Payload for updating a source profile's .env configuration."""
    label: str | None = None
    src_path: str | None = None
    source_id: str | None = None
    assets_path: str | None = None
    pathlinker_group: str | None = None
    group_name: str | None = None
    vault_name: str | None = None
    vault_path: str | None = None
    db_local: str | None = None
    db_session: str | None = None
    db_transaction: str | None = None


def create_app(settings: Settings) -> FastAPI:
    app = FastAPI(title="sx_obsidian SQLite API", version="0.1.0")
    repository = get_repository(settings)
    scheduler = Scheduler(settings)
    backend_mode = str(getattr(settings, "SX_DB_BACKEND_MODE", "SQLITE") or "SQLITE").strip().upper()
    is_pg_primary = backend_mode == "POSTGRES_PRIMARY"

    def _sanitize_source_id(v: object) -> str:
        raw = str(v or "").strip()
        if not raw:
            return str(settings.SX_DEFAULT_SOURCE_ID or "default")
        cleaned = re.sub(r"[^a-zA-Z0-9._-]", "", raw)
        return cleaned or str(settings.SX_DEFAULT_SOURCE_ID or "default")

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

    def _update_env_file(path: Path, updates: dict[str, str | None]) -> None:
        """Atomically update key-value pairs in a .env file.

        - Existing keys are updated in-place (preserving line position).
        - Keys set to ``None`` are removed.
        - New keys are appended at the end.
        - Comments, blank lines, and ordering are preserved.
        """
        remaining = dict(updates)
        lines: list[str] = []

        if path.exists():
            for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
                stripped = raw_line.strip()
                if stripped and not stripped.startswith("#") and "=" in stripped:
                    key = stripped.split("=", 1)[0].strip()
                    if key in remaining:
                        new_val = remaining.pop(key)
                        if new_val is not None:
                            lines.append(f"{key}={new_val}")
                        # else: key is being removed — skip line
                        continue
                lines.append(raw_line)

        # Append any brand-new keys that were not found in the file.
        for key, val in remaining.items():
            if val is not None:
                lines.append(f"{key}={val}")

        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _build_db_url_from_alias(env_map: dict[str, str], alias: str) -> tuple[str, str] | tuple[None, None]:
        alias = str(alias or "").strip()
        if not alias:
            return None, None
        user = env_map.get(f"{alias}_DB_USER", "")
        pwd = env_map.get(f"{alias}_DB_PASSWORD", "")
        host = env_map.get(f"{alias}_DB_HOST", "")
        port = env_map.get(f"{alias}_DB_PORT", "")
        dbn = env_map.get(f"{alias}_DB_NAME", "")
        schema = env_map.get(f"{alias}_DB_SCHEMA", "")
        if not (user and host and port and dbn):
            return None, None

        full = f"postgresql://{quote(user)}:{quote(pwd)}@{host}:{port}/{quote(dbn)}"
        if schema:
            full += f"?options=-c%20search_path%3D{quote(schema)}"

        redacted = f"postgresql://***:***@{host}:{port}/{dbn}"
        if schema:
            redacted += f"?options=-c%20search_path%3D{schema}"
        return full, redacted

    def _source_id_from_profile_env(env_map: dict[str, str], idx: int) -> str:
        """Resolve a stable source_id from profile env keys.

        Priority:
        1) SRC_PROFILE_<N>_ID (explicit source id)
        2) DATABASE_PROFILE_<N> when it is a single non-alias token
        3) assets_<N> fallback
        """
        explicit_sid = str(env_map.get(f"SRC_PROFILE_{idx}_ID") or "").strip()
        if explicit_sid:
            return _sanitize_source_id(explicit_sid)

        legacy = str(env_map.get(f"DATABASE_PROFILE_{idx}") or "").strip()
        if legacy and "," not in legacy:
            # Ignore DB alias-like values (LOCAL_2, SUPABASE_SESSION_3, ...).
            if not re.match(r"^(LOCAL|SUPABASE_SESSION|SUPABASE_TRANS|SUPABASE_TRANSACTION|SXO_LOCAL|SXO_SESSION|SXO_TRANS)_\d+$", legacy):
                return _sanitize_source_id(legacy)

        return _sanitize_source_id(f"assets_{idx}")

    if settings.SX_API_CORS_ALLOW_ALL:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=False,
            allow_methods=["*"] ,
            allow_headers=["*"],
        )

    default_source_id = _sanitize_source_id(settings.SX_DEFAULT_SOURCE_ID)

    # Bootstrap source registry for existing DBs.
    try:
        if is_pg_primary and isinstance(repository, PostgresRepository):
            repository.init_schema(default_source_id)
            srcs = repository.list_sources()
            if not srcs.get("default_source_id"):
                with repository._connect() as pg_conn:
                    now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
                    with pg_conn.cursor() as cur:
                        cur.execute("UPDATE public.sources SET is_default=0")
                        cur.execute(
                            """
                            INSERT INTO public.sources(id, label, enabled, is_default, created_at, updated_at)
                            VALUES(%s, %s, 1, 1, %s, %s)
                            ON CONFLICT(id) DO UPDATE SET is_default=1, updated_at=EXCLUDED.updated_at
                            """,
                            (default_source_id, default_source_id, now, now),
                        )
                    pg_conn.commit()
        else:
            conn0 = connect(settings.SX_DB_PATH)
            init_db(conn0, enable_fts=settings.SX_DB_ENABLE_FTS)
            ensure_source(conn0, default_source_id, label=default_source_id)
            if not conn0.execute("SELECT 1 FROM sources WHERE is_default=1 LIMIT 1").fetchone():
                set_default_source(conn0, default_source_id)
            conn0.commit()
    except Exception:
        # Do not block app startup on source registry bootstrap.
        pass

    @app.middleware("http")
    async def source_context_middleware(request: Request, call_next):
        request_id = uuid.uuid4().hex
        requested = request.headers.get("X-SX-Source-ID") or request.query_params.get("source_id")
        hdr_profile_raw = request.headers.get("X-SX-Profile-Index")
        hdr_profile_idx: int | None = None
        if hdr_profile_raw is not None:
            try:
                n = int(str(hdr_profile_raw).strip())
                if n >= 1:
                    hdr_profile_idx = n
            except Exception:
                return JSONResponse(
                    status_code=400,
                    content={
                        "ok": False,
                        "detail": "Invalid X-SX-Profile-Index header",
                        "request_id": request_id,
                    },
                )

        # Profile config endpoints are meta/admin — they don't need source scoping.
        _exempt_prefixes = ("/pipeline/profiles", "/config/profiles")
        is_exempt = any(request.url.path.startswith(p) for p in _exempt_prefixes)

        if settings.SX_API_REQUIRE_EXPLICIT_SOURCE and not requested and not is_exempt:
            return JSONResponse(
                status_code=400,
                content={
                    "ok": False,
                    "detail": "Missing explicit source_id (query or X-SX-Source-ID)",
                    "request_id": request_id,
                },
            )

        if requested:
            source_id = _sanitize_source_id(requested)
        else:
            resolved_default = default_source_id
            if is_pg_primary and isinstance(repository, PostgresRepository):
                try:
                    d = repository.list_sources().get("default_source_id")
                    resolved_default = _sanitize_source_id(d or default_source_id)
                except Exception:
                    resolved_default = default_source_id
            else:
                try:
                    conn = connect(settings.SX_DB_PATH)
                    init_db(conn, enable_fts=settings.SX_DB_ENABLE_FTS)
                    resolved_default = _sanitize_source_id(get_default_source_id(conn, fallback=default_source_id))
                except Exception:
                    resolved_default = default_source_id
            source_id = resolved_default

        if settings.SX_API_ENFORCE_PROFILE_SOURCE_MATCH:
            sid_idx = _extract_trailing_profile_index(source_id)
            if hdr_profile_idx is not None and sid_idx is not None and hdr_profile_idx != sid_idx:
                return JSONResponse(
                    status_code=400,
                    content={
                        "ok": False,
                        "detail": (
                            f"Profile/source mismatch: X-SX-Profile-Index={hdr_profile_idx} "
                            f"but source_id={source_id} implies profile #{sid_idx}"
                        ),
                        "request_id": request_id,
                    },
                )

        if is_pg_primary and isinstance(repository, PostgresRepository):
            try:
                schema = repository.resolve_schema(source_id, create_if_missing=False)
            except Exception as e:
                return JSONResponse(
                    status_code=400,
                    content={
                        "ok": False,
                        "detail": f"Source schema mapping missing/invalid for source_id={source_id}: {e}",
                        "request_id": request_id,
                    },
                )

            backend_ctx = {
                "backend": "postgres_primary",
                "active": True,
                "source_id": source_id,
                "schema": schema,
                "search_path": f"{schema},public",
            }
        else:
            try:
                conn = connect(settings.SX_DB_PATH)
                init_db(conn, enable_fts=settings.SX_DB_ENABLE_FTS)
                ensure_source(conn, source_id, label=source_id)
                conn.commit()
            except Exception:
                pass

            backend_ctx = {
                "backend": "sqlite",
                "active": False,
                "reason": "default sqlite backend",
                "source_id": source_id,
            }
            try:
                backend_ctx = maybe_sync_postgres_mirror(settings, source_id)
                if str(getattr(settings, "SX_DB_BACKEND_MODE", "")).strip().upper() == "POSTGRES_MIRROR":
                    backend_ctx["deprecation"] = "POSTGRES_MIRROR is transitional; migrate to POSTGRES_PRIMARY"
            except Exception as e:
                backend_ctx = {
                    "backend": "sqlite",
                    "active": False,
                    "reason": f"postgres mirror sync failed: {e}",
                    "source_id": source_id,
                }

        tok_sid = _CTX_SOURCE_ID.set(source_id)
        tok_rid = _CTX_REQUEST_ID.set(request_id)
        request.state.sx_source_id = source_id
        request.state.sx_request_id = request_id
        request.state.sx_backend_ctx = backend_ctx
        try:
            response = await call_next(request)
        finally:
            _CTX_SOURCE_ID.reset(tok_sid)
            _CTX_REQUEST_ID.reset(tok_rid)
        response.headers["X-SX-Source-ID"] = source_id
        response.headers["X-SX-Backend"] = str(backend_ctx.get("backend") or "sqlite")
        response.headers["X-SX-Request-ID"] = request_id
        _AUDIT_LOG.info(
            "audit request_id=%s source_id=%s schema=%s endpoint=%s timestamp=%s",
            request_id,
            source_id,
            str(backend_ctx.get("schema") or ""),
            request.url.path,
            datetime.utcnow().isoformat(timespec="seconds") + "Z",
        )
        return response

    @app.get("/sources")
    def get_sources() -> dict:
        if is_pg_primary:
            return repository.list_sources()
        conn = connect(settings.SX_DB_PATH)
        init_db(conn, enable_fts=settings.SX_DB_ENABLE_FTS)
        rows = list_sources(conn)
        active_default = get_default_source_id(conn, fallback=default_source_id)
        return {"sources": rows, "default_source_id": active_default}

    @app.get("/admin/audit/source-overlap")
    def audit_source_overlap(
        source_a: str = Query("assets_1"),
        source_b: str = Query("assets_2"),
    ) -> dict:
        a = _sanitize_source_id(source_a)
        b = _sanitize_source_id(source_b)
        if a == b:
            raise HTTPException(status_code=400, detail="source_a and source_b must differ")

        if not (is_pg_primary and isinstance(repository, PostgresRepository)):
            return {"ok": True, "backend": "sqlite", "message": "Overlap audit is only available in POSTGRES_PRIMARY"}

        try:
            sa = repository.resolve_schema(a, create_if_missing=False)
            sb = repository.resolve_schema(b, create_if_missing=False)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Schema resolution failed: {e}")

        with repository._connect() as pg_conn:
            with pg_conn.cursor() as cur:
                cur.execute(f'SELECT COUNT(*) AS n FROM "{sa}".videos')
                count_a = int((cur.fetchone() or {}).get("n") or 0)
                cur.execute(f'SELECT COUNT(*) AS n FROM "{sb}".videos')
                count_b = int((cur.fetchone() or {}).get("n") or 0)
                cur.execute(
                    f'''
                    SELECT COUNT(*) AS n
                    FROM "{sa}".videos va
                    JOIN "{sb}".videos vb ON va.id = vb.id
                    '''
                )
                overlap = int((cur.fetchone() or {}).get("n") or 0)
                cur.execute(
                    f'''
                    SELECT COUNT(*) AS n
                    FROM (
                      SELECT id FROM "{sa}".videos
                      EXCEPT
                      SELECT id FROM "{sb}".videos
                    ) t
                    '''
                )
                only_a = int((cur.fetchone() or {}).get("n") or 0)
                cur.execute(
                    f'''
                    SELECT COUNT(*) AS n
                    FROM (
                      SELECT id FROM "{sb}".videos
                      EXCEPT
                      SELECT id FROM "{sa}".videos
                    ) t
                    '''
                )
                only_b = int((cur.fetchone() or {}).get("n") or 0)

        return {
            "ok": True,
            "backend": "postgres_primary",
            "source_a": a,
            "schema_a": sa,
            "count_a": count_a,
            "source_b": b,
            "schema_b": sb,
            "count_b": count_b,
            "overlap_ids": overlap,
            "only_a_ids": only_a,
            "only_b_ids": only_b,
        }

    @app.get("/pipeline/profiles")
    def get_pipeline_profiles() -> dict:
        env_path = Path(settings.SX_SCHEDULERX_ENV) if settings.SX_SCHEDULERX_ENV else Path("../SchedulerX/backend/pipeline/.env")
        env_map = _parse_env_file(env_path)

        indices: set[int] = set()
        for k in env_map.keys():
            m = re.match(r"^(SRC_PATH|SRC_PROFILE)_(\d+)$", k)
            if m:
                indices.add(int(m.group(2)))
        if not indices:
            indices.add(int(settings.SX_PROFILE_INDEX or 1))

        profiles: list[dict] = []
        for idx in sorted(indices):
            path = env_map.get(f"SRC_PATH_{idx}") or env_map.get(f"SRC_PROFILE_{idx}") or ""
            label = env_map.get(f"SRC_PATH_{idx}_LABEL") or env_map.get(f"SRC_PROFILE_{idx}_LABEL") or f"profile_{idx}"
            source_id = _source_id_from_profile_env(env_map, idx)

            local_alias = env_map.get(f"SRC_PATH_{idx}_DB_LOCAL") or env_map.get(f"SRC_PROFILE_{idx}_DB_LOCAL") or ""
            session_alias = env_map.get(f"SRC_PATH_{idx}_DB_SESSION") or env_map.get(f"SRC_PROFILE_{idx}_DB_SESSION") or ""
            trans_alias = env_map.get(f"SRC_PATH_{idx}_DB_TRANSACTION") or env_map.get(f"SRC_PROFILE_{idx}_DB_TRANSACTION") or ""
            sql_db_path = (
                env_map.get(f"SQL_DB_PATH_{idx}")
                or env_map.get(f"SX_SQL_DB_PATH_{idx}")
                or env_map.get(f"SRC_PATH_{idx}_DB_SQL")
                or env_map.get(f"SRC_PROFILE_{idx}_DB_SQL")
                or ""
            )

            local_url, local_redacted = _build_db_url_from_alias(env_map, local_alias)
            session_url, session_redacted = _build_db_url_from_alias(env_map, session_alias)
            trans_url, trans_redacted = _build_db_url_from_alias(env_map, trans_alias)

            profiles.append(
                {
                    "index": idx,
                    "label": label,
                    "src_path": path,
                    "source_id": source_id,
                    "pathlinker_group": env_map.get(f"PATHLINKER_GROUP_{idx}") or "",
                    "group_name": env_map.get(f"GROUP_NAME_{idx}") or "",
                    "vault_name": env_map.get(f"VAULT_NAME_{idx}") or "",
                    "vault_path": env_map.get(f"VAULT_PATH_{idx}") or "",
                    "assets_path": env_map.get(f"ASSETS_PATH_{idx}") or "",
                    "db_profiles": {
                        "local": {"alias": local_alias or None, "url_redacted": local_redacted, "configured": bool(local_url)},
                        "session": {"alias": session_alias or None, "url_redacted": session_redacted, "configured": bool(session_url)},
                        "transaction": {"alias": trans_alias or None, "url_redacted": trans_redacted, "configured": bool(trans_url)},
                        "sql": {"db_path": sql_db_path or None, "configured": bool(sql_db_path)},
                    },
                    "available_modes": ["LOCAL", "SESSION", "TRANSACTION", "SQL"],
                }
            )

        return {
            "ok": True,
            "env_path": str(env_path),
            "profiles": profiles,
        }

    @app.put("/config/profiles/{idx}")
    def update_profile_config(idx: int, payload: ProfileConfigIn = Body(...)) -> dict:
        """Write profile configuration fields back to the .env file."""
        env_path = Path(settings.SX_SCHEDULERX_ENV) if settings.SX_SCHEDULERX_ENV else Path(".env")
        if idx < 1 or idx > 99:
            raise HTTPException(status_code=400, detail="Profile index must be 1–99")

        updates: dict[str, str | None] = {}

        field_map: dict[str, str] = {
            "src_path": f"SRC_PATH_{idx}",
            "label": f"SRC_PATH_{idx}_LABEL",
            "source_id": f"SRC_PROFILE_{idx}_ID",
            "assets_path": f"ASSETS_PATH_{idx}",
            "pathlinker_group": f"PATHLINKER_GROUP_{idx}",
            "group_name": f"GROUP_NAME_{idx}",
            "vault_name": f"VAULT_NAME_{idx}",
            "vault_path": f"VAULT_PATH_{idx}",
            "db_local": f"SRC_PATH_{idx}_DB_LOCAL",
            "db_session": f"SRC_PATH_{idx}_DB_SESSION",
            "db_transaction": f"SRC_PATH_{idx}_DB_TRANSACTION",
        }

        payload_dict = payload.dict(exclude_unset=True)
        for field_name, env_key in field_map.items():
            if field_name in payload_dict:
                val = payload_dict[field_name]
                updates[env_key] = str(val).strip() if val is not None else None

        if not updates:
            raise HTTPException(status_code=400, detail="No fields to update")

        try:
            _update_env_file(env_path, updates)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Failed to write .env: {exc}")

        # Re-read and return updated profile snapshot.
        env_map = _parse_env_file(env_path)
        return {
            "ok": True,
            "index": idx,
            "updated_keys": list(updates.keys()),
            "profile": {
                "index": idx,
                "label": env_map.get(f"SRC_PATH_{idx}_LABEL") or env_map.get(f"SRC_PROFILE_{idx}_LABEL") or f"profile_{idx}",
                "src_path": env_map.get(f"SRC_PATH_{idx}") or "",
                "source_id": _source_id_from_profile_env(env_map, idx),
                "pathlinker_group": env_map.get(f"PATHLINKER_GROUP_{idx}") or "",
                "group_name": env_map.get(f"GROUP_NAME_{idx}") or "",
                "vault_name": env_map.get(f"VAULT_NAME_{idx}") or "",
                "vault_path": env_map.get(f"VAULT_PATH_{idx}") or "",
                "assets_path": env_map.get(f"ASSETS_PATH_{idx}") or "",
            },
        }

    @app.post("/sources")
    def create_source(payload: SourceIn = Body(...)) -> dict:
        source_id = _sanitize_source_id(payload.id)
        if not source_id:
            raise HTTPException(status_code=400, detail="Invalid source id")

        if is_pg_primary and isinstance(repository, PostgresRepository):
            schema_info = repository.init_schema(source_id)
            with repository._connect() as pg_conn:
                now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
                with pg_conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO public.sources(id, label, kind, description, enabled, is_default, created_at, updated_at)
                        VALUES(%s, %s, %s, %s, %s, 0, %s, %s)
                        ON CONFLICT(id) DO UPDATE SET
                          label=COALESCE(EXCLUDED.label, public.sources.label),
                          kind=COALESCE(EXCLUDED.kind, public.sources.kind),
                          description=COALESCE(EXCLUDED.description, public.sources.description),
                          enabled=EXCLUDED.enabled,
                          updated_at=EXCLUDED.updated_at
                        """,
                        (
                            source_id,
                            payload.label or source_id,
                            payload.kind,
                            payload.description,
                            1 if bool(payload.enabled) else 0,
                            now,
                            now,
                        ),
                    )
                    if payload.make_default:
                        cur.execute("UPDATE public.sources SET is_default=0")
                        cur.execute("UPDATE public.sources SET is_default=1, updated_at=%s WHERE id=%s", (now, source_id))
                pg_conn.commit()
            return {"ok": True, "source_id": source_id, "schema": schema_info.get("schema")}

        conn = connect(settings.SX_DB_PATH)
        init_db(conn, enable_fts=settings.SX_DB_ENABLE_FTS)
        ensure_source(
            conn,
            source_id,
            label=(payload.label or source_id),
            kind=payload.kind,
            description=payload.description,
            enabled=bool(payload.enabled),
        )
        if payload.make_default:
            set_default_source(conn, source_id)
        conn.commit()
        return {"ok": True, "source_id": source_id}

    @app.patch("/sources/{source_id}")
    def patch_source(source_id: str, payload: SourcePatchIn = Body(...)) -> dict:
        sid = _sanitize_source_id(source_id)
        if not sid:
            raise HTTPException(status_code=400, detail="Invalid source id")

        if is_pg_primary and isinstance(repository, PostgresRepository):
            now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
            with repository._connect() as pg_conn:
                with pg_conn.cursor() as cur:
                    cur.execute("SELECT id FROM public.sources WHERE id=%s", (sid,))
                    row = cur.fetchone()
                    if not row:
                        raise HTTPException(status_code=404, detail="Source not found")
                    cur.execute(
                        """
                        UPDATE public.sources
                        SET
                          label=COALESCE(%s, label),
                          kind=COALESCE(%s, kind),
                          description=COALESCE(%s, description),
                          enabled=COALESCE(%s, enabled),
                          updated_at=%s
                        WHERE id=%s
                        """,
                        (
                            payload.label,
                            payload.kind,
                            payload.description,
                            None if payload.enabled is None else (1 if payload.enabled else 0),
                            now,
                            sid,
                        ),
                    )
                pg_conn.commit()
            return {"ok": True, "source_id": sid}

        conn = connect(settings.SX_DB_PATH)
        init_db(conn, enable_fts=settings.SX_DB_ENABLE_FTS)
        row = conn.execute("SELECT id FROM sources WHERE id=?", (sid,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Source not found")

        now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        conn.execute(
            """
            UPDATE sources
            SET
              label=COALESCE(?, label),
              kind=COALESCE(?, kind),
              description=COALESCE(?, description),
              enabled=COALESCE(?, enabled),
              updated_at=?
            WHERE id=?
            """,
            (
                payload.label,
                payload.kind,
                payload.description,
                None if payload.enabled is None else (1 if payload.enabled else 0),
                now,
                sid,
            ),
        )
        conn.commit()
        return {"ok": True, "source_id": sid}

    @app.post("/sources/{source_id}/activate")
    def activate_source(source_id: str) -> dict:
        sid = _sanitize_source_id(source_id)
        if not sid:
            raise HTTPException(status_code=400, detail="Invalid source id")

        if is_pg_primary and isinstance(repository, PostgresRepository):
            repository.init_schema(sid)
            with repository._connect() as pg_conn:
                now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
                with pg_conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO public.sources(id, label, enabled, is_default, created_at, updated_at)
                        VALUES(%s, %s, 1, 1, %s, %s)
                        ON CONFLICT(id) DO UPDATE SET is_default=1, updated_at=EXCLUDED.updated_at
                        """,
                        (sid, sid, now, now),
                    )
                    cur.execute("UPDATE public.sources SET is_default=0 WHERE id<>%s", (sid,))
                pg_conn.commit()
            return {"ok": True, "default_source_id": sid}

        conn = connect(settings.SX_DB_PATH)
        init_db(conn, enable_fts=settings.SX_DB_ENABLE_FTS)
        ensure_source(conn, sid, label=sid)
        set_default_source(conn, sid)
        conn.commit()
        return {"ok": True, "default_source_id": sid}

    @app.delete("/sources/{source_id}")
    def delete_source(source_id: str) -> dict:
        sid = _sanitize_source_id(source_id)
        if sid == default_source_id:
            raise HTTPException(status_code=400, detail="Cannot delete configured default source")

        if is_pg_primary and isinstance(repository, PostgresRepository):
            with repository._connect() as pg_conn:
                with pg_conn.cursor() as cur:
                    cur.execute("SELECT id, is_default FROM public.sources WHERE id=%s", (sid,))
                    src = cur.fetchone()
                    if not src:
                        raise HTTPException(status_code=404, detail="Source not found")
                    if int(src.get("is_default") or 0) == 1:
                        raise HTTPException(status_code=400, detail="Cannot delete active default source")

                    try:
                        schema = repository.resolve_schema(sid, create_if_missing=False)
                    except Exception:
                        schema = None

                    if schema:
                        cur.execute(f'SELECT COUNT(*) AS n FROM "{schema}".videos WHERE source_id=%s', (sid,))
                        videos_n = int((cur.fetchone() or {}).get("n") or 0)
                        if videos_n > 0:
                            raise HTTPException(status_code=400, detail="Source has data; delete rows first or disable it")
                        cur.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
                        cur.execute(f'DELETE FROM public.{repository._registry_table} WHERE source_id=%s', (sid,))

                    cur.execute("DELETE FROM public.sources WHERE id=%s", (sid,))
                pg_conn.commit()
            return {"ok": True, "deleted": sid}

        conn = connect(settings.SX_DB_PATH)
        init_db(conn, enable_fts=settings.SX_DB_ENABLE_FTS)

        src = conn.execute("SELECT id, is_default FROM sources WHERE id=?", (sid,)).fetchone()
        if not src:
            raise HTTPException(status_code=404, detail="Source not found")
        if int(src[1] or 0) == 1:
            raise HTTPException(status_code=400, detail="Cannot delete active default source")

        videos_n = conn.execute("SELECT COUNT(*) FROM videos WHERE source_id=?", (sid,)).fetchone()[0]
        if int(videos_n or 0) > 0:
            raise HTTPException(status_code=400, detail="Source has data; delete rows first or disable it")

        conn.execute("DELETE FROM sources WHERE id=?", (sid,))
        conn.commit()
        return {"ok": True, "deleted": sid}

    @app.get("/health")
    def health(request: Request):
        source_id = str(getattr(request.state, "sx_source_id", settings.SX_DEFAULT_SOURCE_ID))
        return {
            "ok": True,
            "source_id": source_id,
            "backend": dict(getattr(request.state, "sx_backend_ctx", {}) or {}),
            "profile_index": _source_profile_index(source_id),
            "db_path": str(settings.SX_DB_PATH),
            "api_version": "1.0.0",
            "env_hint": str(getattr(settings, "SX_DB_BACKEND_MODE", "SQLITE")),
        }

    @app.get("/")
    def root(request: Request):
        return {
            "service": "sx_obsidian SQLite API",
            "ok": True,
            "source_id": str(getattr(request.state, "sx_source_id", settings.SX_DEFAULT_SOURCE_ID)),
            "backend": dict(getattr(request.state, "sx_backend_ctx", {}) or {}),
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
    def stats(request: Request):
        """Lightweight DB stats for troubleshooting and plugin UX."""
        source_id = str(getattr(request.state, "sx_source_id", settings.SX_DEFAULT_SOURCE_ID))
        conn = _conn()

        total = conn.execute("SELECT COUNT(*) AS n FROM videos WHERE source_id=?", (source_id,)).fetchone()[0]
        bookmarked = conn.execute(
            "SELECT COUNT(*) AS n FROM videos WHERE source_id=? AND bookmarked=1",
            (source_id,),
        ).fetchone()[0]
        authors = conn.execute(
            """
            SELECT COUNT(DISTINCT author_unique_id) AS n
            FROM videos
            WHERE source_id=? AND author_unique_id IS NOT NULL AND author_unique_id != ''
            """,
            (source_id,),
        ).fetchone()[0]
        last_updated_at = conn.execute(
            "SELECT MAX(updated_at) AS t FROM videos WHERE source_id=?",
            (source_id,),
        ).fetchone()[0]

        has_fts = bool(
            conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='videos_fts'"
            ).fetchone()
        )
        fts_rows = (
            conn.execute("SELECT COUNT(*) FROM videos_fts WHERE source_id=?", (source_id,)).fetchone()[0] if has_fts else None
        )

        return {
            "db_path": str(settings.SX_DB_PATH),
            "source_id": source_id,
            "source_mode": "single-db",
            "backend": dict(getattr(request.state, "sx_backend_ctx", {}) or {}),
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
    def search(request: Request, q: str = "", limit: int = 50, offset: int = 0):
        source_id = str(getattr(request.state, "sx_source_id", settings.SX_DEFAULT_SOURCE_ID))
        conn = _conn()
        results = search_fn(conn, q, limit=limit, offset=offset, source_id=source_id)
        return {"results": results, "limit": limit, "offset": offset}

    @app.post("/admin/bootstrap/schema")
    def bootstrap_schema(payload: BootstrapSchemaIn = Body(...)) -> dict:
        sid = _sanitize_source_id(payload.source_id)
        if not sid:
            raise HTTPException(status_code=400, detail="Invalid source id")
        if not (is_pg_primary and isinstance(repository, PostgresRepository)):
            return {"ok": True, "backend": "sqlite", "source_id": sid, "message": "No-op outside POSTGRES_PRIMARY"}
        out = repository.init_schema(sid)
        return {"ok": True, **out}

    def _conn():
        if is_pg_primary and isinstance(repository, PostgresRepository):
            sid = _CTX_SOURCE_ID.get()
            return repository.connection_for_source(sid)
        conn = connect(settings.SX_DB_PATH)
        init_db(conn, enable_fts=settings.SX_DB_ENABLE_FTS)
        return conn

    def _sid(request: Request) -> str:
        return str(getattr(request.state, "sx_source_id", settings.SX_DEFAULT_SOURCE_ID))

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
    def danger_reset(request: Request, payload: DangerResetIn = Body(...)) -> dict:
        """Danger Zone reset.

        Supports dry-run previews (default). On apply:
        - reset_user_meta deletes rows from user_meta
        - reset_user_notes deletes rows from video_notes where template_version='user'
        - reset_cached_notes deletes rows from video_notes where template_version!='user'

        Scope is controlled by `filters` (same semantics as /items).
        """

        conn = _conn()
        source_id = _sid(request)
        f = payload.filters or DangerFilters()
        where_sql, params = _build_where_for_filters(f)
        source_where = "v.source_id=?"
        scoped_where_sql = where_sql.replace("WHERE ", f"WHERE {source_where} AND ") if where_sql else f"WHERE {source_where}"
        scoped_params: list[object] = [source_id, *params]

        # Subquery for the target set
        subq = (
            "SELECT v.id FROM videos v "
            "LEFT JOIN user_meta m ON m.video_id=v.id AND m.source_id=v.source_id "
            f"{scoped_where_sql}"
        )

        matched = conn.execute(
            (
                "SELECT COUNT(*) FROM videos v "
                "LEFT JOIN user_meta m ON m.video_id=v.id AND m.source_id=v.source_id "
                f"{scoped_where_sql}"
            ),
            tuple(scoped_params),
        ).fetchone()[0]

        meta_to_delete = 0
        user_notes_to_delete = 0
        cached_notes_to_delete = 0

        if payload.reset_user_meta:
            meta_to_delete = conn.execute(
                f"SELECT COUNT(*) FROM user_meta WHERE source_id=? AND video_id IN ({subq})",
                tuple([source_id, *scoped_params]),
            ).fetchone()[0]

        if payload.reset_user_notes:
            user_notes_to_delete = conn.execute(
                f"SELECT COUNT(*) FROM video_notes WHERE source_id=? AND template_version='user' AND video_id IN ({subq})",
                tuple([source_id, *scoped_params]),
            ).fetchone()[0]

        if payload.reset_cached_notes:
            cached_notes_to_delete = conn.execute(
                f"SELECT COUNT(*) FROM video_notes WHERE source_id=? AND template_version!='user' AND video_id IN ({subq})",
                tuple([source_id, *scoped_params]),
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
                f"DELETE FROM user_meta WHERE source_id=? AND video_id IN ({subq})",
                tuple([source_id, *scoped_params]),
            )

        if payload.reset_user_notes:
            conn.execute(
                f"DELETE FROM video_notes WHERE source_id=? AND template_version='user' AND video_id IN ({subq})",
                tuple([source_id, *scoped_params]),
            )

        if payload.reset_cached_notes:
            conn.execute(
                f"DELETE FROM video_notes WHERE source_id=? AND template_version!='user' AND video_id IN ({subq})",
                tuple([source_id, *scoped_params]),
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

    def _source_profile_index(source_id: str) -> int | None:
        s = str(source_id or "").strip().lower()
        if not s:
            return None
        m = re.search(r"(?:^|[_-])(?:p)?(\d{1,2})$", s)
        if not m:
            return None
        n = int(m.group(1))
        return n if n >= 1 else None

    def _wsl_to_windows_root(path_value: str | None) -> str | None:
        p = str(path_value or "").strip()
        if not p:
            return None
        m = re.match(r"^/mnt/([a-zA-Z])/(.*)$", p)
        if not m:
            return None
        drive = m.group(1).upper()
        tail = m.group(2).replace("/", "\\")
        return f"{drive}:\\{tail}" if tail else f"{drive}:\\"

    def _windows_to_wsl_root(path_value: str | None) -> str | None:
        p = str(path_value or "").strip()
        if not p:
            return None
        # Accept X:\foo\bar or X:/foo/bar
        m = re.match(r"^([a-zA-Z]):[\\/]*(.*)$", p)
        if not m:
            return None
        drive = m.group(1).lower()
        tail = str(m.group(2) or "").replace("\\", "/").lstrip("/")
        return f"/mnt/{drive}/{tail}" if tail else f"/mnt/{drive}"

    def _build_media_resolution_context(source_id: str) -> dict[str, object]:
        """Resolve source-aware media roots for on-disk media existence checks.

        Media resolution should prefer source roots (`SRC_PATH_N`) and avoid vault-root
        assumptions that can produce false negatives in split-root deployments.
        """

        env_map: dict[str, str] = dict(os.environ)
        try:
            env_map.update(_parse_env_file(Path(".env")))
        except Exception:
            pass
        try:
            if settings.SX_SCHEDULERX_ENV:
                env_map.update(_parse_env_file(Path(settings.SX_SCHEDULERX_ENV)))
        except Exception:
            pass

        sid = _sanitize_source_id(source_id)
        idx = _source_profile_index(sid)

        if idx is None:
            indices: set[int] = set()
            for k in env_map.keys():
                m = re.match(r"^(SRC_PATH|SRC_PROFILE)_(\d+)$", k)
                if m:
                    indices.add(int(m.group(2)))
            for i in sorted(indices):
                if _source_id_from_profile_env(env_map, i) == sid:
                    idx = i
                    break

        src_linux = None
        src_windows = None
        vault_linux = None
        vault_windows = None
        resolution = ""

        if idx is not None:
            src_linux = (
                env_map.get(f"SRC_PATH_{idx}")
                or env_map.get(f"SRC_PROFILE_{idx}")
                or None
            )
            src_windows = (
                env_map.get(f"SRC_PATH_WINDOWS_{idx}")
                or env_map.get(f"SRC_PROFILE_WINDOWS_{idx}")
                or _wsl_to_windows_root(src_linux)
            )

            vault_linux = (
                env_map.get(f"VAULT_PATH_{idx}")
                or env_map.get(f"VAULT_{idx}")
                or None
            )
            vault_windows = (
                env_map.get(f"VAULT_PATH_WINDOWS_{idx}")
                or env_map.get(f"VAULT_WINDOWS_{idx}")
                or env_map.get(f"VAULT_WIN_{idx}")
                or _wsl_to_windows_root(vault_linux)
            )

            # Some deployments store SRC_PATH_N as a Windows path even when API runs
            # in Linux/WSL. Normalize this case so file existence checks remain valid.
            if src_linux and re.match(r"^[a-zA-Z]:[\\/]", str(src_linux)):
                src_windows = src_windows or str(src_linux)
                src_linux = _windows_to_wsl_root(str(src_linux)) or src_linux

            if vault_linux and re.match(r"^[a-zA-Z]:[\\/]", str(vault_linux)):
                vault_windows = vault_windows or str(vault_linux)
                vault_linux = _windows_to_wsl_root(str(vault_linux)) or vault_linux

            resolution = f"profile_{idx}"
        else:
            # Operational fallback for environments without indexed profile mappings.
            # Keep this source-root oriented by using SX_MEDIA_VAULT only if explicitly set.
            src_linux = settings.SX_MEDIA_VAULT or None
            src_windows = _wsl_to_windows_root(src_linux)
            vault_linux = settings.VAULT_default or settings.SX_MEDIA_VAULT or None
            vault_windows = settings.VAULT_WINDOWS_default or _wsl_to_windows_root(vault_linux)
            resolution = "fallback_media_vault"

        return {
            "source_id": sid,
            "profile_index": idx,
            "source_root_linux": str(src_linux or "").strip() or None,
            "source_root_windows": str(src_windows or "").strip() or None,
            "vault_root_linux": str(vault_linux or "").strip() or None,
            "vault_root_windows": str(vault_windows or "").strip() or None,
            "resolution": resolution or "none",
        }

    def _resolve_vault_roots_for_source(source_id: str) -> tuple[str | None, str | None]:
        """Resolve source-specific media roots (linux + windows) for link/media generation.

        Priority is SRC_PATH_N (source/media root). VAULT_PATH_N/VAULT_N remain fallback.
        """

        env_map: dict[str, str] = dict(os.environ)
        try:
            env_map.update(_parse_env_file(Path(".env")))
        except Exception:
            pass
        try:
            if settings.SX_SCHEDULERX_ENV:
                env_map.update(_parse_env_file(Path(settings.SX_SCHEDULERX_ENV)))
        except Exception:
            pass

        sid = _sanitize_source_id(source_id)
        idx = _source_profile_index(sid)

        if idx is None:
            indices: set[int] = set()
            for k in env_map.keys():
                m = re.match(r"^(SRC_PATH|SRC_PROFILE|VAULT_PATH|VAULT|VAULT_WINDOWS|VAULT_WIN)_(\d+)$", k)
                if m:
                    indices.add(int(m.group(2)))
            for i in sorted(indices):
                if _source_id_from_profile_env(env_map, i) == sid:
                    idx = i
                    break

        default_linux = settings.SX_MEDIA_VAULT or settings.VAULT_default
        default_windows = settings.VAULT_WINDOWS_default

        if idx is None:
            return default_linux, default_windows

        linux_root = (
            env_map.get(f"SRC_PATH_{idx}")
            or env_map.get(f"SRC_PROFILE_{idx}")
            or env_map.get(f"VAULT_PATH_{idx}")
            or env_map.get(f"VAULT_{idx}")
            or default_linux
        )
        windows_root = (
            env_map.get(f"SRC_PATH_WINDOWS_{idx}")
            or env_map.get(f"SRC_PROFILE_WINDOWS_{idx}")
            or env_map.get(f"VAULT_WINDOWS_{idx}")
            or env_map.get(f"VAULT_WIN_{idx}")
            or _wsl_to_windows_root(linux_root)
            or default_windows
        )

        return linux_root, windows_root

    def _resolve_group_link_prefix_for_source(source_id: str) -> str | None:
        """Resolve PathLinker-style group prefix for a source, when needed.

        Uses explicit env overrides first, then auto-enables `group:<source_id>/...`
        when SRC_PATH_N and VAULT_N differ.
        """

        env_map: dict[str, str] = dict(os.environ)
        try:
            # Only read the local .env when no explicit scheduler env is configured,
            # to avoid the project .env contaminating isolated profiles.
            if not settings.SX_SCHEDULERX_ENV:
                env_map.update(_parse_env_file(Path(".env")))
        except Exception:
            pass
        try:
            if settings.SX_SCHEDULERX_ENV:
                env_map.update(_parse_env_file(Path(settings.SX_SCHEDULERX_ENV)))
        except Exception:
            pass

        sid = _sanitize_source_id(source_id)
        idx = _source_profile_index(sid)
        if idx is None:
            indices: set[int] = set()
            for k in env_map.keys():
                m = re.match(r"^(SRC_PATH|SRC_PROFILE|VAULT_PATH|VAULT)_(\d+)$", k)
                if m:
                    indices.add(int(m.group(2)))
            for i in sorted(indices):
                if _source_id_from_profile_env(env_map, i) == sid:
                    idx = i
                    break

        if idx is None:
            return None

        explicit = (
            env_map.get(f"PATHLINKER_GROUP_{idx}")
            or env_map.get(f"GROUP_LINK_{idx}")
            or ""
        ).strip().strip("/")
        if explicit:
            return explicit

        src_root = (env_map.get(f"SRC_PATH_{idx}") or env_map.get(f"SRC_PROFILE_{idx}") or "").strip()
        vault_root = (env_map.get(f"VAULT_PATH_{idx}") or env_map.get(f"VAULT_{idx}") or src_root).strip()

        if src_root and vault_root and src_root != vault_root:
            return sid

        return None

    def _sanitize_group_prefix(value: object) -> str | None:
        raw = str(value or "").strip().strip("/")
        if not raw:
            return None
        # Keep conservative chars used in group names/paths.
        cleaned = re.sub(r"[^a-zA-Z0-9._/-]", "", raw)
        cleaned = cleaned.strip().strip("/")
        return cleaned or None

    def _note_resolver(source_id: str | None = None, group_link_prefix_override: str | None = None) -> PathResolver:
        # Build a resolver using source-aware media roots.
        sid = _sanitize_source_id(source_id or _CTX_SOURCE_ID.get() or settings.SX_DEFAULT_SOURCE_ID)
        vault_linux, vault_windows = _resolve_vault_roots_for_source(sid)
        group_link_prefix = _sanitize_group_prefix(group_link_prefix_override) or _resolve_group_link_prefix_for_source(sid)
        config = {
            "path_style": settings.PATH_STYLE,
            "vault": vault_linux or settings.SX_MEDIA_VAULT or settings.VAULT_default,
            "vault_windows": vault_windows or settings.VAULT_WINDOWS_default,
            "data_dir": settings.SX_MEDIA_DATA_DIR or settings.DATA_DIR,
            "group_link_prefix": group_link_prefix,
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

    def _fetch_video_with_meta(conn, item_id: str, source_id: str) -> dict | None:
        row = conn.execute(
            """
            SELECT
              v.*, 
                            m.rating, m.status, m.statuses, m.tags, m.notes,
                                                        m.product_link, m.author_links, m.platform_targets, m.workflow_log, m.post_url, m.published_time
            FROM videos v
            LEFT JOIN user_meta m ON m.video_id = v.id AND m.source_id = v.source_id
            WHERE v.id=? AND v.source_id=?
            """,
            (item_id, source_id),
        ).fetchone()
        return dict(row) if row else None

    def _get_cached_note(conn, item_id: str, source_id: str) -> tuple[str, str | None] | None:
        """Return cached markdown from DB.

        Notes are user-owned once persisted: if a user edits the synced .md in Obsidian
        and pushes it back, we must not discard it just because the template version changed.
        Use `force=true` to regenerate from the latest template.
        """

        row = conn.execute(
            "SELECT markdown, template_version FROM video_notes WHERE video_id=? AND source_id=?",
            (item_id, source_id),
        ).fetchone()
        if not row:
            return None
        return (row[0], row[1])

    def _render_and_cache_note(
        conn,
        video: dict,
        source_id: str,
        group_link_prefix_override: str | None = None,
    ) -> str:
        _ensure_media_paths(video)

        resolver = _note_resolver(source_id, group_link_prefix_override=group_link_prefix_override)

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

        # Notes rendered with an explicit override are considered client-local
        # and should not mutate shared DB cache.
        if group_link_prefix_override:
            return md

        if not media_present:
            return md

        now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        conn.execute(
            """
                        INSERT INTO video_notes(video_id, source_id, markdown, template_version, updated_at)
                        VALUES(?, ?, ?, ?, ?)
            ON CONFLICT(source_id, video_id) DO UPDATE SET
                            source_id=excluded.source_id,
              markdown=excluded.markdown,
              template_version=excluded.template_version,
              updated_at=excluded.updated_at
            """,
                        (str(video["id"]), source_id, md, TEMPLATE_VERSION, now),
        )
        conn.commit()
        return md

    @app.get("/authors")
    def list_authors(
        request: Request,
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
        source_id = _sid(request)

        where = ["v.source_id=?", "(v.author_unique_id IS NOT NULL AND v.author_unique_id != '')"]
        params: list[object] = [source_id]

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
                        ) author_groups
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
        request: Request,
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
        source_id = _sid(request)

        where = ["v.source_id=?"]
        params: list[object] = [source_id]

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
            LEFT JOIN user_meta m ON m.video_id = v.id AND m.source_id = v.source_id
            {where_sql}
            {order_sql}
            LIMIT ? OFFSET ?
            """,
            (*params, limit, offset),
        ).fetchall()

        total = conn.execute(
            f"SELECT COUNT(*) FROM videos v LEFT JOIN user_meta m ON m.video_id=v.id AND m.source_id=v.source_id {where_sql}",
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
    def get_meta(item_id: str, request: Request) -> dict:
        conn = _conn()
        source_id = _sid(request)
        row = conn.execute(
            """
            SELECT m.video_id, m.rating, m.status, m.statuses, m.tags, m.notes,
                   m.product_link, m.author_links, m.platform_targets, m.workflow_log,
                   m.post_url, m.published_time, m.updated_at
            FROM user_meta m
            JOIN videos v ON v.id = m.video_id
            WHERE m.video_id=? AND v.source_id=? AND m.source_id=v.source_id
            """,
            (item_id, source_id),
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
    def put_meta(item_id: str, request: Request, meta: MetaIn = Body(...)) -> dict:
        conn = _conn()
        source_id = _sid(request)
        exists = conn.execute("SELECT 1 FROM videos WHERE id=? AND source_id=?", (item_id, source_id)).fetchone()
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
                "SELECT author_links FROM user_meta WHERE video_id=? AND source_id=?",
                (item_id, source_id),
            ).fetchone()
            author_links_list = _unpack_url_list(existing_links_row[0] if existing_links_row else None)
        packed_author_links = _pack_url_list(author_links_list)

        author_row = conn.execute(
            "SELECT author_unique_id, author_name FROM videos WHERE id=? AND source_id=?",
            (item_id, source_id),
        ).fetchone()
        author_uid = str((author_row[0] if author_row else "") or "").strip()
        author_name = str((author_row[1] if author_row else "") or "").strip()

        conn.execute(
            """
            INSERT INTO user_meta(
                                video_id, source_id, rating, status, statuses, tags, notes,
                product_link, author_links, platform_targets, workflow_log, post_url, published_time,
                updated_at
            )
                        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_id, video_id) DO UPDATE SET
                            source_id=excluded.source_id,
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
                source_id,
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
                                INSERT INTO user_meta(video_id, source_id, author_links, updated_at)
                                SELECT v.id, v.source_id, ?, ?
                FROM videos v
                                WHERE v.author_unique_id = ? AND v.source_id = ?
                ON CONFLICT(source_id, video_id) DO UPDATE SET
                                    source_id=excluded.source_id,
                  author_links=excluded.author_links,
                  updated_at=excluded.updated_at
                """,
                                (packed_author_links, now, author_uid, source_id),
            )
        elif author_links_was_provided and author_name:
            conn.execute(
                """
                                INSERT INTO user_meta(video_id, source_id, author_links, updated_at)
                                SELECT v.id, v.source_id, ?, ?
                FROM videos v
                WHERE (v.author_unique_id IS NULL OR TRIM(v.author_unique_id) = '')
                  AND COALESCE(TRIM(v.author_name), '') = ?
                                    AND v.source_id = ?
                                ON CONFLICT(source_id, video_id) DO UPDATE SET
                                    source_id=excluded.source_id,
                  author_links=excluded.author_links,
                  updated_at=excluded.updated_at
                """,
                                (packed_author_links, now, author_name, source_id),
            )
        conn.commit()

        dumped = meta.model_dump()
        # Ensure response reflects normalized state.
        dumped["statuses"] = statuses_list
        dumped["status"] = primary_status
        dumped["author_links"] = author_links_list
        out = {"video_id": item_id, **dumped, "updated_at": now}
        return {"meta": out}

    def _safe_media_path(relative_path: str, source_id: str) -> Path:
        if not relative_path:
            raise HTTPException(status_code=404, detail="No media path for item")

        sid = _sanitize_source_id(source_id)
        request_id = _CTX_REQUEST_ID.get()
        media_ctx = _build_media_resolution_context(sid)

        src_linux = str(media_ctx.get("source_root_linux") or "").strip()
        src_windows = str(media_ctx.get("source_root_windows") or "").strip()
        vault_linux = str(media_ctx.get("vault_root_linux") or "").strip()
        vault_windows = str(media_ctx.get("vault_root_windows") or "").strip()
        src_windows_wsl = _windows_to_wsl_root(src_windows) if src_windows else None
        vault_windows_wsl = _windows_to_wsl_root(vault_windows) if vault_windows else None

        roots: list[tuple[str, str]] = []
        if src_linux:
            roots.append(("src_linux", src_linux))
        if src_windows_wsl:
            roots.append(("src_windows_as_wsl", src_windows_wsl))
        if vault_linux and vault_linux != src_linux:
            roots.append(("vault_linux", vault_linux))
        if vault_windows_wsl and vault_windows_wsl not in {src_windows_wsl, src_linux, vault_linux}:
            roots.append(("vault_windows_as_wsl", vault_windows_wsl))

        if not roots:
            raise HTTPException(status_code=500, detail="Source media root is not configured (SRC_PATH_N/SX_MEDIA_VAULT)")

        rel = str(relative_path).strip().replace("\\", "/").lstrip("/")
        if not rel:
            raise HTTPException(status_code=404, detail="No media path for item")

        data_dir = str(settings.SX_MEDIA_DATA_DIR or settings.DATA_DIR or "data").strip().strip("/\\") or "data"

        candidates: list[tuple[str, Path, Path]] = []
        seen: set[str] = set()
        for root_name, root in roots:
            root_path = Path(root)

            # Preferred path: <SRC_PATH_N>/<DATA_DIR>/<relative_path>
            preferred = root_path / data_dir / rel
            # Fallback path: <SRC_PATH_N>/<relative_path> (handles rows that already include data/ prefix)
            fallback = root_path / rel

            for mode, p in (("preferred", preferred), ("fallback", fallback)):
                key = str(p)
                if key in seen:
                    continue
                seen.add(key)
                candidates.append((f"{root_name}:{mode}", p, root_path))

        diagnostics: list[dict[str, object]] = []
        for label, candidate, base_root in candidates:
            try:
                cand_resolved = candidate.resolve()
                base_resolved = base_root.resolve()
                cand_resolved.relative_to(base_resolved)
                exists = cand_resolved.exists()
                diagnostics.append({"candidate": str(cand_resolved), "label": label, "exists": exists})
                if exists:
                    _MEDIA_LOG.info(
                        "media.resolve request_id=%s source_id=%s profile_index=%s resolution=%s relative_path=%s selected=%s checked=%s",
                        request_id,
                        sid,
                        media_ctx.get("profile_index"),
                        media_ctx.get("resolution"),
                        rel,
                        str(cand_resolved),
                        diagnostics,
                    )
                    return cand_resolved
            except Exception:
                diagnostics.append({"candidate": str(candidate), "label": label, "exists": False, "error": "invalid_or_unsafe"})

        _MEDIA_LOG.warning(
            "media.resolve request_id=%s source_id=%s profile_index=%s resolution=%s relative_path=%s selected=none checked=%s",
            request_id,
            sid,
            media_ctx.get("profile_index"),
            media_ctx.get("resolution"),
            rel,
            diagnostics,
        )
        raise HTTPException(status_code=404, detail="Media file not found")

    @app.get("/media/cover/{item_id}")
    def media_cover(item_id: str, request: Request):
        conn = _conn()
        source_id = _sid(request)
        row = conn.execute(
            "SELECT cover_path, bookmarked, author_id FROM videos WHERE id=? AND source_id=?",
            (item_id, source_id),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Not found")
        cover_path = row[0] or ""
        if not cover_path:
            _, derived_cp = _canonical_media_paths(item_id=item_id, bookmarked=row[1], author_id=row[2])
            cover_path = derived_cp
        path = _safe_media_path(cover_path, source_id)
        media_type, _ = mimetypes.guess_type(str(path))
        return FileResponse(path, media_type=media_type or "image/jpeg")

    @app.get("/media/video/{item_id}")
    def media_video(item_id: str, request: Request):
        conn = _conn()
        source_id = _sid(request)
        row = conn.execute(
            "SELECT video_path, bookmarked, author_id FROM videos WHERE id=? AND source_id=?",
            (item_id, source_id),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Not found")
        video_path = row[0] or ""
        if not video_path:
            derived_vp, _ = _canonical_media_paths(item_id=item_id, bookmarked=row[1], author_id=row[2])
            video_path = derived_vp
        path = _safe_media_path(video_path, source_id)
        media_type, _ = mimetypes.guess_type(str(path))
        # Starlette's FileResponse supports Range requests (important for video preview).
        return FileResponse(path, media_type=media_type or "video/mp4")

    @app.get("/items/{item_id}/links")
    def get_item_links(item_id: str, request: Request) -> dict:
        """Return protocol links for opening/revealing local media.

        This is intended for the Obsidian plugin's Open/Reveal buttons.
        It avoids depending on cached note frontmatter (which may be missing
        in older notes or user-edited YAML).
        """

        conn = _conn()
        source_id = _sid(request)
        row = conn.execute(
            "SELECT id, video_path, cover_path, bookmarked, author_id FROM videos WHERE id=? AND source_id=?",
            (item_id, source_id),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Not found")

        d = dict(row)
        _ensure_media_paths(d)

        resolver = _note_resolver(source_id)

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
    def get_item(item_id: str, request: Request):
        conn = _conn()
        source_id = _sid(request)
        row = conn.execute("SELECT * FROM videos WHERE id=? AND source_id=?", (item_id, source_id)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Not found")
        return {"item": dict(row)}

    @app.get("/items/{item_id}/raw")
    def get_item_raw(item_id: str, request: Request):
        """Return full-fidelity raw CSV rows stored in the DB.

        This is intentionally separate from /items/{id} so normal UI flows stay light.
        """

        conn = _conn()
        source_id = _sid(request)
        item = conn.execute(
            "SELECT id, author_id, bookmarked FROM videos WHERE id=? AND source_id=?",
            (item_id, source_id),
        ).fetchone()
        if not item:
            raise HTTPException(status_code=404, detail="Not found")

        consolidated = conn.execute(
            "SELECT row_json, csv_row_hash, imported_at FROM csv_consolidated_raw WHERE source_id=? AND video_id=?",
            (source_id, item_id),
        ).fetchone()

        bookmark = conn.execute(
            "SELECT row_json, imported_at FROM csv_bookmarks_raw WHERE source_id=? AND video_id=?",
            (source_id, item_id),
        ).fetchone()

        author_id = (item["author_id"] or "").strip()
        author = None
        if author_id:
            author = conn.execute(
                "SELECT row_json, imported_at FROM csv_authors_raw WHERE source_id=? AND author_id=?",
                (source_id, author_id),
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
    def get_item_note(
        item_id: str,
        request: Request,
        force: bool = False,
        pathlinker_group: str | None = None,
    ):
        conn = _conn()
        source_id = _sid(request)
        group_override = _sanitize_group_prefix(pathlinker_group)
        cached = _get_cached_note(conn, item_id, source_id)
        if cached:
            md, tv = cached

            # If the user pushed their own note content, never overwrite it
            # unless the caller explicitly asks for regeneration.
            if tv == "user" and not force:
                return {
                    "id": item_id,
                    "markdown": md,
                    "cached": True,
                    "template_version": tv,
                    "stale": False,
                }

            is_stale = bool(tv and tv != TEMPLATE_VERSION)
            if (not force) and (not group_override) and (not is_stale):
                return {
                    "id": item_id,
                    "markdown": md,
                    "cached": True,
                    "template_version": tv,
                    "stale": False,
                }

        video = _fetch_video_with_meta(conn, item_id, source_id)
        if not video:
            raise HTTPException(status_code=404, detail="Not found")

        _ensure_media_paths(video)

        md = _render_and_cache_note(conn, video, source_id, group_link_prefix_override=group_override)
        return {"id": item_id, "markdown": md, "cached": False, "template_version": TEMPLATE_VERSION, "stale": False}

    @app.put("/items/{item_id}/note-md")
    def put_item_note_md(item_id: str, request: Request, payload: NoteIn = Body(...)) -> dict:
        """Upsert markdown note content into `video_notes`.

        Used when the user edits synced notes in Obsidian and wants to persist those edits.
        """

        conn = _conn()
        source_id = _sid(request)
        exists = conn.execute("SELECT 1 FROM videos WHERE id=? AND source_id=?", (item_id, source_id)).fetchone()
        if not exists:
            raise HTTPException(status_code=404, detail="Not found")

        md = (payload.markdown or "").strip("\ufeff")
        if not md:
            raise HTTPException(status_code=400, detail="Empty markdown")

        tv = payload.template_version or "user"
        now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        conn.execute(
            """
                        INSERT INTO video_notes(video_id, source_id, markdown, template_version, updated_at)
                        VALUES(?, ?, ?, ?, ?)
            ON CONFLICT(source_id, video_id) DO UPDATE SET
                            source_id=excluded.source_id,
              markdown=excluded.markdown,
              template_version=excluded.template_version,
              updated_at=excluded.updated_at
            """,
                        (item_id, source_id, md, tv, now),
        )
        conn.commit()
        return {"ok": True, "id": item_id, "template_version": tv, "updated_at": now}

    @app.post("/items/{item_id}/schedule")
    def schedule_item(item_id: str, request: Request):
        source_id = _sid(request)
        result = scheduler.enqueue_scheduling_job(source_id, item_id)
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=result.get("error"))
        return result

    @app.get("/jobs")
    def list_jobs(request: Request, limit: int = 50, offset: int = 0):
        source_id = _sid(request)
        conn = _conn()
        rows = conn.execute(
            "SELECT id, video_id, platform, action, status, scheduled_time, created_at, updated_at FROM job_queue WHERE source_id=? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (source_id, limit, offset)
        ).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM job_queue WHERE source_id=?", (source_id,)).fetchone()[0]
        return {"jobs": [dict(r) for r in rows], "total": int(total), "limit": limit, "offset": offset}

    @app.post("/admin/sync-vault")
    def sync_vault(request: Request):
        source_id = _sid(request)
        return {"ok": True, "message": f"Triggered Local Vault metadata sync for {source_id}.", "source_id": source_id}

    @app.post("/media/sync-all")
    def sync_all_media(request: Request):
        source_id = _sid(request)
        return {"ok": True, "message": f"R2 Media sync enqueued to background worker for {source_id}.", "source_id": source_id}

    @app.post("/scheduler/process-all")
    def process_all_scheduled(request: Request):
        source_id = _sid(request)
        return {"ok": True, "message": f"Draft notes pushed to JSON scheduling pipeline for {source_id}.", "source_id": source_id}



    @app.get("/notes")
    def bulk_notes(
        request: Request,
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
        pathlinker_group: str | None = None,
        order: str = Query("recent", pattern="^(recent|bookmarked|author|status|rating)$"),
    ):
        """Return rendered markdown notes for syncing into the vault.

        Notes are persisted in `video_notes` so subsequent syncs can be fast.
        """
        conn = _conn()
        source_id = _sid(request)
        group_override = _sanitize_group_prefix(pathlinker_group)

        where = ["v.source_id=?"]
        params: list[object] = [source_id]

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
            LEFT JOIN user_meta m ON m.video_id = v.id AND m.source_id = v.source_id
            {where_sql}
            {order_sql}
            LIMIT ? OFFSET ?
            """,
            (*params, limit, offset),
        ).fetchall()

        total = conn.execute(
            f"SELECT COUNT(*) FROM videos v LEFT JOIN user_meta m ON m.video_id=v.id AND m.source_id=v.source_id {where_sql}",
            tuple(params),
        ).fetchone()[0]

        out = []
        for r in rows:
            v = dict(r)
            _ensure_media_paths(v)
            vid = str(v["id"])
            md = None
            cached = _get_cached_note(conn, vid, source_id)
            if cached:
                cached_md, cached_tv = cached
                if cached_tv == "user" and not force:
                    md = cached_md
                elif (not force) and (not group_override) and (not cached_tv or cached_tv == TEMPLATE_VERSION):
                    md = cached_md
            if md is None:
                md = _render_and_cache_note(conn, v, source_id, group_link_prefix_override=group_override)

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
