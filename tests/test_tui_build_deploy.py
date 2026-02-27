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


def test_default_checked_falls_back_to_profile_roots() -> None:
    all_paths = {
        "/mnt/t/AlexNova": "/mnt/t/AlexNova  [no .obsidian]",
        "/mnt/t/YuZhou": "/mnt/t/YuZhou  [✓ .obsidian]",
    }
    profiles = [_profile(1, "/mnt/t/AlexNova"), _profile(2, "/mnt/t/YuZhou")]

    checked = _default_checked_vault_paths(all_paths, profiles, None)
    assert "/mnt/t/AlexNova" in checked
    assert "/mnt/t/YuZhou" in checked


def test_default_checked_uses_obsidian_hint_when_profiles_missing() -> None:
    all_paths = {
        "/x/one": "/x/one  [no .obsidian]",
        "/x/two": "/x/two  [✓ .obsidian]",
    }

    checked = _default_checked_vault_paths(all_paths, [], None)
    assert checked == {"/x/two"}
