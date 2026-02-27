from __future__ import annotations

from pathlib import Path

from sx_db.tui.screens import build_deploy as bd


def test_known_vault_memory_roundtrip(tmp_path: Path, monkeypatch) -> None:
    mem_file = tmp_path / "known_vault_paths.json"
    monkeypatch.setattr(bd, "KNOWN_VAULTS_PATH", mem_file)

    p1 = tmp_path / "vault_a"
    p2 = tmp_path / "vault_b"
    p1.mkdir(parents=True)
    p2.mkdir(parents=True)

    bd._remember_vault_paths([p1, p2, p1])
    loaded = bd._load_known_vault_memory()
    assert loaded == [str(p1), str(p2)]

    removed = bd._forget_vault_paths([str(p1)])
    assert removed == 1
    loaded2 = bd._load_known_vault_memory()
    assert loaded2 == [str(p2)]


def test_delete_memory_at_cursor_middle() -> None:
    paths = ["/a", "/b", "/c"]
    updated, next_cursor, removed = bd._delete_memory_at_cursor(paths, 1)
    assert removed == "/b"
    assert updated == ["/a", "/c"]
    assert next_cursor == 1


def test_delete_memory_at_cursor_last() -> None:
    paths = ["/a", "/b"]
    updated, next_cursor, removed = bd._delete_memory_at_cursor(paths, 1)
    assert removed == "/b"
    assert updated == ["/a"]
    assert next_cursor == 0
