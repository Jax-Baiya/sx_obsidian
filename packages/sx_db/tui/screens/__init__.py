"""Screen modules for the TUI."""
from __future__ import annotations

# Import all screen modules to register them with the router
from . import (
    api_control,
    build_deploy,
    database_management,
    help,
    import_wizard,
    install_plugin,
    main,
    search,
    settings,
    sources,
    userdata,
)

__all__ = [
    "api_control",
    "build_deploy",
    "database_management",
    "help",
    "import_wizard",
    "install_plugin",
    "main",
    "search",
    "settings",
    "sources",
    "userdata",
]
