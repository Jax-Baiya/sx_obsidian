from __future__ import annotations

import json
import os
import pty
import select
import shutil
import subprocess
import time
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SXCTL = ROOT / "scripts" / "sxctl.sh"
SXCTL_DIR = ROOT / ".sxctl"
LOGS_DIR = ROOT / "_logs"


@pytest.fixture(autouse=True)
def preserve_sxctl_state(tmp_path: Path):
    backup_dir = tmp_path / "backup"
    backup_dir.mkdir(parents=True, exist_ok=True)

    tracked = [
        SXCTL_DIR / "context.env",
        SXCTL_DIR / "context.json",
        SXCTL_DIR / "history.json",
        LOGS_DIR / "last_successful_vault_path",
    ]

    snapshots: dict[Path, Path] = {}
    for p in tracked:
        if p.exists():
            dst = backup_dir / p.name
            shutil.copy2(p, dst)
            snapshots[p] = dst

    try:
        yield
    finally:
        for p in tracked:
            if p in snapshots:
                p.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(snapshots[p], p)
            elif p.exists():
                p.unlink()


def _run(args: list[str], env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    return subprocess.run(
        [str(SXCTL), *args],
        cwd=ROOT,
        env=merged,
        check=False,
        capture_output=True,
        text=True,
    )


def _make_vault(base: Path, name: str) -> Path:
    p = base / name
    (p / ".obsidian").mkdir(parents=True, exist_ok=True)
    return p


def test_postgres_primary_is_default_backend_and_context_fields(tmp_path: Path):
    vault = _make_vault(tmp_path, "vault_pg")

    proc = _run(
        ["context", "init"],
        env={
            "SXCTL_NONINTERACTIVE": "1",
            "SXCTL_PROFILE_INDEX": "2",
            "SXCTL_VAULT_ROOT": str(vault),
        },
    )
    assert proc.returncode == 0, proc.stderr

    ctx = (SXCTL_DIR / "context.env").read_text(encoding="utf-8")
    assert "SXCTL_DB_BACKEND=postgres_primary" in ctx

    show = _run(["context", "show"])
    assert show.returncode == 0
    out = show.stdout
    for field in ["Profile", "Source ID", "Data Path", "DB Backend", "Schema", "Search Path"]:
        assert field in out
    assert "DB Path" not in out


def test_sqlite_context_renders_legacy_fields_only(tmp_path: Path):
    vault = _make_vault(tmp_path, "vault_sqlite")

    proc = _run(
        ["context", "init"],
        env={
            "SXCTL_NONINTERACTIVE": "1",
            "SXCTL_PROFILE_INDEX": "1",
            "SXCTL_VAULT_ROOT": str(vault),
            "SXCTL_DB_BACKEND": "sqlite",
        },
    )
    assert proc.returncode == 0, proc.stderr

    show = _run(["context", "show"])
    assert show.returncode == 0
    out = show.stdout
    for field in ["Profile", "Source ID", "Data Path", "DB Backend", "DB Path"]:
        assert field in out
    assert "Schema" not in out
    assert "Search Path" not in out
    assert "legacy sqlite" in out


def test_history_pruning_removes_temp_and_normalizes_obsidian_paths(tmp_path: Path):
    valid_one = _make_vault(tmp_path, "valid_one")
    valid_two = _make_vault(tmp_path, "valid_two")

    SXCTL_DIR.mkdir(parents=True, exist_ok=True)
    polluted = [
        f"{valid_one}/.obsidian",
        str(valid_two),
        "/tmp/tmp.XYZ123",
        "/var/tmp/tmp.ABC999",
        "/definitely/missing/path",
    ]
    (SXCTL_DIR / "history.json").write_text(json.dumps(polluted, indent=2), encoding="utf-8")

    proc = _run(["--help"])
    assert proc.returncode == 0

    cleaned = json.loads((SXCTL_DIR / "history.json").read_text(encoding="utf-8"))
    assert str(valid_one) in cleaned
    assert str(valid_two) in cleaned
    assert not any(p.startswith("/tmp/tmp.") for p in cleaned)
    assert not any(p.startswith("/var/tmp/tmp.") for p in cleaned)
    assert not any(p.endswith("/.obsidian") for p in cleaned)


def test_menu_ctx_cancel_returns_to_main_menu(tmp_path: Path):
    vault = _make_vault(tmp_path, "vault_menu")
    init_proc = _run(
        ["context", "init"],
        env={
            "SXCTL_NONINTERACTIVE": "1",
            "SXCTL_PROFILE_INDEX": "2",
            "SXCTL_VAULT_ROOT": str(vault),
        },
    )
    assert init_proc.returncode == 0, init_proc.stderr

    pid, fd = pty.fork()
    if pid == 0:
        os.execv(str(SXCTL), [str(SXCTL), "menu"])

    buf = ""

    def read_for(seconds: float) -> None:
        nonlocal buf
        end = time.time() + seconds
        while time.time() < end:
            r, _, _ = select.select([fd], [], [], 0.1)
            if not r:
                continue
            try:
                data = os.read(fd, 4096)
            except OSError:
                return
            if not data:
                return
            buf += data.decode("utf-8", "ignore")

    read_for(2.0)
    # Move from API to CTX (6th option)
    for _ in range(5):
        os.write(fd, b"\x1b[B")
        time.sleep(0.06)
    os.write(fd, b"\r")

    read_for(1.6)
    # Move to "Back to main menu" in profile picker (4 profiles + back)
    for _ in range(4):
        os.write(fd, b"\x1b[B")
        time.sleep(0.06)
    os.write(fd, b"\r")

    read_for(1.8)
    os.write(fd, b"q")
    read_for(0.8)

    try:
        os.close(fd)
    except OSError:
        pass

    assert "Context change cancelled; returning to main menu" in buf
    assert buf.count("Main menu") >= 1
