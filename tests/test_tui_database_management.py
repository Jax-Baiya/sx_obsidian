"""Unit tests for database management TUI helpers."""
from __future__ import annotations

from unittest.mock import MagicMock

from sx_db.tui.db_targets import DatabaseServer
from sx_db.tui.screens.database_management import (
    _schema_for_target,
    _stop_prisma_studio,
    _studio_port_for_target,
)


def test_studio_port_mapping():
    """Local/cloud studio actions should use stable, distinct default ports."""
    assert _studio_port_for_target("local") == 5555
    assert _studio_port_for_target("cloud") == 5556


def test_schema_for_target_mapping():
    """Target should map to the correct Prisma schema file."""
    assert _schema_for_target("local").name == "schema.local.prisma"
    assert _schema_for_target("cloud").name == "schema.cloud.prisma"


def test_prisma_dsn_uses_schema_query_param():
    """Prisma DSN should use ?schema=... so db pull targets the intended schema."""
    server = DatabaseServer(
        name="local",
        label="Local",
        host="localhost",
        port=5432,
        db_name="sx_obsidian_unified_db",
        user="jax",
        password="2112",
        alias_prefix="SXO_LOCAL",
        is_active=True,
    )
    dsn = server.prisma_dsn(schema="sxo_assets_2")
    assert "?schema=sxo_assets_2" in dsn
    assert "search_path" not in dsn


def test_stop_prisma_studio_no_listeners(monkeypatch):
    """Stopping Studio should gracefully succeed when no matching listeners exist."""

    def _fake_run(*args, **kwargs):
        cmd = args[0]
        m = MagicMock()
        m.returncode = 1
        m.stdout = ""
        m.stderr = ""
        if cmd and cmd[0] == "ss":
            m.returncode = 0
            m.stdout = ""
        return m

    monkeypatch.setattr("sx_db.tui.screens.database_management.subprocess.run", _fake_run)

    router = MagicMock()
    router.console = MagicMock()

    ok = _stop_prisma_studio(router, None)
    assert ok is True
