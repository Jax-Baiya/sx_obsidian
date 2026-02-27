from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from sx_db.api import create_app
from sx_db.db import connect, ensure_source, init_db
from sx_db.settings import Settings


def _mk_client(db_path: Path) -> TestClient:
    settings = Settings(
        SX_DB_PATH=db_path,
        SX_DB_ENABLE_FTS=False,
        SX_API_CORS_ALLOW_ALL=False,
        SX_DEFAULT_SOURCE_ID="default",
        SX_API_REQUIRE_EXPLICIT_SOURCE=False,
        SX_API_ENFORCE_PROFILE_SOURCE_MATCH=False,
        SX_DB_BACKEND_MODE="SQLITE",
        DATA_DIR=str(db_path.parent),
        SX_MEDIA_VAULT=str(db_path.parent),
        SX_MEDIA_DATA_DIR=str(db_path.parent),
        SX_MEDIA_STYLE="linux",
    )
    return TestClient(create_app(settings))


def test_authors_total_and_counts(tmp_path: Path) -> None:
    db_path = tmp_path / "sx_obsidian.db"
    conn = connect(db_path)
    init_db(conn, enable_fts=False)
    ensure_source(conn, "default", label="default")
    conn.execute(
        """
        INSERT INTO videos(source_id, id, author_id, author_unique_id, author_name, caption, bookmarked, updated_at)
        VALUES
          ('default', 'v1', 'a1', 'author_one', 'Author One', 'x', 1, '2026-01-01T00:00:00Z'),
          ('default', 'v2', 'a1', 'author_one', 'Author One', 'y', 0, '2026-01-01T00:00:01Z'),
          ('default', 'v3', 'a2', 'author_two', 'Author Two', 'z', 1, '2026-01-01T00:00:02Z')
        """
    )
    conn.commit()

    client = _mk_client(db_path)
    r = client.get("/authors", params={"source_id": "default", "order": "count", "limit": 10, "offset": 0})

    assert r.status_code == 200
    payload = r.json()
    assert payload["total"] == 2
    assert len(payload["authors"]) == 2

    first = payload["authors"][0]
    assert first["author_unique_id"] == "author_one"
    assert int(first["items_count"]) == 2
    assert int(first["bookmarked_count"]) == 1
