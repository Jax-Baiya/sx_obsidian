from __future__ import annotations

from pathlib import Path

import sx_db.cli as cli
from sx_db.db import connect, init_db


class _Settings:
    def __init__(self, db_path: Path):
        self.SX_DB_PATH = db_path
        self.SX_DB_ENABLE_FTS = False
        self.SX_DEFAULT_SOURCE_ID = "default"


def test_cli_source_commands_manage_registry(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "sx.db"
    conn = connect(db_path)
    init_db(conn, enable_fts=False)

    monkeypatch.setattr(cli, "load_settings", lambda: _Settings(db_path))

    cli.sources_add("alpha", label="Alpha", kind="csv", description="first", default=False)
    cli.sources_set_default("alpha")

    conn2 = connect(db_path)
    init_db(conn2, enable_fts=False)

    rows = conn2.execute("SELECT id, is_default FROM sources ORDER BY id").fetchall()
    ids = [r[0] for r in rows]
    assert "alpha" in ids

    default_row = conn2.execute("SELECT id FROM sources WHERE is_default=1").fetchone()
    assert default_row is not None
    assert default_row[0] == "alpha"

    # Empty, non-default source can be removed.
    cli.sources_add("temp", label="Temp", default=False)
    cli.sources_remove("temp")
    gone = conn2.execute("SELECT 1 FROM sources WHERE id='temp'").fetchone()
    assert gone is None
