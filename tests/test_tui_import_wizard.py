from __future__ import annotations

import sys

from sx_db.tui.screens.import_wizard import _build_import_cmd


def test_build_import_cmd_uses_current_interpreter_and_source_flag() -> None:
    cmd = _build_import_cmd("assets_1")
    assert cmd == [sys.executable, "-m", "sx_db", "import-csv", "--source", "assets_1"]
