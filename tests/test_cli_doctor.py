from __future__ import annotations

import json
from pathlib import Path

import sx_db.cli as cli


def test_doctor_latest_logs_prefers_newest(tmp_path: Path, monkeypatch):
    logs = tmp_path / "_logs"
    logs.mkdir(parents=True, exist_ok=True)
    a = logs / "prisma_pipeline_local_sxo_assets_1_20260220_120000.log"
    b = logs / "prisma_pipeline_local_sxo_assets_1_20260220_130000.log"
    a.write_text("old\n", encoding="utf-8")
    b.write_text("new\n", encoding="utf-8")

    monkeypatch.setattr(cli, "_project_root", lambda: tmp_path)

    out = cli._doctor_latest_logs()
    latest = out["latest"]["prisma_pipeline"]
    assert latest is not None
    assert latest["path"].endswith("20260220_130000.log")
    assert "new" in latest["tail"]


def test_doctor_port_listeners_no_listener():
    out = cli._doctor_port_listeners(65530)
    assert out["port"] == 65530
    assert isinstance(out["pids"], list)


def test_doctor_json_output(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_doctor_shell_aliases", lambda: {"ok": True})
    monkeypatch.setattr(cli, "_doctor_port_listeners", lambda p: {"port": p, "listening": False, "pids": []})
    monkeypatch.setattr(cli, "_doctor_latest_logs", lambda: {"latest": {}})

    cli.doctor(json_out=True)
    captured = capsys.readouterr().out
    obj = json.loads(captured)
    assert obj["shell"]["ok"] is True
    assert obj["ports"]["5555"]["port"] == 5555
    assert obj["ports"]["5556"]["port"] == 5556
