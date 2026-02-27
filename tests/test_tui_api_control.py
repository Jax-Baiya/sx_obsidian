from __future__ import annotations

import sys
from types import SimpleNamespace
import json

from sx_db.tui.screens.api_control import _build_api_server_cmd, _fetch_health_payload, _start_server


def test_build_api_server_cmd_uses_current_interpreter() -> None:
    cmd = _build_api_server_cmd("127.0.0.1", "8123")
    assert cmd == [sys.executable, "-m", "sx_db", "serve", "--host", "127.0.0.1", "--port", "8123"]


def test_start_server_skips_when_external_server_is_running(monkeypatch) -> None:
    printed: list[str] = []

    class _Console:
        def print(self, msg):
            printed.append(str(msg))

    router = SimpleNamespace(console=_Console(), state=SimpleNamespace(active_db_server="local"))

    monkeypatch.setattr("sx_db.tui.screens.api_control._is_server_running", lambda: False)
    monkeypatch.setattr("sx_db.tui.screens.api_control._api_healthy", lambda host, port: True)

    called = {"popen": False}

    def _boom(*args, **kwargs):
        called["popen"] = True
        raise AssertionError("Popen should not be called when external server already runs")

    monkeypatch.setattr("sx_db.tui.screens.api_control.get_server_by_name", lambda name: object())
    monkeypatch.setattr("sx_db.tui.screens.api_control.subprocess.Popen", _boom)

    _start_server(router, "127.0.0.1", "8123", "local")

    assert called["popen"] is False
    assert any("already reachable" in line for line in printed)


def test_fetch_health_payload_returns_json_dict(monkeypatch) -> None:
    payload = {
        "ok": True,
        "source_id": "assets_1",
        "backend": {"backend": "postgres_primary"},
        "profile_index": 1,
        "db_path": "data/sx_obsidian.db",
        "api_version": "1.0.0",
        "env_hint": "POSTGRES_PRIMARY",
    }

    class _Resp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(payload).encode("utf-8")

    monkeypatch.setattr("sx_db.tui.screens.api_control.urlopen", lambda *a, **k: _Resp())

    out = _fetch_health_payload("127.0.0.1", "8123")
    assert out == payload
    assert out["profile_index"] == 1
    assert out["api_version"] == "1.0.0"
    assert out["env_hint"] == "POSTGRES_PRIMARY"
    assert out["db_path"] == "data/sx_obsidian.db"


def test_view_health_payload_renders_new_fields(monkeypatch) -> None:
    """Verify _view_health_payload displays the new diagnostic fields."""
    from io import StringIO
    from rich.console import Console
    from sx_db.tui.screens.api_control import _view_health_payload

    payload = {
        "ok": True,
        "source_id": "assets_1",
        "backend": {"backend": "sqlite"},
        "profile_index": 1,
        "db_path": "data/sx_obsidian.db",
        "api_version": "1.0.0",
        "env_hint": "SQLITE",
    }

    monkeypatch.setattr(
        "sx_db.tui.screens.api_control._fetch_health_payload",
        lambda host, port: payload,
    )

    # Mock questionary.select to pick "back"
    class _FakeSelect:
        def ask(self):
            return "back"

    monkeypatch.setattr(
        "sx_db.tui.screens.api_control.questionary.select",
        lambda *a, **kw: _FakeSelect(),
    )

    buf = StringIO()
    console = Console(file=buf, force_terminal=True)

    router = SimpleNamespace(console=console)

    _view_health_payload(router, "127.0.0.1", "8123")

    rendered = buf.getvalue()
    assert "profile_index" in rendered
    assert "db_path" in rendered
    assert "api_version" in rendered
    assert "env_hint" in rendered


def test_fetch_health_payload_returns_none_on_non_200(monkeypatch) -> None:
    class _Resp:
        status = 503

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'{"ok": false}'

    monkeypatch.setattr("sx_db.tui.screens.api_control.urlopen", lambda *a, **k: _Resp())

    out = _fetch_health_payload("127.0.0.1", "8123")
    assert out is None
