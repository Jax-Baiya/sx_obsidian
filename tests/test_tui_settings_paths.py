from __future__ import annotations

from pathlib import Path

from sx_db.tui.screens.settings import _upsert_env_vars


def test_upsert_env_vars_updates_and_appends(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "SRC_PATH_1=/old/source",
                "SRC_PATH_1_LABEL=OldLabel",
                "UNRELATED_KEY=keep",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    _upsert_env_vars(
        env_path,
        {
            "SRC_PATH_1": "/new/source",
            "VAULT_1": "/new/vault",
            "SRC_PATH_1_LABEL": "NewLabel",
        },
    )

    content = env_path.read_text(encoding="utf-8")
    assert "SRC_PATH_1=/new/source" in content
    assert "SRC_PATH_1_LABEL=NewLabel" in content
    assert "VAULT_1=/new/vault" in content
    assert "UNRELATED_KEY=keep" in content
