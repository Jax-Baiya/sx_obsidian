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
        SX_DB_BACKEND_MODE="SQLITE",
        SX_API_REQUIRE_EXPLICIT_SOURCE=False,
        SX_API_ENFORCE_PROFILE_SOURCE_MATCH=False,
        DATA_DIR=str(db_path.parent),
        SX_MEDIA_VAULT=str(db_path.parent),
        SX_MEDIA_DATA_DIR=str(db_path.parent),
        SX_MEDIA_STYLE="linux",
    )
    app = create_app(settings)
    return TestClient(app)


def test_sources_crud_and_default_resolution(tmp_path: Path):
    db_path = tmp_path / "sx_obsidian.db"
    conn = connect(db_path)
    init_db(conn, enable_fts=False)

    client = _mk_client(db_path)

    # Bootstrap default source exists.
    r0 = client.get("/sources")
    assert r0.status_code == 200
    d0 = r0.json()
    assert d0["default_source_id"] == "default"
    assert any(s.get("id") == "default" for s in d0.get("sources", []))

    # Create and activate a new source.
    r1 = client.post("/sources", json={"id": "alpha", "label": "Alpha", "make_default": True})
    assert r1.status_code == 200

    r2 = client.get("/sources")
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["default_source_id"] == "alpha"
    assert any(s.get("id") == "alpha" for s in d2.get("sources", []))

    # Default resolution should follow source registry when source_id is omitted.
    h = client.get("/health")
    assert h.status_code == 200
    assert h.json().get("source_id") == "alpha"

    # Deleting default source is blocked.
    bad = client.delete("/sources/alpha")
    assert bad.status_code == 400

    # Non-default empty source can be deleted.
    r3 = client.post("/sources", json={"id": "temp-src", "label": "Temp"})
    assert r3.status_code == 200
    r4 = client.delete("/sources/temp-src")
    assert r4.status_code == 200
    assert r4.json().get("ok") is True


def test_sources_delete_rejects_non_empty_source(tmp_path: Path):
    db_path = tmp_path / "sx_obsidian.db"
    conn = connect(db_path)
    init_db(conn, enable_fts=False)

    client = _mk_client(db_path)

    # Create source + one video row in that source.
    r0 = client.post("/sources", json={"id": "beta", "label": "Beta"})
    assert r0.status_code == 200

    conn2 = connect(db_path)
    init_db(conn2, enable_fts=False)
    conn2.execute(
        """
        INSERT INTO videos(source_id, id, platform, caption, bookmarked, updated_at)
        VALUES('beta', 'vid-1', 'tiktok', 'hello', 0, '2026-01-01T00:00:00Z')
        """
    )
    conn2.commit()

    bad = client.delete("/sources/beta")
    assert bad.status_code == 400


def test_pipeline_profiles_includes_sql_mode_metadata(tmp_path: Path):
    db_path = tmp_path / "sx_obsidian.db"
    env_path = tmp_path / "pipeline.env"
    env_path.write_text(
        "\n".join(
            [
                "SRC_PATH_1=/mnt/t/AlexNova/data",
                "SRC_PATH_1_LABEL=AlexNova",
                "DATABASE_PROFILE_1=assets_1",
                "SRC_PATH_1_DB_LOCAL=LOCAL_1",
                "SRC_PATH_1_DB_SESSION=SUPABASE_SESSION_1",
                "SRC_PATH_1_DB_TRANSACTION=SUPABASE_TRANSACTION_1",
                "SQL_DB_PATH_1=data/sx_obsidian_assets_1.db",
                "LOCAL_1_DB_USER=user",
                "LOCAL_1_DB_PASSWORD=pass",
                "LOCAL_1_DB_HOST=localhost",
                "LOCAL_1_DB_PORT=5432",
                "LOCAL_1_DB_NAME=db1",
                "LOCAL_1_DB_SCHEMA=pipe",
            ]
        ),
        encoding="utf-8",
    )

    settings = Settings(
        SX_DB_PATH=db_path,
        SX_DB_ENABLE_FTS=False,
        SX_API_CORS_ALLOW_ALL=False,
        SX_DEFAULT_SOURCE_ID="default",
        SX_DB_BACKEND_MODE="SQLITE",
        SX_API_REQUIRE_EXPLICIT_SOURCE=False,
        SX_API_ENFORCE_PROFILE_SOURCE_MATCH=False,
        SX_SCHEDULERX_ENV=env_path,
        SX_PROFILE_INDEX=1,
        DATA_DIR=str(tmp_path),
        SX_MEDIA_VAULT=str(tmp_path),
        SX_MEDIA_DATA_DIR=str(tmp_path),
        SX_MEDIA_STYLE="linux",
    )
    client = TestClient(create_app(settings))

    r = client.get("/pipeline/profiles")
    assert r.status_code == 200
    payload = r.json()
    assert payload.get("ok") is True
    assert isinstance(payload.get("profiles"), list)
    p1 = payload["profiles"][0]
    assert p1["db_profiles"]["sql"]["configured"] is True
    assert p1["db_profiles"]["sql"]["db_path"] == "data/sx_obsidian_assets_1.db"
    assert "SQL" in p1["available_modes"]


def test_postgres_mirror_mode_falls_back_without_url(tmp_path: Path):
    db_path = tmp_path / "sx_obsidian.db"
    settings = Settings(
        SX_DB_PATH=db_path,
        SX_DB_ENABLE_FTS=False,
        SX_API_CORS_ALLOW_ALL=False,
        SX_DEFAULT_SOURCE_ID="default",
        SX_API_REQUIRE_EXPLICIT_SOURCE=False,
        SX_API_ENFORCE_PROFILE_SOURCE_MATCH=False,
        SX_DB_BACKEND_MODE="POSTGRES_MIRROR",
        SX_PIPELINE_DB_MODE="LOCAL",
        DATA_DIR=str(tmp_path),
        SX_MEDIA_VAULT=str(tmp_path),
        SX_MEDIA_DATA_DIR=str(tmp_path),
        SX_MEDIA_STYLE="linux",
    )
    client = TestClient(create_app(settings))

    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body.get("ok") is True
    backend = body.get("backend") or {}
    assert backend.get("backend") in {"sqlite", "postgres_mirror"}
    assert isinstance(backend.get("active"), bool)
    if backend.get("backend") == "postgres_mirror":
        assert "reason" in backend


def _seed_collision_fixture(db_path: Path) -> None:
    conn = connect(db_path)
    init_db(conn, enable_fts=False)

    ensure_source(conn, "default", label="default")
    ensure_source(conn, "alpha", label="alpha")

    conn.execute(
        """
        INSERT INTO videos(source_id, id, platform, caption, bookmarked, updated_at)
        VALUES
          ('default', 'dup-1', 'tiktok', 'default-caption', 0, '2026-01-01T00:00:00Z'),
          ('alpha', 'dup-1', 'tiktok', 'alpha-caption', 1, '2026-01-02T00:00:00Z')
        """
    )

    conn.execute(
        """
        INSERT INTO user_meta(source_id, video_id, rating, status, notes, updated_at)
        VALUES
          ('default', 'dup-1', 2, 'raw', 'default-meta', '2026-01-03T00:00:00Z'),
          ('alpha', 'dup-1', 5, 'reviewed', 'alpha-meta', '2026-01-04T00:00:00Z')
        """
    )

    conn.execute(
        """
        INSERT INTO video_notes(source_id, video_id, markdown, template_version, updated_at)
        VALUES
          ('default', 'dup-1', '# default-note', 'v1', '2026-01-05T00:00:00Z'),
          ('alpha', 'dup-1', '# alpha-note', 'v1', '2026-01-06T00:00:00Z')
        """
    )
    conn.commit()


def test_items_and_item_lookup_are_isolated_by_source(tmp_path: Path):
    db_path = tmp_path / "sx_obsidian.db"
    _seed_collision_fixture(db_path)
    client = _mk_client(db_path)

    r_default = client.get("/items", params={"source_id": "default"})
    assert r_default.status_code == 200
    items_default = r_default.json().get("items", [])
    assert len(items_default) == 1
    assert items_default[0]["id"] == "dup-1"
    assert items_default[0]["caption"] == "default-caption"
    assert items_default[0]["bookmarked"] == 0

    r_alpha = client.get("/items", headers={"X-SX-Source-ID": "alpha"})
    assert r_alpha.status_code == 200
    items_alpha = r_alpha.json().get("items", [])
    assert len(items_alpha) == 1
    assert items_alpha[0]["id"] == "dup-1"
    assert items_alpha[0]["caption"] == "alpha-caption"
    assert items_alpha[0]["bookmarked"] == 1

    i_default = client.get("/items/dup-1", params={"source_id": "default"})
    assert i_default.status_code == 200
    assert i_default.json()["item"]["caption"] == "default-caption"

    i_alpha = client.get("/items/dup-1", headers={"X-SX-Source-ID": "alpha"})
    assert i_alpha.status_code == 200
    assert i_alpha.json()["item"]["caption"] == "alpha-caption"


def test_meta_and_note_endpoints_are_isolated_by_source(tmp_path: Path):
    db_path = tmp_path / "sx_obsidian.db"
    _seed_collision_fixture(db_path)
    client = _mk_client(db_path)

    m_default = client.get("/items/dup-1/meta", params={"source_id": "default"})
    assert m_default.status_code == 200
    assert m_default.json()["meta"]["rating"] == 2
    assert m_default.json()["meta"]["status"] == "raw"
    assert m_default.json()["meta"]["notes"] == "default-meta"

    m_alpha = client.get("/items/dup-1/meta", headers={"X-SX-Source-ID": "alpha"})
    assert m_alpha.status_code == 200
    assert m_alpha.json()["meta"]["rating"] == 5
    assert m_alpha.json()["meta"]["status"] == "reviewed"
    assert m_alpha.json()["meta"]["notes"] == "alpha-meta"

    n_default = client.get("/items/dup-1/note", params={"source_id": "default"})
    assert n_default.status_code == 200
    md_default = str(n_default.json().get("markdown") or "")
    assert md_default
    assert "default-note" in md_default or "dup-1" in md_default

    n_alpha = client.get("/items/dup-1/note", headers={"X-SX-Source-ID": "alpha"})
    assert n_alpha.status_code == 200
    md_alpha = str(n_alpha.json().get("markdown") or "")
    assert md_alpha
    assert "alpha-note" in md_alpha or "dup-1" in md_alpha

    upd_alpha = client.put(
        "/items/dup-1/meta",
        headers={"X-SX-Source-ID": "alpha"},
        json={"rating": 4, "status": "reviewing", "notes": "alpha-updated"},
    )
    assert upd_alpha.status_code == 200
    assert upd_alpha.json()["meta"]["rating"] == 4
    assert upd_alpha.json()["meta"]["status"] == "reviewing"

    m_alpha_after = client.get("/items/dup-1/meta", headers={"X-SX-Source-ID": "alpha"})
    assert m_alpha_after.status_code == 200
    assert m_alpha_after.json()["meta"]["rating"] == 4
    assert m_alpha_after.json()["meta"]["notes"] == "alpha-updated"

    m_default_after = client.get("/items/dup-1/meta", params={"source_id": "default"})
    assert m_default_after.status_code == 200
    assert m_default_after.json()["meta"]["rating"] == 2
    assert m_default_after.json()["meta"]["status"] == "raw"
    assert m_default_after.json()["meta"]["notes"] == "default-meta"


def test_authors_endpoint_returns_grouped_counts(tmp_path: Path):
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
        body = r.json()
        assert body["total"] == 2
        assert len(body["authors"]) == 2
        first = body["authors"][0]
        assert first["author_unique_id"] == "author_one"
        assert int(first["items_count"]) == 2
        assert int(first["bookmarked_count"]) == 1
