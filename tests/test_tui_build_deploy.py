from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from sx_db.tui.screens.build_deploy import _default_checked_vault_paths


def _profile(index: int, root: str):
    return SimpleNamespace(index=index, vault_root=Path(root))


def test_default_checked_prefers_active_profile_indices() -> None:
    all_paths = {
        "/mnt/t/AlexNova": "/mnt/t/AlexNova  [✓ .obsidian]",
        "/mnt/t/YuZhou": "/mnt/t/YuZhou  [✓ .obsidian]",
        "/mnt/t/Other": "/mnt/t/Other  [✓ .obsidian]",
    }
    profiles = [_profile(1, "/mnt/t/AlexNova"), _profile(2, "/mnt/t/YuZhou")]

    checked = _default_checked_vault_paths(all_paths, profiles, [2])
    assert checked == {"/mnt/t/YuZhou"}


def test_default_checked_falls_back_to_profile_roots(tmp_path: Path) -> None:
    alex = tmp_path / "AlexNova"
    yuzhou = tmp_path / "YuZhou"
    alex.mkdir(parents=True, exist_ok=True)
    yuzhou.mkdir(parents=True, exist_ok=True)

    all_paths = {
        str(alex): f"{alex}  [no .obsidian]",
        str(yuzhou): f"{yuzhou}  [✓ .obsidian]",
    }
    profiles = [_profile(1, str(alex)), _profile(2, str(yuzhou))]

    checked = _default_checked_vault_paths(all_paths, profiles, None)
    assert checked == {str(alex), str(yuzhou)}


def test_default_checked_uses_obsidian_hint_when_profiles_missing() -> None:
    all_paths = {
        "/x/one": "/x/one  [no .obsidian]",
        "/x/two": "/x/two  [✓ .obsidian]",
    }

    checked = _default_checked_vault_paths(all_paths, [], None)
    assert checked == {"/x/two"}
