"""Database server discovery — local vs cloud (Supabase).

Parses .env for SXO_LOCAL_N and SXO_SESSION_N connection profiles
and provides structured DatabaseServer objects for TUI screens.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote


@dataclass
class DatabaseServer:
    """Represents a discovered PostgreSQL server (local or cloud)."""

    name: str            # "local" or "cloud"
    label: str           # "Local (localhost)" or "Cloud (Supabase)"
    host: str
    port: int
    db_name: str
    user: str
    password: str
    alias_prefix: str    # "SXO_LOCAL" or "SXO_SESSION"
    is_active: bool      # True if currently selected via DB_PROFILE

    def dsn(self, schema: str | None = None) -> str:
        """Build a PostgreSQL DSN, optionally with search_path."""
        base = (
            f"postgresql://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.db_name}"
        )
        if schema:
            base += f"?options=-c%20search_path%3D{quote(schema)}"
        return base

    def prisma_dsn(self, schema: str | None = None) -> str:
        """Build a Prisma-compatible DSN, optionally with schema query param.

        Prisma tools (validate/db pull/generate/studio) honor `?schema=...`.
        Using `options=-c search_path=...` can still introspect `public`.
        """
        base = (
            f"postgresql://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.db_name}"
        )
        if schema:
            base += f"?schema={quote(schema)}"
        return base

    def alias_for(self, index: int) -> str:
        """Get the full alias name for a profile index, e.g. SXO_LOCAL_1."""
        return f"{self.alias_prefix}_{index}"

    @property
    def short_label(self) -> str:
        """Short display label: 'Local' or 'Cloud'."""
        return "Local" if self.name == "local" else "Cloud"


def discover_servers(env_path: str | Path | None = None) -> list[DatabaseServer]:
    """Discover local and cloud database servers from .env.

    Returns a list of DatabaseServer objects (typically [local, cloud]).
    """
    if env_path is None:
        env_path = Path(__file__).resolve().parent.parent.parent / ".env"

    env_path = Path(env_path)
    if not env_path.exists():
        return []

    env = _parse_env(env_path)
    servers: list[DatabaseServer] = []

    # Current active profile
    active_profile = env.get("DB_PROFILE", "SXO_LOCAL_1")

    # ── Local server (SXO_LOCAL_1) ──────────────────────────────────
    local_host = env.get("SXO_LOCAL_1_DB_HOST")
    if local_host:
        servers.append(
            DatabaseServer(
                name="local",
                label=f"Local ({local_host})",
                host=local_host,
                port=int(env.get("SXO_LOCAL_1_DB_PORT", "5432")),
                db_name=env.get("SXO_LOCAL_1_DB_NAME", ""),
                user=env.get("SXO_LOCAL_1_DB_USER", ""),
                password=env.get("SXO_LOCAL_1_DB_PASSWORD", ""),
                alias_prefix="SXO_LOCAL",
                is_active=active_profile.startswith("SXO_LOCAL"),
            )
        )

    # ── Cloud server (SXO_SESSION_1 — Supabase pooler) ──────────────
    cloud_host = env.get("SXO_SESSION_1_DB_HOST")
    if cloud_host:
        # Derive a friendly label from the host
        if "supabase" in cloud_host:
            cloud_label = "Cloud (Supabase)"
        else:
            cloud_label = f"Cloud ({cloud_host})"

        servers.append(
            DatabaseServer(
                name="cloud",
                label=cloud_label,
                host=cloud_host,
                port=int(env.get("SXO_SESSION_1_DB_PORT", "5432")),
                db_name=env.get("SXO_SESSION_1_DB_NAME", ""),
                user=env.get("SXO_SESSION_1_DB_USER", ""),
                password=env.get("SXO_SESSION_1_DB_PASSWORD", ""),
                alias_prefix="SXO_SESSION",
                is_active=active_profile.startswith("SXO_SESSION"),
            )
        )

    return servers


def get_active_server(
    env_path: str | Path | None = None,
) -> DatabaseServer | None:
    """Return the currently active database server based on DB_PROFILE."""
    servers = discover_servers(env_path)
    for s in servers:
        if s.is_active:
            return s
    return servers[0] if servers else None


def get_server_by_name(
    name: str, env_path: str | Path | None = None
) -> DatabaseServer | None:
    """Get a specific server by name ('local' or 'cloud')."""
    for s in discover_servers(env_path):
        if s.name == name:
            return s
    return None


def _parse_env(path: Path) -> dict[str, str]:
    """Simple .env parser."""
    env: dict[str, str] = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()
    return env
