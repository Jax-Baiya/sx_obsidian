from __future__ import annotations

import os
import sys


def _ensure_project_root_on_path() -> None:
    # When running via the venv's pytest entrypoint, the CWD is not guaranteed to
    # be on sys.path. Ensure the repository root (containing `sx/`) is importable.
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)


_ensure_project_root_on_path()
