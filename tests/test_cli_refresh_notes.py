from __future__ import annotations

from pathlib import Path

import sx_db.cli as cli
from sx_db.db import connect, ensure_source, init_db


class _Settings:
    def __init__(self, db_path: Path, scheduler_env: Path):
        self.SX_DB_PATH = db_path
        self.SX_DB_ENABLE_FTS = False
        self.SX_DEFAULT_SOURCE_ID = "default"
        self.SX_DB_BACKEND_MODE = "SQLITE"
        self.SX_SCHEDULERX_ENV = scheduler_env
        self.SX_MEDIA_VAULT = None
        self.VAULT_default = str(db_path.parent)
        self.VAULT_WINDOWS_default = None
        self.PATH_STYLE = "linux"
        self.SX_MEDIA_DATA_DIR = "data"
        self.DATA_DIR = "data"


def test_refresh_notes_rerenders_with_group_links(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "sx.db"
    src_root = tmp_path / "src_root"
    vault_root = tmp_path / "vault_root"
    src_root.mkdir(parents=True)
    vault_root.mkdir(parents=True)

    scheduler_env = tmp_path / "pipeline.env"
    scheduler_env.write_text(
        "\n".join(
            [
                f"SRC_PATH_1={src_root}",
                f"VAULT_1={vault_root}",
                "SRC_PROFILE_1_ID=assets_1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    conn = connect(db_path)
    init_db(conn, enable_fts=False)
    ensure_source(conn, "assets_1", label="assets_1")
    conn.execute(
        """
        INSERT INTO videos(source_id, id, platform, caption, bookmarked, video_path, cover_path, updated_at)
        VALUES('assets_1', 'vid-1', 'tiktok', 'hello', 1, 'Favorites/videos/vid-1.mp4', 'Favorites/covers/vid-1.jpg', '2026-01-01T00:00:00Z')
        """
    )
    conn.commit()

    monkeypatch.setattr(cli, "load_settings", lambda: _Settings(db_path, scheduler_env))

    cli.refresh_notes(source="assets_1", limit=0)

    row = conn.execute(
        "SELECT markdown, template_version FROM video_notes WHERE source_id='assets_1' AND video_id='vid-1'"
    ).fetchone()
    assert row is not None
    markdown, template_version = row
    assert template_version == "v1.3"
    assert "group:assets_1/Favorites/videos/vid-1.mp4" in str(markdown)
