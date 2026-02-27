from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class ImportStats:
    inserted: int = 0
    updated: int = 0
    skipped: int = 0


def _read_csv(path: str) -> list[dict]:
    with open(path, "r", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


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


def import_all(
    conn,
    consolidated_csv: str,
    authors_csv: str | None,
    bookmarks_csv: str | None,
    *,
    source_id: str = "default",
) -> ImportStats:
    # Build author lookup
    authors_by_id: dict[str, dict] = {}
    if authors_csv:
        for row in _read_csv(authors_csv):
            aid = row.get("authors_id")
            if aid:
                authors_by_id[aid] = row

        # Store full-fidelity author rows
        conn.executemany(
            """
                        INSERT INTO csv_authors_raw(source_id, author_id, row_json, imported_at)
                        VALUES(?, ?, ?, ?)
                        ON CONFLICT(source_id, author_id) DO UPDATE SET
              row_json=excluded.row_json,
              imported_at=excluded.imported_at
            """,
            [
                (
                                        source_id,
                    str(r.get("authors_id")),
                    json.dumps(r, ensure_ascii=False),
                    datetime.utcnow().isoformat(timespec="seconds") + "Z",
                )
                for r in authors_by_id.values()
                if r.get("authors_id")
            ],
        )

    bookmarked: dict[str, dict] = {}
    if bookmarks_csv:
        for row in _read_csv(bookmarks_csv):
            bid = row.get("bookmarks_bookmark_id")
            if bid:
                bookmarked[bid] = row

        # Store full-fidelity bookmark rows
        conn.executemany(
            """
                        INSERT INTO csv_bookmarks_raw(source_id, video_id, row_json, imported_at)
                        VALUES(?, ?, ?, ?)
                        ON CONFLICT(source_id, video_id) DO UPDATE SET
              row_json=excluded.row_json,
              imported_at=excluded.imported_at
            """,
            [
                (
                                        source_id,
                    str(r.get("bookmarks_bookmark_id")),
                    json.dumps(r, ensure_ascii=False),
                    datetime.utcnow().isoformat(timespec="seconds") + "Z",
                )
                for r in bookmarked.values()
                if r.get("bookmarks_bookmark_id")
            ],
        )

    rows = _read_csv(consolidated_csv)
    stats = ImportStats()

    now = datetime.utcnow().isoformat(timespec="seconds") + "Z"

    for row in rows:
        vid = row.get("c_videos_id")
        if not vid:
            stats.skipped += 1
            continue

        # Store full-fidelity consolidated row.
        # Note: consolidated exports can sometimes contain duplicates; last write wins.
        conn.execute(
            """
                        INSERT INTO csv_consolidated_raw(source_id, video_id, row_json, csv_row_hash, imported_at)
                        VALUES(?, ?, ?, ?, ?)
                        ON CONFLICT(source_id, video_id) DO UPDATE SET
              row_json=excluded.row_json,
              csv_row_hash=excluded.csv_row_hash,
              imported_at=excluded.imported_at
            """,
            (
                                source_id,
                str(vid),
                json.dumps(row, ensure_ascii=False),
                row.get("csv_row_hash") or row.get("source.csv_row_hash") or "",
                now,
            ),
        )

        author_id = row.get("c_videos_authorid")
        author_info = authors_by_id.get(author_id) or {}
        author_uid = author_info.get("authors_uniqueids") or row.get("c_authors_uniqueids")
        author_name = author_info.get("authors_nicknames") or row.get("c_authors_nicknames")

        followers = _to_int(author_info.get("authors_followercount"))
        hearts = _to_int(author_info.get("authors_heartcount"))
        videos_count = _to_int(author_info.get("authors_videocount"))
        signature = (author_info.get("authors_signature") or "").strip() or None
        is_private = author_info.get("authors_privateaccount")
        if is_private is None or str(is_private).strip() == "":
            is_private_int = None
        else:
            is_private_int = 1 if str(is_private).strip().lower() in ("1", "true", "yes", "y") else 0

        bm = bookmarked.get(vid) or {}
        is_bookmarked = 1 if vid in bookmarked else 0

        # Upsert
        # NOTE: `csv_row_hash` comes from the consolidated export, but some important fields
        # (bookmarks + author stats) come from joined CSVs and can change independently.
        existing = conn.execute(
            """
            SELECT
              id,
              csv_row_hash,
              bookmarked,
              bookmark_timestamp,
              followers,
              hearts,
              videos_count,
              signature,
              is_private
            FROM videos
            WHERE source_id=? AND id=?
            """,
            (source_id, vid),
        ).fetchone()
        csv_row_hash = row.get("csv_row_hash") or row.get("source.csv_row_hash") or ""

        # minimal stable hash fallback
        if not csv_row_hash:
            csv_row_hash = str(hash(frozenset(row.items())))

        payload = {
            "source_id": source_id,
            "id": str(vid),
            "platform": row.get("platform") or "TikTok",
            "author_id": author_id,
            "author_unique_id": author_uid,
            "author_name": author_name,
            "followers": followers,
            "hearts": hearts,
            "videos_count": videos_count,
            "signature": signature,
            "is_private": is_private_int,
            "caption": row.get("c_texts_text_content") or row.get("text") or "",
            "bookmarked": is_bookmarked,
            "bookmark_timestamp": bm.get("bookmarks_timestamp"),
            "video_path": row.get("video_path") or row.get("media.video") or None,
            "cover_path": row.get("cover_path") or row.get("media.cover") or None,
            "csv_row_hash": csv_row_hash,
            "updated_at": now,
        }

        # Canonical fallback when upstream export doesn't include explicit media columns.
        if not payload["video_path"] or not payload["cover_path"]:
            base = "Favorites" if is_bookmarked else (f"Following/{author_id}" if author_id else "Following")
            if not payload["video_path"]:
                payload["video_path"] = f"{base}/videos/{vid}.mp4"
            if not payload["cover_path"]:
                payload["cover_path"] = f"{base}/covers/{vid}.jpg"

        if existing and existing["csv_row_hash"] == csv_row_hash:
            # If the consolidated row hash matches, only skip when all join-sourced fields
            # we care about also match.
            unchanged = (
                int(existing["bookmarked"] or 0) == int(is_bookmarked)
                and (existing["bookmark_timestamp"] or None) == (bm.get("bookmarks_timestamp") or None)
                and (existing["followers"] if existing["followers"] is not None else None) == followers
                and (existing["hearts"] if existing["hearts"] is not None else None) == hearts
                and (existing["videos_count"] if existing["videos_count"] is not None else None)
                == videos_count
                and (existing["signature"] or None) == signature
                and (existing["is_private"] if existing["is_private"] is not None else None)
                == is_private_int
            )
            if unchanged:
                stats.skipped += 1
                continue
        # Idempotent write strategy:
        # - Existing row: explicit UPDATE only when changed
        # - Missing row: INSERT with ON CONFLICT DO NOTHING (safe for duplicate inputs/races)
        if existing:
            conn.execute(
                """
                UPDATE videos
                SET
                  platform=:platform,
                  author_id=:author_id,
                  author_unique_id=:author_unique_id,
                  author_name=:author_name,
                  followers=:followers,
                  hearts=:hearts,
                  videos_count=:videos_count,
                  signature=:signature,
                  is_private=:is_private,
                  caption=:caption,
                  bookmarked=:bookmarked,
                  bookmark_timestamp=:bookmark_timestamp,
                  video_path=:video_path,
                  cover_path=:cover_path,
                  csv_row_hash=:csv_row_hash,
                  updated_at=:updated_at
                WHERE source_id=:source_id AND id=:id
                """,
                payload,
            )
            stats.updated += 1
        else:
            conn.execute(
                """
                INSERT INTO videos(
                  source_id, id, platform, author_id, author_unique_id, author_name,
                  followers, hearts, videos_count, signature, is_private,
                  caption,
                  bookmarked, bookmark_timestamp, video_path, cover_path, csv_row_hash, updated_at
                ) VALUES(
                  :source_id, :id, :platform, :author_id, :author_unique_id, :author_name,
                  :followers, :hearts, :videos_count, :signature, :is_private,
                  :caption,
                  :bookmarked, :bookmark_timestamp, :video_path, :cover_path, :csv_row_hash, :updated_at
                )
                ON CONFLICT(source_id, id) DO NOTHING
                """,
                payload,
            )
            # Rowcount is not reliable across sqlite/psycopg adapters for INSERT.
            # We treat the first-seen path as inserted; duplicate rows in the same
            # import pass will be handled by the `existing` branch on subsequent loops.
            stats.inserted += 1

    conn.commit()
    return stats
