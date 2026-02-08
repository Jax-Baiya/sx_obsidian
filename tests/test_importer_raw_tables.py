from __future__ import annotations

import csv
import json

from sx_db.db import connect, init_db
from sx_db.importer import import_all


def _write_csv(path, fieldnames, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def test_importer_persists_raw_rows(tmp_path):
    db_path = tmp_path / "sx.db"
    conn = connect(db_path)
    init_db(conn, enable_fts=False)

    consolidated = tmp_path / "consolidated.csv"
    authors = tmp_path / "authors.csv"
    bookmarks = tmp_path / "bookmarks.csv"

    vid = "123"
    aid = "999"

    _write_csv(
        consolidated,
        fieldnames=["c_videos_id", "c_videos_authorid", "c_texts_text_content", "csv_row_hash", "extra_col"],
        rows=[
            {
                "c_videos_id": vid,
                "c_videos_authorid": aid,
                "c_texts_text_content": "hello",
                "csv_row_hash": "h1",
                "extra_col": "EXTRA",
            }
        ],
    )

    _write_csv(
        authors,
        fieldnames=["authors_id", "authors_uniqueids", "authors_nicknames", "authors_followercount", "weird"],
        rows=[
            {
                "authors_id": aid,
                "authors_uniqueids": "someone",
                "authors_nicknames": "Some One",
                "authors_followercount": "42",
                "weird": "x",
            }
        ],
    )

    _write_csv(
        bookmarks,
        fieldnames=["bookmarks_bookmark_id", "bookmarks_timestamp", "other"],
        rows=[
            {
                "bookmarks_bookmark_id": vid,
                "bookmarks_timestamp": "2026-01-01T00:00:00Z",
                "other": "y",
            }
        ],
    )

    stats = import_all(conn, str(consolidated), str(authors), str(bookmarks))
    assert stats.inserted + stats.updated >= 1

    r0 = conn.execute(
        "SELECT video_id, row_json, csv_row_hash FROM csv_consolidated_raw WHERE video_id=?",
        (vid,),
    ).fetchone()
    assert r0 is not None
    assert r0[0] == vid
    assert r0[2] == "h1"
    consolidated_obj = json.loads(r0[1])
    assert consolidated_obj["extra_col"] == "EXTRA"

    r1 = conn.execute(
        "SELECT author_id, row_json FROM csv_authors_raw WHERE author_id=?",
        (aid,),
    ).fetchone()
    assert r1 is not None
    author_obj = json.loads(r1[1])
    assert author_obj["weird"] == "x"

    r2 = conn.execute(
        "SELECT video_id, row_json FROM csv_bookmarks_raw WHERE video_id=?",
        (vid,),
    ).fetchone()
    assert r2 is not None
    bm_obj = json.loads(r2[1])
    assert bm_obj["other"] == "y"
