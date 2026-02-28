from __future__ import annotations

import sqlite3


def search(
    conn: sqlite3.Connection,
    q: str,
    *,
    limit: int = 50,
    offset: int = 0,
    source_id: str = "default",
) -> list[dict]:
    q = (q or "").strip()
    if not q:
        rows = conn.execute(
            "SELECT id, author_unique_id, author_name, substr(caption, 1, 160) AS snippet, bookmarked "
            "FROM videos WHERE source_id=? ORDER BY bookmarked DESC, updated_at DESC LIMIT ? OFFSET ?",
            (source_id, limit, offset),
        ).fetchall()
        return [dict(r) for r in rows]

    # FTS path if present
    has_fts = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='videos_fts'"
    ).fetchone()

    if has_fts:
        try:
            rows = conn.execute(
                """
                SELECT v.id, v.author_unique_id, v.author_name,
                       substr(v.caption, 1, 160) AS snippet,
                       v.bookmarked,
                       bm25(videos_fts) AS score
                FROM videos_fts
                JOIN videos v ON v.id = videos_fts.id AND v.source_id = videos_fts.source_id
                WHERE videos_fts MATCH ? AND v.source_id=?
                ORDER BY score
                LIMIT ? OFFSET ?
                """,
                (q, source_id, limit, offset),
            ).fetchall()
            if rows:
                return [dict(r) for r in rows]
        except sqlite3.OperationalError:
            # If the user types something that isn't valid FTS syntax, fallback.
            pass

    # Fallback LIKE (substring match; slower but user-friendly)
    like = f"%{q}%"
    rows = conn.execute(
        """
        SELECT id, author_unique_id, author_name, substr(caption, 1, 160) AS snippet, bookmarked
        FROM videos
        WHERE source_id=? AND (caption LIKE ? OR author_unique_id LIKE ? OR author_name LIKE ? OR id LIKE ?)
        ORDER BY bookmarked DESC, updated_at DESC
        LIMIT ? OFFSET ?
        """,
        (source_id, like, like, like, like, limit, offset),
    ).fetchall()
    return [dict(r) for r in rows]
