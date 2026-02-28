from __future__ import annotations

import logging
import os
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from .settings import Settings


def _resolve_log_dir(settings: object) -> Path:
    """Resolve the API log directory.

    - If SX_API_LOG_DIR is absolute, use it directly.
    - Otherwise, treat it as relative to the repo root (sx_obsidian/).

    This keeps logs out of the vault by default.
    """

    raw = getattr(settings, "SX_API_LOG_DIR", Path("_logs"))
    p = raw if isinstance(raw, Path) else Path(str(raw))
    if p.is_absolute():
        return p

    project_root = Path(__file__).resolve().parents[1]  # .../sx_obsidian/sx_db -> .../sx_obsidian
    return project_root / p


def setup_api_logging(settings: object) -> Path:
    """Configure Python + uvicorn logging to write to a rotating diagnostic log file.

    Returns the resolved log file path.

    Rotation:
      - Daily rotation at midnight.
      - Keep the last `SX_API_LOG_BACKUP_COUNT` rotated files.

    Notes:
      - Access logs can be noisy; controlled via SX_API_LOG_ACCESS.
      - This function is safe to call multiple times (it resets handlers).
    """

    log_dir = _resolve_log_dir(settings)
    log_dir.mkdir(parents=True, exist_ok=True)

    log_file = log_dir / "sx_db_api.log"

    level_name = str(getattr(settings, "SX_API_LOG_LEVEL", "INFO") or "INFO").upper().strip()
    level = getattr(logging, level_name, logging.INFO)

    fmt = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"

    file_handler = TimedRotatingFileHandler(
        filename=str(log_file),
        when="midnight",
        interval=1,
        backupCount=max(0, int(getattr(settings, "SX_API_LOG_BACKUP_COUNT", 14) or 0)),
        encoding="utf-8",
        utc=False,
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(logging.Formatter(fmt))

    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(logging.Formatter(fmt))

    # Reset root handlers so we don't duplicate logs on reload / repeated starts.
    root = logging.getLogger()
    root.handlers = []
    root.setLevel(level)
    root.addHandler(file_handler)
    root.addHandler(console_handler)

    # Uvicorn loggers.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers = []
        lg.setLevel(level)
        lg.propagate = True

    access = bool(getattr(settings, "SX_API_LOG_ACCESS", False))
    if not access:
        # Keep error logs, drop access logs.
        logging.getLogger("uvicorn.access").disabled = True

    # A tiny breadcrumb for sanity.
    logging.getLogger("sx_db").info(
        "sx_db API logging enabled (file=%s, level=%s, access=%s)",
        os.fspath(log_file),
        level_name,
        access,
    )

    return log_file
