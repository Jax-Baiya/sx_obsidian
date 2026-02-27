from __future__ import annotations

from pathlib import Path

from sx_db.tui.profiles import discover_profiles


def test_discover_profiles_uses_explicit_vault(tmp_path: Path) -> None:
    src = tmp_path / "AlexNova"
    vault = tmp_path / "Amazon"
    assets = tmp_path / "SchedulerX_assets_1"
    src.mkdir(parents=True)
    vault.mkdir(parents=True)
    assets.mkdir(parents=True)

    env = tmp_path / ".env"
    env.write_text(
        "\n".join(
            [
                f"SRC_PATH_1={src}",
                f"VAULT_1={vault}",
                f"ASSETS_PATH_1={assets}",
                "SRC_PATH_1_LABEL=AlexNova",
                "SRC_PROFILE_1_ID=assets_1",
                "SX_POSTGRES_SCHEMA_PREFIX=sxo",
            ]
        ),
        encoding="utf-8",
    )

    profiles = discover_profiles(env)
    assert len(profiles) == 1
    p = profiles[0]
    assert p.src_path == str(src)
    assert p.vault_path == str(vault)
    assert str(p.vault_root) == str(vault)
    assert p.vault_fallback is False


def test_discover_profiles_fallbacks_vault_to_src(tmp_path: Path) -> None:
    src = tmp_path / "YuZhou"
    src.mkdir(parents=True)
    env = tmp_path / ".env"
    env.write_text(
        "\n".join(
            [
                f"SRC_PATH_2={src}",
                "SRC_PATH_2_LABEL=YuZhou",
                "SRC_PROFILE_2_ID=assets_2",
            ]
        ),
        encoding="utf-8",
    )

    profiles = discover_profiles(env)
    assert len(profiles) == 1
    p = profiles[0]
    assert p.vault_path == str(src)
    assert p.vault_fallback is True
