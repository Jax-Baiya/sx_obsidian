from __future__ import annotations

import sqlite3
from pathlib import Path


SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA temp_store=MEMORY;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS videos (
  id TEXT PRIMARY KEY,
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
  updated_at TEXT
);

-- User-editable metadata (owned by the user; never overwritten by CSV imports)
CREATE TABLE IF NOT EXISTS user_meta (
    video_id TEXT PRIMARY KEY,
    rating INTEGER,
    status TEXT,
    statuses TEXT,
    tags TEXT,
    notes TEXT,
    product_link TEXT,
    platform_targets TEXT,
    workflow_log TEXT,
    post_url TEXT,
    published_time TEXT,
    updated_at TEXT,
    FOREIGN KEY(video_id) REFERENCES videos(id) ON DELETE CASCADE
);

-- Cached/persisted markdown notes (rendered from template; used for fast sync into vault)
CREATE TABLE IF NOT EXISTS video_notes (
    video_id TEXT PRIMARY KEY,
    markdown TEXT NOT NULL,
    template_version TEXT,
    updated_at TEXT,
    FOREIGN KEY(video_id) REFERENCES videos(id) ON DELETE CASCADE
);

-- Raw CSV row retention (full-fidelity source data)
-- These tables intentionally store the full CSV DictReader row as JSON so we can
-- evolve mappings over time without needing to constantly migrate the main schema.
CREATE TABLE IF NOT EXISTS csv_consolidated_raw (
    video_id TEXT PRIMARY KEY,
    row_json TEXT NOT NULL,
    csv_row_hash TEXT,
    imported_at TEXT
);

CREATE TABLE IF NOT EXISTS csv_authors_raw (
    author_id TEXT PRIMARY KEY,
    row_json TEXT NOT NULL,
    imported_at TEXT
);

CREATE TABLE IF NOT EXISTS csv_bookmarks_raw (
    video_id TEXT PRIMARY KEY,
    row_json TEXT NOT NULL,
    imported_at TEXT
);
"""

FTS_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS videos_fts USING fts5(
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

    videos_cols = _cols("videos")

    to_add: list[tuple[str, str]] = [
        ("followers", "INTEGER"),
        ("hearts", "INTEGER"),
        ("videos_count", "INTEGER"),
        ("signature", "TEXT"),
        ("is_private", "INTEGER"),
    ]

    for name, decl in to_add:
        if name in videos_cols:
            continue
        conn.execute(f"ALTER TABLE videos ADD COLUMN {name} {decl}")

    # user_meta additive columns (user-owned workflow fields)
    meta_cols = _cols("user_meta")
    meta_to_add: list[tuple[str, str]] = [
        # Core user_meta columns (some very old DBs may not have them)
        ("rating", "INTEGER"),
        ("status", "TEXT"),
        ("tags", "TEXT"),
        ("notes", "TEXT"),
        ("statuses", "TEXT"),
        ("product_link", "TEXT"),
        ("platform_targets", "TEXT"),
        ("workflow_log", "TEXT"),
        ("post_url", "TEXT"),
        ("published_time", "TEXT"),
    ]
    for name, decl in meta_to_add:
        if name in meta_cols:
            continue
        conn.execute(f"ALTER TABLE user_meta ADD COLUMN {name} {decl}")


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
    if "bookmarked" in videos_cols:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_videos_bookmarked ON videos(bookmarked)"
        )

    meta_cols = _cols("user_meta")
    if "status" in meta_cols:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_user_meta_status ON user_meta(status)"
        )
    if "statuses" in meta_cols:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_user_meta_statuses ON user_meta(statuses)"
        )

    raw_cols = _cols("csv_consolidated_raw")
    if "csv_row_hash" in raw_cols:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_csv_consolidated_hash ON csv_consolidated_raw(csv_row_hash)"
        )


def upsert_fts(conn: sqlite3.Connection, row: dict) -> None:
    # If FTS table doesn't exist, skip.
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='videos_fts'"
    ).fetchone()
    if not cur:
        return

    conn.execute(
        "INSERT INTO videos_fts(id, caption, author_unique_id, author_name) VALUES(?, ?, ?, ?)",
        (
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
        "SELECT id, caption, author_unique_id, author_name FROM videos"
    ).fetchall()
    for r in rows:
        upsert_fts(conn, dict(r))
    conn.commit()
