from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from sx_db.api import create_app
from sx_db.db import connect, ensure_source, init_db
from sx_db.settings import Settings


def _mk_client(db_path: Path, scheduler_env: Path) -> TestClient:
    settings = Settings(
        SX_DB_PATH=db_path,
        SX_DB_ENABLE_FTS=False,
        SX_API_CORS_ALLOW_ALL=False,
        SX_DEFAULT_SOURCE_ID="default",
        SX_DB_BACKEND_MODE="SQLITE",
        SX_SCHEDULERX_ENV=scheduler_env,
        PATH_STYLE="linux",
        DATA_DIR="data",
        SX_MEDIA_STYLE="linux",
    )
    return TestClient(create_app(settings))


def _seed_video(
    db_path: Path,
    source_id: str,
    item_id: str,
    *,
    video_path: str = "Favorites/videos/vid-1.mp4",
    cover_path: str = "Favorites/covers/vid-1.jpg",
) -> None:
    conn = connect(db_path)
    init_db(conn, enable_fts=False)
    ensure_source(conn, source_id, label=source_id)
    conn.execute(
        """
        INSERT INTO videos(source_id, id, platform, caption, bookmarked, video_path, cover_path, updated_at)
        VALUES(?, ?, 'tiktok', 'hello', 1, ?, ?, '2026-01-01T00:00:00Z')
        """,
        (source_id, item_id, video_path, cover_path),
    )
    conn.commit()


def test_item_links_use_src_path_root_when_vault_differs(tmp_path: Path) -> None:
    db_path = tmp_path / "sx_obsidian.db"
    env_path = tmp_path / "pipeline.env"

    src_root = tmp_path / "source_root"
    vault_root = tmp_path / "vault_root"
    src_root.mkdir(parents=True)
    vault_root.mkdir(parents=True)

    env_path.write_text(
        "\n".join(
            [
                f"SRC_PATH_1={src_root}",
                f"VAULT_1={vault_root}",
                "SRC_PROFILE_1_ID=assets_1",
            ]
        ),
        encoding="utf-8",
    )

    _seed_video(db_path, "assets_1", "vid-1")
    client = _mk_client(db_path, env_path)

    r = client.get("/items/vid-1/links", params={"source_id": "assets_1"})
    assert r.status_code == 200
    links = r.json()
    assert links["video_abs"].startswith(str(src_root / "data"))
    assert links["sxopen_video"].startswith(f"sxopen:{src_root}/data/")


def test_note_uses_group_embed_when_src_and_vault_split(tmp_path: Path) -> None:
    db_path = tmp_path / "sx_obsidian.db"
    env_path = tmp_path / "pipeline.env"

    src_root = tmp_path / "source_root"
    vault_root = tmp_path / "vault_root"
    src_root.mkdir(parents=True)
    vault_root.mkdir(parents=True)

    env_path.write_text(
        "\n".join(
            [
                f"SRC_PATH_1={src_root}",
                f"VAULT_1={vault_root}",
                "SRC_PROFILE_1_ID=assets_1",
            ]
        ),
        encoding="utf-8",
    )

    _seed_video(db_path, "assets_1", "vid-1")
    client = _mk_client(db_path, env_path)

    r = client.get("/items/vid-1/note", params={"source_id": "assets_1", "force": True})
    assert r.status_code == 200
    md = r.json()["markdown"]
    assert "video: '[[group:assets_1/Favorites/videos/vid-1.mp4]]'" in md
    assert "cover: '[[group:assets_1/Favorites/covers/vid-1.jpg]]'" in md
    assert "![[group:assets_1/Favorites/covers/vid-1.jpg]]" in md
    assert "![[group:assets_1/Favorites/videos/vid-1.mp4]]" in md


def test_stale_cached_note_is_auto_regenerated(tmp_path: Path) -> None:
    db_path = tmp_path / "sx_obsidian.db"
    env_path = tmp_path / "pipeline.env"

    src_root = tmp_path / "source_root"
    vault_root = tmp_path / "vault_root"
    src_root.mkdir(parents=True)
    vault_root.mkdir(parents=True)

    env_path.write_text(
        "\n".join(
            [
                f"SRC_PATH_1={src_root}",
                f"VAULT_1={vault_root}",
                "SRC_PROFILE_1_ID=assets_1",
            ]
        ),
        encoding="utf-8",
    )

    _seed_video(db_path, "assets_1", "vid-1")
    conn = connect(db_path)
    init_db(conn, enable_fts=False)
    conn.execute(
        """
        INSERT INTO video_notes(source_id, video_id, markdown, template_version, updated_at)
        VALUES('assets_1', 'vid-1', '# stale-note', 'v1.1', '2026-01-01T00:00:00Z')
        """
    )
    conn.commit()

    client = _mk_client(db_path, env_path)
    r = client.get("/items/vid-1/note", params={"source_id": "assets_1"})
    assert r.status_code == 200
    body = r.json()
    assert body["markdown"] != "# stale-note"
    assert "group:assets_1/Favorites/videos/vid-1.mp4" in body["markdown"]


def test_force_regenerates_even_user_cached_note(tmp_path: Path) -> None:
    db_path = tmp_path / "sx_obsidian.db"
    env_path = tmp_path / "pipeline.env"

    src_root = tmp_path / "source_root"
    vault_root = tmp_path / "vault_root"
    src_root.mkdir(parents=True)
    vault_root.mkdir(parents=True)

    env_path.write_text(
        "\n".join(
            [
                f"SRC_PATH_1={src_root}",
                f"VAULT_1={vault_root}",
                "SRC_PROFILE_1_ID=assets_1",
            ]
        ),
        encoding="utf-8",
    )

    _seed_video(db_path, "assets_1", "vid-1")
    conn = connect(db_path)
    init_db(conn, enable_fts=False)
    conn.execute(
        """
        INSERT INTO video_notes(source_id, video_id, markdown, template_version, updated_at)
        VALUES('assets_1', 'vid-1', '# user-note', 'user', '2026-01-01T00:00:00Z')
        """
    )
    conn.commit()

    client = _mk_client(db_path, env_path)

    keep = client.get("/items/vid-1/note", params={"source_id": "assets_1"})
    assert keep.status_code == 200
    assert keep.json()["markdown"] == "# user-note"

    regen = client.get("/items/vid-1/note", params={"source_id": "assets_1", "force": True})
    assert regen.status_code == 200
    body = regen.json()
    assert body["markdown"] != "# user-note"
    assert "group:assets_1/Favorites/videos/vid-1.mp4" in body["markdown"]


def test_note_pathlinker_group_override_is_ephemeral(tmp_path: Path) -> None:
    db_path = tmp_path / "sx_obsidian.db"
    env_path = tmp_path / "pipeline.env"

    src_root = tmp_path / "source_root"
    vault_root = tmp_path / "vault_root"
    src_root.mkdir(parents=True)
    vault_root.mkdir(parents=True)

    env_path.write_text(
        "\n".join(
            [
                f"SRC_PATH_1={src_root}",
                f"VAULT_1={vault_root}",
                "SRC_PROFILE_1_ID=assets_1",
            ]
        ),
        encoding="utf-8",
    )

    _seed_video(db_path, "assets_1", "vid-1")
    client = _mk_client(db_path, env_path)

    base = client.get("/items/vid-1/note", params={"source_id": "assets_1", "force": True})
    assert base.status_code == 200
    assert "group:assets_1/Favorites/videos/vid-1.mp4" in base.json()["markdown"]

    overridden = client.get(
        "/items/vid-1/note",
        params={"source_id": "assets_1", "pathlinker_group": "local_group_1"},
    )
    assert overridden.status_code == 200
    assert "group:local_group_1/Favorites/videos/vid-1.mp4" in overridden.json()["markdown"]

    # Override render should be ephemeral and must not overwrite shared DB cache.
    after = client.get("/items/vid-1/note", params={"source_id": "assets_1"})
    assert after.status_code == 200
    assert "group:assets_1/Favorites/videos/vid-1.mp4" in after.json()["markdown"]


def test_media_cover_resolves_data_prefixed_relative_path(tmp_path: Path) -> None:
    db_path = tmp_path / "sx_obsidian.db"
    env_path = tmp_path / "pipeline.env"

    src_root = tmp_path / "source_root"
    src_root.mkdir(parents=True)
    (src_root / "data" / "Favorites" / "covers").mkdir(parents=True)
    (src_root / "data" / "Favorites" / "covers" / "vid-1.jpg").write_bytes(b"jpeg")

    env_path.write_text(
        "\n".join(
            [
                f"SRC_PATH_1={src_root}",
                "SRC_PROFILE_1_ID=assets_1",
            ]
        ),
        encoding="utf-8",
    )

    _seed_video(
        db_path,
        "assets_1",
        "vid-1",
        cover_path="data/Favorites/covers/vid-1.jpg",
    )
    client = _mk_client(db_path, env_path)

    r = client.get("/media/cover/vid-1", params={"source_id": "assets_1"})
    assert r.status_code == 200


def test_media_cover_resolves_windows_src_path_in_wsl_runtime(tmp_path: Path) -> None:
    db_path = tmp_path / "sx_obsidian.db"
    env_path = tmp_path / "pipeline.env"

    # Emulate SchedulerX .env configured with Windows path while API runs on Linux/WSL.
    env_path.write_text(
        "\n".join(
            [
                r"SRC_PATH_1=T:\\MediaRoot",
                "SRC_PROFILE_1_ID=assets_1",
            ]
        ),
        encoding="utf-8",
    )

    # Expected WSL mirror location for T:\MediaRoot
    wsl_root = Path("/mnt/t/MediaRoot")
    try:
        (wsl_root / "data" / "Favorites" / "covers").mkdir(parents=True, exist_ok=True)
        (wsl_root / "data" / "Favorites" / "covers" / "vid-1.jpg").write_bytes(b"jpeg")
    except Exception:
        pytest.skip("/mnt/t is not writable in this test environment")

    _seed_video(db_path, "assets_1", "vid-1")
    client = _mk_client(db_path, env_path)

    r = client.get("/media/cover/vid-1", params={"source_id": "assets_1"})
    assert r.status_code == 200
