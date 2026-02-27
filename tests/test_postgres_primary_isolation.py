from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sx_db.api import create_app
from sx_db.repositories import PostgresRepository, safe_ident
from sx_db.settings import Settings


def test_safe_ident_rejects_injection() -> None:
    with pytest.raises(ValueError):
        safe_ident("sx_bad;DROP SCHEMA public")
    with pytest.raises(ValueError):
        safe_ident("sx.bad")
    assert safe_ident("sx_assets_1") == "sx_assets_1"


def test_postgres_primary_missing_schema_mapping_returns_400(tmp_path: Path) -> None:
    settings = Settings(
        SX_DB_PATH=tmp_path / "sx_obsidian.db",
        SX_DB_ENABLE_FTS=False,
        SX_API_CORS_ALLOW_ALL=False,
        SX_DEFAULT_SOURCE_ID="default",
        SX_DB_BACKEND_MODE="POSTGRES_PRIMARY",
        # No DSN on purpose: should not silently fallback.
        SX_POSTGRES_DSN=None,
        DATA_DIR=str(tmp_path),
        SX_MEDIA_VAULT=str(tmp_path),
        SX_MEDIA_DATA_DIR=str(tmp_path),
        SX_MEDIA_STYLE="linux",
    )

    client = TestClient(create_app(settings))
    r = client.get("/health", params={"source_id": "assets_1"})
    assert r.status_code == 400
    body = r.json()
    assert body.get("ok") is False
    assert "Source schema mapping missing/invalid" in str(body.get("detail") or "")


@pytest.mark.skipif(
    not os.getenv("SX_POSTGRES_TEST_DSN"),
    reason="Set SX_POSTGRES_TEST_DSN to run PostgreSQL primary integration tests",
)
def test_cross_schema_id_collision_isolated_postgres_primary(tmp_path: Path) -> None:
    dsn = os.environ["SX_POSTGRES_TEST_DSN"]
    settings = Settings(
        SX_DB_PATH=tmp_path / "sx_obsidian.db",
        SX_DB_ENABLE_FTS=False,
        SX_API_CORS_ALLOW_ALL=False,
        SX_DEFAULT_SOURCE_ID="assets_1",
        SX_DB_BACKEND_MODE="POSTGRES_PRIMARY",
        SX_POSTGRES_DSN=dsn,
        SX_POSTGRES_SCHEMA_PREFIX="sx_test",
        DATA_DIR=str(tmp_path),
        SX_MEDIA_VAULT=str(tmp_path),
        SX_MEDIA_DATA_DIR=str(tmp_path),
        SX_MEDIA_STYLE="linux",
    )
    repo = PostgresRepository(settings)
    repo.init_schema("assets_1")
    repo.init_schema("assets_2")

    repo.write_item("assets_1", {"id": "dup-id", "caption": "from-assets-1", "bookmarked": 0})
    repo.write_item("assets_2", {"id": "dup-id", "caption": "from-assets-2", "bookmarked": 1})

    i1 = repo.get_item("assets_1", "dup-id")
    i2 = repo.get_item("assets_2", "dup-id")
    assert i1 is not None and i1.get("caption") == "from-assets-1"
    assert i2 is not None and i2.get("caption") == "from-assets-2"


@pytest.mark.skipif(
    not os.getenv("SX_POSTGRES_TEST_DSN"),
    reason="Set SX_POSTGRES_TEST_DSN to run PostgreSQL primary integration tests",
)
def test_concurrent_profile_requests_isolated(tmp_path: Path) -> None:
    dsn = os.environ["SX_POSTGRES_TEST_DSN"]
    settings = Settings(
        SX_DB_PATH=tmp_path / "sx_obsidian.db",
        SX_DB_ENABLE_FTS=False,
        SX_API_CORS_ALLOW_ALL=False,
        SX_DEFAULT_SOURCE_ID="assets_1",
        SX_DB_BACKEND_MODE="POSTGRES_PRIMARY",
        SX_POSTGRES_DSN=dsn,
        SX_POSTGRES_SCHEMA_PREFIX="sx_test",
        DATA_DIR=str(tmp_path),
        SX_MEDIA_VAULT=str(tmp_path),
        SX_MEDIA_DATA_DIR=str(tmp_path),
        SX_MEDIA_STYLE="linux",
    )
    app = create_app(settings)
    client = TestClient(app)

    # Bootstrap schemas via API endpoint.
    assert client.post("/admin/bootstrap/schema", json={"source_id": "assets_1"}).status_code == 200
    assert client.post("/admin/bootstrap/schema", json={"source_id": "assets_2"}).status_code == 200

    # Seed same id in both sources via normal API path.
    c1 = PostgresRepository(settings)
    c1.write_item("assets_1", {"id": "concurrent-id", "caption": "A1"})
    c1.write_item("assets_2", {"id": "concurrent-id", "caption": "A2"})

    def fetch(source_id: str) -> str:
        r = client.get(f"/items/concurrent-id", headers={"X-SX-Source-ID": source_id})
        assert r.status_code == 200
        return str(r.json()["item"]["caption"])

    with ThreadPoolExecutor(max_workers=2) as ex:
        a, b = ex.map(fetch, ["assets_1", "assets_2"])

    assert a == "A1"
    assert b == "A2"


@pytest.mark.skipif(
    not os.getenv("SX_POSTGRES_TEST_DSN"),
    reason="Set SX_POSTGRES_TEST_DSN to run PostgreSQL primary integration tests",
)
def test_wrong_schema_injection_rejected(tmp_path: Path) -> None:
    dsn = os.environ["SX_POSTGRES_TEST_DSN"]
    settings = Settings(
        SX_DB_PATH=tmp_path / "sx_obsidian.db",
        SX_DB_ENABLE_FTS=False,
        SX_API_CORS_ALLOW_ALL=False,
        SX_DEFAULT_SOURCE_ID="assets_1",
        SX_DB_BACKEND_MODE="POSTGRES_PRIMARY",
        SX_POSTGRES_DSN=dsn,
        SX_POSTGRES_SCHEMA_PREFIX="sx_test",
        DATA_DIR=str(tmp_path),
        SX_MEDIA_VAULT=str(tmp_path),
        SX_MEDIA_DATA_DIR=str(tmp_path),
        SX_MEDIA_STYLE="linux",
    )

    repo = PostgresRepository(settings)
    with pytest.raises(ValueError):
        # strict identifier validator should reject SQL injection payloads
        repo.schema_name_for_source("assets_1;DROP_SCHEMA")


@pytest.mark.skipif(
    not os.getenv("SX_POSTGRES_TEST_DSN"),
    reason="Set SX_POSTGRES_TEST_DSN to run PostgreSQL primary integration tests",
)
def test_postgres_schema_parity_constraints_and_indexes(tmp_path: Path) -> None:
    dsn = os.environ["SX_POSTGRES_TEST_DSN"]
    settings = Settings(
        SX_DB_PATH=tmp_path / "sx_obsidian.db",
        SX_DB_ENABLE_FTS=False,
        SX_API_CORS_ALLOW_ALL=False,
        SX_DEFAULT_SOURCE_ID="assets_1",
        SX_DB_BACKEND_MODE="POSTGRES_PRIMARY",
        SX_POSTGRES_DSN=dsn,
        SX_POSTGRES_SCHEMA_PREFIX="sx_test",
        DATA_DIR=str(tmp_path),
        SX_MEDIA_VAULT=str(tmp_path),
        SX_MEDIA_DATA_DIR=str(tmp_path),
        SX_MEDIA_STYLE="linux",
    )

    repo = PostgresRepository(settings)
    out = repo.init_schema("assets_1")
    schema = str(out["schema"])

    with repo._connect() as conn:  # noqa: SLF001 - integration assertion of internal bootstrap side effects
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT conname
                FROM pg_constraint c
                JOIN pg_namespace n ON n.oid = c.connamespace
                WHERE n.nspname=%s AND conname IN ('fk_user_meta_videos', 'fk_video_notes_videos')
                ORDER BY conname
                """,
                (schema,),
            )
            constraints = [str(r["conname"]) for r in (cur.fetchall() or [])]

            cur.execute(
                """
                SELECT indexname
                FROM pg_indexes
                WHERE schemaname=%s
                  AND indexname IN (
                      %s, %s, %s,
                      %s, %s, %s,
                      %s, %s
                  )
                ORDER BY indexname
                """,
                (
                    schema,
                    f"idx_{schema}_videos_bookmarked",
                    f"idx_{schema}_videos_updated",
                    f"idx_{schema}_videos_author_uid",
                    f"idx_{schema}_user_meta_status",
                    f"idx_{schema}_user_meta_source_id",
                    f"idx_{schema}_user_meta_statuses",
                    f"idx_{schema}_video_notes_source_id",
                    f"idx_{schema}_csv_consolidated_hash",
                ),
            )
            indexes = {str(r["indexname"]) for r in (cur.fetchall() or [])}

    assert constraints == ["fk_user_meta_videos", "fk_video_notes_videos"]
    assert f"idx_{schema}_videos_bookmarked" in indexes
    assert f"idx_{schema}_videos_updated" in indexes
    assert f"idx_{schema}_videos_author_uid" in indexes
    assert f"idx_{schema}_user_meta_status" in indexes
    assert f"idx_{schema}_user_meta_source_id" in indexes
    assert f"idx_{schema}_user_meta_statuses" in indexes
    assert f"idx_{schema}_video_notes_source_id" in indexes
    assert f"idx_{schema}_csv_consolidated_hash" in indexes
