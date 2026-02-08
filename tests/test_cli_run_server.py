from __future__ import annotations

import sys
from types import SimpleNamespace

import sx_db.cli as cli


def test_run_uses_real_host_port_when_called_directly(monkeypatch):
    """Regression test: calling cli.run() directly must not use Typer OptionInfo defaults."""

    class _Settings:
        SX_API_HOST = "127.0.0.1"
        SX_API_PORT = 8123

    captured: dict[str, object] = {}

    def fake_uvicorn_run(app, host=None, port=None, reload=None, **kwargs):
        captured["app"] = app
        captured["host"] = host
        captured["port"] = port
        captured["reload"] = reload
        captured["kwargs"] = kwargs

    # Ensure the function doesn't consult the real environment.
    monkeypatch.setattr(cli, "load_settings", lambda: _Settings())

    # cli.run() imports uvicorn inside the function. Provide a fake module.
    monkeypatch.setitem(sys.modules, "uvicorn", SimpleNamespace(run=fake_uvicorn_run))

    cli.run()  # called with defaults, as the interactive menu does

    assert captured["app"] == "sx_db.app:app"
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 8123
    assert isinstance(captured["host"], str)
    assert isinstance(captured["port"], int)
