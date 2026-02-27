from __future__ import annotations

from sx_db.postgres_mirror import _safe_ident, _schema_from_pg_url


def test_safe_ident_accepts_valid_names() -> None:
    assert _safe_ident("pipe") == "pipe"
    assert _safe_ident("sx_obsidian_2") == "sx_obsidian_2"
    assert _safe_ident("_internal") == "_internal"


def test_safe_ident_rejects_invalid_names() -> None:
    assert _safe_ident("") is None
    assert _safe_ident("public;drop table x") is None
    assert _safe_ident("a-b") is None
    assert _safe_ident("1abc") is None


def test_schema_from_pg_url_parses_search_path_options() -> None:
    url = "postgresql://u:p@localhost:5432/db?options=-c%20search_path%3Dsx_obsidian_2%2Cpublic"
    assert _schema_from_pg_url(url) == "sx_obsidian_2"


def test_schema_from_pg_url_handles_missing_or_invalid() -> None:
    assert _schema_from_pg_url("postgresql://u:p@localhost:5432/db") is None
    # invalid identifier should be rejected
    bad = "postgresql://u:p@localhost:5432/db?options=-c%20search_path%3Dsx-obsidian%2Cpublic"
    assert _schema_from_pg_url(bad) is None
