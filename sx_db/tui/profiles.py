"""Source profile discovery from .env configuration.

Parses .env for SRC_PATH_N / VAULT_N / ASSETS_PATH_N / SRC_PROFILE_N_ID entries
and returns structured SourceProfile objects used by all TUI screens.

Key distinction:
    SRC_PATH_N    = source root path (external media/source location)
    VAULT_N       = Obsidian vault root used for plugin deployment
    ASSETS_PATH_N = SchedulerX assets dir (where CSVs live under xlsx_files/)
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

def _safe_is_dir(base: str | Path, *subpaths: str) -> bool:
    """Check if a path is a directory, gracefully handling OSErrors (e.g., unmounted drives)."""
    try:
        return Path(base, *subpaths).is_dir()
    except OSError:
        return False

if TYPE_CHECKING:
    pass


@dataclass
class SourceProfile:
    """A discovered source profile from .env."""

    index: int  # N in SRC_PATH_N
    label: str  # SRC_PATH_N_LABEL
    src_path: str  # SRC_PATH_N = source root path
    vault_path: str  # VAULT_N = Obsidian vault root (falls back to src_path)
    assets_path: str  # ASSETS_PATH_N = SchedulerX assets dir
    profile_id: str  # SRC_PROFILE_N_ID (e.g. "assets_1")
    schema_name: str  # derived: sxo_assets_N
    db_local_alias: str  # SXO_LOCAL_N alias name
    vault_fallback: bool = False  # True when VAULT_N is missing and src_path is used
    active: bool = False  # True if vault root exists

    @property
    def vault_root(self) -> Path:
        """Vault root path used for plugin deployment."""
        return Path(self.vault_path)

    @property
    def xlsx_dir(self) -> Path:
        """Path to xlsx_files/ inside the SchedulerX assets dir."""
        return Path(self.assets_path) / "xlsx_files"

    @property
    def csv_consolidated(self) -> Path | None:
        """Path to consolidated.csv if it exists."""
        p = self.xlsx_dir / "consolidated.csv"
        return p if p.exists() else None

    @property
    def csv_authors(self) -> Path | None:
        """Path to authors.csv if it exists."""
        p = self.xlsx_dir / "authors.csv"
        return p if p.exists() else None

    @property
    def csv_bookmarks(self) -> Path | None:
        """Path to bookmarks.csv if it exists."""
        p = self.xlsx_dir / "bookmarks.csv"
        return p if p.exists() else None

    def status_icon(self) -> str:
        """Return ✓ or ✗ based on vault root existence."""
        return "✓" if self.active else "✗"

    def has_csvs(self) -> bool:
        """Check if the xlsx_files dir has any CSVs."""
        return self.xlsx_dir.exists() and any(self.xlsx_dir.glob("*.csv"))


@dataclass
class VaultTarget:
    """A discovered vault path from .env."""

    key: str  # env key e.g. VAULT_default
    path: str  # path value
    has_obsidian: bool = False  # True if .obsidian/ exists

    def obsidian_dir(self) -> Path:
        return Path(self.path) / ".obsidian"

    def plugin_dir(self) -> Path:
        return self.obsidian_dir() / "plugins" / "sx-obsidian-db"


def discover_profiles(env_path: str | Path | None = None) -> list[SourceProfile]:
    """Parse .env to discover all source profiles.

    Scans for: SRC_PATH_N, VAULT_N, SRC_PATH_N_LABEL, ASSETS_PATH_N, SRC_PROFILE_N_ID
    and the corresponding PostgreSQL schema from SXO_LOCAL_N_DB_SCHEMA.

    Args:
        env_path: Path to .env file. Defaults to project root .env.

    Returns:
        List of SourceProfile sorted by index.
    """
    if env_path is None:
        env_path = Path(__file__).resolve().parent.parent.parent / ".env"

    env_path = Path(env_path)
    if not env_path.exists():
        return []

    env_vars = _parse_env_file(env_path)

    # Find all SRC_PATH_N entries (bare SRC_PATH_N, not SRC_PATH_N_*)
    src_pattern = re.compile(r"^SRC_PATH_(\d+)$")
    indices: list[int] = []
    for key in env_vars:
        m = src_pattern.match(key)
        if m:
            indices.append(int(m.group(1)))

    indices.sort()

    profiles: list[SourceProfile] = []
    for idx in indices:
        src_path = env_vars.get(f"SRC_PATH_{idx}", "")
        explicit_vault = env_vars.get(f"VAULT_{idx}", "")
        vault_path = explicit_vault or src_path
        label = env_vars.get(f"SRC_PATH_{idx}_LABEL", f"Profile {idx}")
        profile_id = env_vars.get(f"SRC_PROFILE_{idx}_ID", f"assets_{idx}")

        # Assets path: ASSETS_PATH_N or fall back to SRC_PATH_N
        assets_path = env_vars.get(f"ASSETS_PATH_{idx}", src_path)

        # Schema from SXO_LOCAL_N_DB_SCHEMA or derive from prefix
        schema_prefix = env_vars.get("SX_POSTGRES_SCHEMA_PREFIX", "sxo")
        schema_name = env_vars.get(
            f"SXO_LOCAL_{idx}_DB_SCHEMA",
            f"{schema_prefix}_{profile_id}",
        )

        db_local_alias = env_vars.get(f"SRC_PATH_{idx}_DB_LOCAL", f"SXO_LOCAL_{idx}")

        profiles.append(
            SourceProfile(
                index=idx,
                label=label,
                src_path=src_path,
                vault_path=vault_path,
                assets_path=assets_path,
                profile_id=profile_id,
                schema_name=schema_name,
                db_local_alias=db_local_alias,
                vault_fallback=not bool(explicit_vault),
                active=_safe_is_dir(vault_path) if vault_path else False,
            )
        )

    return profiles


def discover_vaults(env_path: str | Path | None = None) -> list[VaultTarget]:
    """Parse .env for VAULT_* entries.

    Args:
        env_path: Path to .env file.

    Returns:
        List of VaultTarget.
    """
    if env_path is None:
        env_path = Path(__file__).resolve().parent.parent.parent / ".env"

    env_path = Path(env_path)
    if not env_path.exists():
        return []

    env_vars = _parse_env_file(env_path)

    vault_pattern = re.compile(r"^VAULT_(?!WINDOWS)(\w+)$")
    vaults: list[VaultTarget] = []
    seen_paths: set[str] = set()

    for key, val in env_vars.items():
        m = vault_pattern.match(key)
        if m and val and val not in seen_paths:
            seen_paths.add(val)
            vaults.append(
                VaultTarget(
                    key=key,
                    path=val,
                    has_obsidian=_safe_is_dir(val, ".obsidian"),
                )
            )

    return vaults


def _parse_env_file(path: Path) -> dict[str, str]:
    """Simple .env parser — key=value lines, ignores comments and blanks."""
    env: dict[str, str] = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip()
            env[key] = val
    return env
