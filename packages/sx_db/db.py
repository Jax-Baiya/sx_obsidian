from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path


SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA temp_store=MEMORY;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    label TEXT,
    kind TEXT,
    description TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    is_default INTEGER NOT NULL DEFAULT 0,
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS videos (
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
);

-- User-editable metadata (owned by the user; never overwritten by CSV imports)
CREATE TABLE IF NOT EXISTS user_meta (
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
    PRIMARY KEY(source_id, video_id),
    FOREIGN KEY(source_id, video_id) REFERENCES videos(source_id, id) ON DELETE CASCADE
);

-- Cached/persisted markdown notes (rendered from template; used for fast sync into vault)
CREATE TABLE IF NOT EXISTS video_notes (
    source_id TEXT NOT NULL DEFAULT 'default',
    video_id TEXT NOT NULL,
    markdown TEXT NOT NULL,
    template_version TEXT,
    updated_at TEXT,
    PRIMARY KEY(source_id, video_id),
    FOREIGN KEY(source_id, video_id) REFERENCES videos(source_id, id) ON DELETE CASCADE
);

-- Raw CSV row retention (full-fidelity source data)
-- These tables intentionally store the full CSV DictReader row as JSON so we can
-- evolve mappings over time without needing to constantly migrate the main schema.
CREATE TABLE IF NOT EXISTS csv_consolidated_raw (
    source_id TEXT NOT NULL DEFAULT 'default',
    video_id TEXT NOT NULL,
    row_json TEXT NOT NULL,
    csv_row_hash TEXT,
    imported_at TEXT,
    PRIMARY KEY(source_id, video_id)
);

CREATE TABLE IF NOT EXISTS csv_authors_raw (
    source_id TEXT NOT NULL DEFAULT 'default',
    author_id TEXT NOT NULL,
    row_json TEXT NOT NULL,
    imported_at TEXT,
    PRIMARY KEY(source_id, author_id)
);

CREATE TABLE IF NOT EXISTS csv_bookmarks_raw (
    source_id TEXT NOT NULL DEFAULT 'default',
    video_id TEXT NOT NULL,
    row_json TEXT NOT NULL,
    imported_at TEXT,
    PRIMARY KEY(source_id, video_id)
);

CREATE TABLE IF NOT EXISTS scheduling_artifacts (
    source_id TEXT NOT NULL DEFAULT 'default',
    video_id TEXT NOT NULL,
    platform TEXT NOT NULL,
    artifact_json TEXT NOT NULL,
    r2_media_url TEXT,
    status TEXT NOT NULL DEFAULT 'draft_review',
    created_at TEXT,
    updated_at TEXT,
    PRIMARY KEY(source_id, video_id, platform)
);

CREATE TABLE IF NOT EXISTS job_queue (
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
);
"""

FTS_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS videos_fts USING fts5(
  source_id UNINDEXED,
  id UNINDEXED,
  caption,
  author_unique_id,
  author_name,
  content=''
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection, *, enable_fts: bool) -> None:
    conn.executescript(SCHEMA_SQL)
    _ensure_columns(conn)
    _ensure_composite_primary_keys(conn)
    _ensure_indexes(conn)
    if enable_fts:
        conn.executescript(FTS_SQL)
    conn.commit()


def _ensure_columns(conn: sqlite3.Connection) -> None:
    """Best-effort schema migration for existing databases.

    SQLite doesn't support many ALTER TABLE operations, but adding columns is safe.
    Keep this minimal and additive.
    """

    def _cols(table: str) -> set[str]:
        try:
            return {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        except Exception:
            return set()

    def _add_column_if_missing(table: str, name: str, decl: str) -> None:
        cols = _cols(table)
        if name in cols:
            return
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")

    videos_cols = _cols("videos")

    to_add: list[tuple[str, str]] = [
        ("source_id", "TEXT NOT NULL DEFAULT 'default'"),
        ("followers", "INTEGER"),
        ("hearts", "INTEGER"),
        ("videos_count", "INTEGER"),
        ("signature", "TEXT"),
        ("is_private", "INTEGER"),
    ]

    for name, decl in to_add:
        _add_column_if_missing("videos", name, decl)

    if "source_id" in _cols("videos"):
        conn.execute(
            "UPDATE videos SET source_id='default' WHERE source_id IS NULL OR TRIM(source_id)=''"
        )

    # user_meta additive columns (user-owned workflow fields)
    meta_cols = _cols("user_meta")
    meta_to_add: list[tuple[str, str]] = [
        ("source_id", "TEXT NOT NULL DEFAULT 'default'"),
        # Core user_meta columns (some very old DBs may not have them)
        ("rating", "INTEGER"),
        ("status", "TEXT"),
        ("tags", "TEXT"),
        ("notes", "TEXT"),
        ("statuses", "TEXT"),
        ("product_link", "TEXT"),
        ("author_links", "TEXT"),
        ("platform_targets", "TEXT"),
        ("workflow_log", "TEXT"),
        ("post_url", "TEXT"),
        ("published_time", "TEXT"),
    ]
    for name, decl in meta_to_add:
        _add_column_if_missing("user_meta", name, decl)

    if "source_id" in _cols("user_meta"):
        conn.execute(
            "UPDATE user_meta SET source_id='default' WHERE source_id IS NULL OR TRIM(source_id)=''"
        )

    notes_cols = _cols("video_notes")
    if "source_id" not in notes_cols:
        _add_column_if_missing("video_notes", "source_id", "TEXT NOT NULL DEFAULT 'default'")
    if "source_id" in _cols("video_notes"):
        conn.execute(
            "UPDATE video_notes SET source_id='default' WHERE source_id IS NULL OR TRIM(source_id)=''"
        )

    # Raw tables source columns for source-scoped retention.
    for t, col in [
        ("csv_consolidated_raw", "video_id"),
        ("csv_bookmarks_raw", "video_id"),
        ("csv_authors_raw", "author_id"),
    ]:
        if _cols(t):
            _add_column_if_missing(t, "source_id", "TEXT NOT NULL DEFAULT 'default'")
            conn.execute(f"UPDATE {t} SET source_id='default' WHERE source_id IS NULL OR TRIM(source_id)=''")

    # Source registry additive columns.
    source_cols = _cols("sources")
    if source_cols:
        _add_column_if_missing("sources", "label", "TEXT")
        _add_column_if_missing("sources", "kind", "TEXT")
        _add_column_if_missing("sources", "description", "TEXT")
        _add_column_if_missing("sources", "enabled", "INTEGER NOT NULL DEFAULT 1")
        _add_column_if_missing("sources", "is_default", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing("sources", "created_at", "TEXT")
        _add_column_if_missing("sources", "updated_at", "TEXT")

    # Scheduling tables additive columns
    artifacts_cols = _cols("scheduling_artifacts")
    if artifacts_cols:
        _add_column_if_missing("scheduling_artifacts", "source_id", "TEXT NOT NULL DEFAULT 'default'")
        _add_column_if_missing("scheduling_artifacts", "video_id", "TEXT NOT NULL")
        _add_column_if_missing("scheduling_artifacts", "platform", "TEXT NOT NULL")
        _add_column_if_missing("scheduling_artifacts", "artifact_json", "TEXT NOT NULL")
        _add_column_if_missing("scheduling_artifacts", "r2_media_url", "TEXT")
        _add_column_if_missing("scheduling_artifacts", "status", "TEXT NOT NULL DEFAULT 'draft_review'")
        _add_column_if_missing("scheduling_artifacts", "created_at", "TEXT")
        _add_column_if_missing("scheduling_artifacts", "updated_at", "TEXT")

    jobs_cols = _cols("job_queue")
    if jobs_cols:
        _add_column_if_missing("job_queue", "id", "TEXT PRIMARY KEY")
        _add_column_if_missing("job_queue", "source_id", "TEXT NOT NULL DEFAULT 'default'")
        _add_column_if_missing("job_queue", "video_id", "TEXT NOT NULL")
        _add_column_if_missing("job_queue", "platform", "TEXT NOT NULL")
        _add_column_if_missing("job_queue", "action", "TEXT NOT NULL")
        _add_column_if_missing("job_queue", "status", "TEXT NOT NULL DEFAULT 'pending'")
        _add_column_if_missing("job_queue", "scheduled_time", "TEXT")
        _add_column_if_missing("job_queue", "execute_after", "TEXT")
        _add_column_if_missing("job_queue", "result_json", "TEXT")
        _add_column_if_missing("job_queue", "error_message", "TEXT")
        _add_column_if_missing("job_queue", "retry_count", "INTEGER DEFAULT 0")
        _add_column_if_missing("job_queue", "created_at", "TEXT")
        _add_column_if_missing("job_queue", "updated_at", "TEXT")


def _ensure_composite_primary_keys(conn: sqlite3.Connection) -> None:
    """Rebuild legacy tables so PKs are source-aware composites.

    This enables duplicate item IDs across different sources while preserving
    strict uniqueness within a source.
    """

    def _pk_cols(table: str) -> list[str]:
        try:
            rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
            pks = [(int(r[5]), str(r[1])) for r in rows if int(r[5]) > 0]
            return [name for _, name in sorted(pks, key=lambda x: x[0])]
        except Exception:
            return []

    def _rebuild_videos() -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS videos__new (
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
        conn.execute(
            """
            INSERT OR REPLACE INTO videos__new(
              source_id, id, platform, author_id, author_unique_id, author_name,
              followers, hearts, videos_count, signature, is_private,
              caption, bookmarked, bookmark_timestamp, video_path, cover_path,
              csv_row_hash, updated_at
            )
            SELECT
              COALESCE(NULLIF(TRIM(source_id), ''), 'default') AS source_id,
              id, platform, author_id, author_unique_id, author_name,
              followers, hearts, videos_count, signature, is_private,
              caption, bookmarked, bookmark_timestamp, video_path, cover_path,
              csv_row_hash, updated_at
            FROM videos
            """
        )
        conn.execute("DROP TABLE videos")
        conn.execute("ALTER TABLE videos__new RENAME TO videos")

    def _rebuild_user_meta() -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_meta__new (
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
                PRIMARY KEY(source_id, video_id),
                FOREIGN KEY(source_id, video_id) REFERENCES videos(source_id, id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO user_meta__new(
              source_id, video_id, rating, status, statuses, tags, notes,
              product_link, author_links, platform_targets, workflow_log,
              post_url, published_time, updated_at
            )
            SELECT
              COALESCE(NULLIF(TRIM(source_id), ''), 'default') AS source_id,
              video_id, rating, status, statuses, tags, notes,
              product_link, author_links, platform_targets, workflow_log,
              post_url, published_time, updated_at
            FROM user_meta
            """
        )
        conn.execute("DROP TABLE user_meta")
        conn.execute("ALTER TABLE user_meta__new RENAME TO user_meta")

    def _rebuild_video_notes() -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS video_notes__new (
                source_id TEXT NOT NULL DEFAULT 'default',
                video_id TEXT NOT NULL,
                markdown TEXT NOT NULL,
                template_version TEXT,
                updated_at TEXT,
                PRIMARY KEY(source_id, video_id),
                FOREIGN KEY(source_id, video_id) REFERENCES videos(source_id, id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO video_notes__new(source_id, video_id, markdown, template_version, updated_at)
            SELECT COALESCE(NULLIF(TRIM(source_id), ''), 'default'), video_id, markdown, template_version, updated_at
            FROM video_notes
            """
        )
        conn.execute("DROP TABLE video_notes")
        conn.execute("ALTER TABLE video_notes__new RENAME TO video_notes")

    def _rebuild_raw(table: str, id_col: str) -> None:
        tmp = f"{table}__new"
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {tmp} (
                source_id TEXT NOT NULL DEFAULT 'default',
                {id_col} TEXT NOT NULL,
                row_json TEXT NOT NULL,
                {"csv_row_hash TEXT," if table == "csv_consolidated_raw" else ""}
                imported_at TEXT,
                PRIMARY KEY(source_id, {id_col})
            )
            """
        )
        cols = "source_id, " + id_col + ", row_json, " + ("csv_row_hash, " if table == "csv_consolidated_raw" else "") + "imported_at"
        source_expr = "COALESCE(NULLIF(TRIM(source_id), ''), 'default')"
        conn.execute(
            f"""
            INSERT OR REPLACE INTO {tmp}({cols})
            SELECT {source_expr}, {id_col}, row_json, {"csv_row_hash, " if table == "csv_consolidated_raw" else ""}imported_at
            FROM {table}
            """
        )
        conn.execute(f"DROP TABLE {table}")
        conn.execute(f"ALTER TABLE {tmp} RENAME TO {table}")

    if _pk_cols("videos") != ["source_id", "id"]:
        _rebuild_videos()
    if _pk_cols("user_meta") != ["source_id", "video_id"]:
        _rebuild_user_meta()
    if _pk_cols("video_notes") != ["source_id", "video_id"]:
        _rebuild_video_notes()
    if _pk_cols("csv_consolidated_raw") != ["source_id", "video_id"]:
        _rebuild_raw("csv_consolidated_raw", "video_id")
    if _pk_cols("csv_bookmarks_raw") != ["source_id", "video_id"]:
        _rebuild_raw("csv_bookmarks_raw", "video_id")
    if _pk_cols("csv_authors_raw") != ["source_id", "author_id"]:
        _rebuild_raw("csv_authors_raw", "author_id")


def _ensure_indexes(conn: sqlite3.Connection) -> None:
    """Create indexes after migrations.

    Index creation must happen *after* `_ensure_columns()` because CREATE TABLE IF NOT EXISTS
    does not add missing columns on existing DBs, and CREATE INDEX will error if a column is missing.
    """

    def _cols(table: str) -> set[str]:
        try:
            return {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        except Exception:
            return set()

    videos_cols = _cols("videos")
    if "author_unique_id" in videos_cols:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_videos_author_unique_id ON videos(author_unique_id)"
        )
    if "source_id" in videos_cols:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_videos_source_id ON videos(source_id)"
        )
    if "bookmarked" in videos_cols:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_videos_bookmarked ON videos(bookmarked)"
        )

    meta_cols = _cols("user_meta")
    if "status" in meta_cols:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_user_meta_status ON user_meta(status)"
        )
    if "source_id" in meta_cols:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_user_meta_source_id ON user_meta(source_id)"
        )
    if "statuses" in meta_cols:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_user_meta_statuses ON user_meta(statuses)"
        )

    notes_cols = _cols("video_notes")
    if "source_id" in notes_cols:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_video_notes_source_id ON video_notes(source_id)"
        )

    raw_cols = _cols("csv_consolidated_raw")
    if "csv_row_hash" in raw_cols:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_csv_consolidated_hash ON csv_consolidated_raw(csv_row_hash)"
        )

    source_cols = _cols("sources")
    if source_cols:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sources_enabled ON sources(enabled)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sources_default ON sources(is_default)")


def get_default_source_id(conn: sqlite3.Connection, fallback: str = "default") -> str:
    row = conn.execute(
        "SELECT id FROM sources WHERE is_default=1 ORDER BY updated_at DESC, id ASC LIMIT 1"
    ).fetchone()
    if row and row[0]:
        return str(row[0])
    return str(fallback or "default")


def ensure_source(
    conn: sqlite3.Connection,
    source_id: str,
    *,
    label: str | None = None,
    kind: str | None = None,
    description: str | None = None,
    enabled: bool = True,
) -> None:
    sid = str(source_id or "").strip() or "default"
    now = datetime.utcnow().isoformat(timespec="seconds") + "Z"

    conn.execute(
        """
        INSERT INTO sources(id, label, kind, description, enabled, is_default, created_at, updated_at)
        VALUES(?, ?, ?, ?, ?, 0, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
          label=COALESCE(excluded.label, sources.label),
          kind=COALESCE(excluded.kind, sources.kind),
          description=COALESCE(excluded.description, sources.description),
          enabled=excluded.enabled,
          updated_at=excluded.updated_at
        """,
        (sid, label, kind, description, 1 if enabled else 0, now, now),
    )


def list_sources(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """
        SELECT id, label, kind, description, enabled, is_default, created_at, updated_at
        FROM sources
        ORDER BY is_default DESC, enabled DESC, id ASC
        """
    ).fetchall()
    return [dict(r) for r in rows]


def set_default_source(conn: sqlite3.Connection, source_id: str) -> None:
    sid = str(source_id or "").strip() or "default"
    now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    conn.execute("UPDATE sources SET is_default=0 WHERE is_default=1")
    conn.execute(
        """
        INSERT INTO sources(id, label, enabled, is_default, created_at, updated_at)
        VALUES(?, ?, 1, 1, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
          enabled=1,
          is_default=1,
          updated_at=excluded.updated_at
        """,
        (sid, sid, now, now),
    )


def upsert_fts(conn: sqlite3.Connection, row: dict) -> None:
    # If FTS table doesn't exist, skip.
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='videos_fts'"
    ).fetchone()
    if not cur:
        return

    conn.execute(
        "INSERT INTO videos_fts(source_id, id, caption, author_unique_id, author_name) VALUES(?, ?, ?, ?, ?)",
        (
            row.get("source_id") or "default",
            row.get("id"),
            row.get("caption") or "",
            row.get("author_unique_id") or "",
            row.get("author_name") or "",
        ),
    )


def rebuild_fts(conn: sqlite3.Connection) -> None:
    """Rebuild the FTS index from the canonical `videos` table.

    Notes:
    - `videos_fts` is created as a *contentless* FTS5 table (content=''), which
      cannot be cleared with `DELETE FROM videos_fts`.
    - The most reliable rebuild strategy is to DROP + recreate the virtual table.
    """

    has_fts = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='videos_fts'"
    ).fetchone()
    if not has_fts:
        return

    # Contentless FTS5 tables cannot be deleted from; drop and recreate.
    conn.execute("DROP TABLE IF EXISTS videos_fts")
    conn.executescript(FTS_SQL)

    rows = conn.execute(
        "SELECT source_id, id, caption, author_unique_id, author_name FROM videos"
    ).fetchall()
    for r in rows:
        upsert_fts(conn, dict(r))
    conn.commit()
