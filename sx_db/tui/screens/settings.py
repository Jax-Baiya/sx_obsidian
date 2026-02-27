"""Settings screen — profile CRUD, config view, user data."""
from __future__ import annotations

import os
from pathlib import Path

import questionary
from rich.panel import Panel
from rich.prompt import Confirm
from rich.table import Table

from ..components import BRAND_STYLE, nav_choices, render_header
from ..profiles import SourceProfile, discover_profiles, discover_vaults
from ..router import Router, register_screen


def _press_enter() -> None:
    """Simple press-enter-to-continue prompt."""
    Confirm.ask("[dim]Press Enter to continue[/dim]", default=True, show_default=False)


def _upsert_env_vars(env_path: Path, updates: dict[str, str]) -> None:
    """Upsert key/value pairs into a .env file while preserving unrelated lines."""

    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    else:
        lines = []

    remaining = dict(updates)
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            out.append(line)
            continue
        key, _, _val = stripped.partition("=")
        k = key.strip()
        if k in remaining:
            out.append(f"{k}={remaining.pop(k)}")
        else:
            out.append(line)

    if remaining:
        if out and out[-1].strip():
            out.append("")
        out.append("# Updated by sx_db settings")
        for k, v in remaining.items():
            out.append(f"{k}={v}")

    env_path.write_text("\n".join(out) + "\n", encoding="utf-8")


def _choose_profile_for_paths() -> SourceProfile | None:
    profiles = discover_profiles()
    if not profiles:
        return None

    choices = [
        questionary.Choice(
            f"{p.index}) {p.label} ({p.profile_id}) · source={p.src_path or '-'} · vault={p.vault_path or '-'}",
            value=p.index,
        )
        for p in profiles
    ]
    choices.append(questionary.Separator(""))
    choices.extend(nav_choices(include_separator=False))
    choices.append(questionary.Choice("Cancel", value="__cancel__"))

    selected = questionary.select(
        "Choose profile to edit database paths:",
        choices=choices,
        style=BRAND_STYLE,
        use_shortcuts=True,
    ).ask()
    if selected in (None, "__cancel__", "back", "home"):
        return None
    return next((p for p in profiles if p.index == int(selected)), None)


def _configure_database_paths(router: Router) -> None:
    profile = _choose_profile_for_paths()
    if profile is None:
        router.console.print("[yellow]No profile selected.[/]")
        _press_enter()
        return

    known_vaults = discover_vaults()
    vault_choices = [
        questionary.Choice(
            f"{v.path} ({'✓ .obsidian' if v.has_obsidian else 'no .obsidian'})",
            value=v.path,
        )
        for v in known_vaults
    ]

    if vault_choices:
        vault_choices.append(questionary.Separator(""))
    vault_choices.extend(nav_choices(include_separator=False))
    vault_choices.append(questionary.Choice("Custom path…", value="__custom__"))

    selected_vault = questionary.select(
        f"Vault path for profile {profile.index} ({profile.label}):",
        choices=vault_choices,
        default=(profile.vault_path if profile.vault_path else None),
        style=BRAND_STYLE,
        use_shortcuts=True,
    ).ask()

    vault_path = profile.vault_path
    if selected_vault in ("back", "home", None):
        router.console.print("[yellow]Cancelled.[/]")
        _press_enter()
        return

    if selected_vault == "__custom__":
        custom = questionary.text(
            "Enter vault path (VAULT_N):",
            default=profile.vault_path or profile.src_path,
            style=BRAND_STYLE,
        ).ask()
        if custom and custom.strip():
            vault_path = custom.strip()
    elif isinstance(selected_vault, str) and selected_vault.strip():
        vault_path = selected_vault.strip()

    src_path = questionary.text(
        "Source path (media location, SRC_PATH_N):",
        default=profile.src_path,
        style=BRAND_STYLE,
    ).ask()
    if not src_path or not src_path.strip():
        router.console.print("[yellow]Source path not changed.[/]")
        _press_enter()
        return
    src_path = src_path.strip()

    label = questionary.text(
        "Profile label:",
        default=profile.label,
        style=BRAND_STYLE,
    ).ask()
    label = (label or profile.label).strip() or profile.label

    env_path = Path(__file__).resolve().parent.parent.parent.parent / ".env"

    router.console.print(
        Panel(
            "\n".join(
                [
                    f"Profile: {profile.index} ({profile.profile_id})",
                    f"SRC_PATH_{profile.index}={src_path}",
                    f"VAULT_{profile.index}={vault_path}",
                    f"SRC_PATH_{profile.index}_LABEL={label}",
                ]
            ),
            title="Confirm Database Paths Update",
            border_style="cyan",
        )
    )

    proceed = questionary.confirm(
        "Write these values to .env?",
        default=True,
        style=BRAND_STYLE,
    ).ask()
    if not proceed:
        router.console.print("[yellow]Cancelled.[/]")
        _press_enter()
        return

    try:
        _upsert_env_vars(
            env_path,
            {
                f"SRC_PATH_{profile.index}": src_path,
                f"VAULT_{profile.index}": vault_path,
                f"SRC_PATH_{profile.index}_LABEL": label,
            },
        )
        router.console.print(f"[green]✓ Updated {env_path}[/]")
    except Exception as e:
        router.console.print(f"[red]✗ Failed to update .env: {e}[/]")

    _press_enter()


@register_screen("settings")
def show_settings(router: Router) -> str | None:
    """Settings sub-menu with profile management."""
    render_header(router.console, router.settings)

    choice = questionary.select(
        "Settings:",
        choices=[
            questionary.Choice("View Config", value="view_config"),
            questionary.Choice("Database Paths (Vault/Source)", value="db_paths"),
            questionary.Choice("Add Profile", value="add_profile"),
            questionary.Choice("Refresh Profiles", value="refresh_profiles"),
            questionary.Choice("User Data Export/Import", value="userdata_menu"),
            questionary.Separator(""),
            *nav_choices(),
        ],
        style=BRAND_STYLE,
    ).ask()

    if choice == "view_config":
        _show_config(router)
        return "settings"
    elif choice == "db_paths":
        _configure_database_paths(router)
        return "settings"
    elif choice == "add_profile":
        _add_profile(router)
        return "settings"
    elif choice == "refresh_profiles":
        _refresh_profiles(router)
        return "settings"
    elif choice == "userdata_menu":
        return "userdata_menu"
    else:
        return choice


def _show_config(router: Router) -> None:
    """Display current configuration as a read-only panel."""
    table = Table(
        title="Current Configuration",
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Key", style="dim")
    table.add_column("Value")

    # Show key settings
    important_keys = [
        "SX_DB_BACKEND_MODE",
        "SX_PIPELINE_DB_MODE",
        "SX_PIPELINE_DB_PROFILE",
        "SX_POSTGRES_DSN",
        "SX_POSTGRES_SCHEMA_PREFIX",
        "SX_API_HOST",
        "SX_API_PORT",
        "SX_DEFAULT_SOURCE_ID",
    ]

    for key in important_keys:
        val = os.getenv(key, "[dim]not set[/]")
        # Mask passwords/secrets
        if "PASSWORD" in key or "SECRET" in key or "KEY" in key:
            val = "****"
        table.add_row(key, val)

    router.console.print(table)

    # Show profiles summary
    profiles = discover_profiles()
    router.console.print(
        f"\n[cyan]Profiles discovered: {len(profiles)}[/]"
    )
    for p in profiles:
        icon = "[green]✓[/]" if p.active else "[red]✗[/]"
        router.console.print(
            f"  {icon} {p.label} → {p.schema_name}\n"
            f"     source: {p.src_path}\n"
            f"     vault:  {p.vault_path}"
        )

    router.console.print()
    _press_enter()


def _add_profile(router: Router) -> None:
    """Wizard to add a new source profile to .env."""
    profiles = discover_profiles()
    next_index = max((p.index for p in profiles), default=0) + 1

    router.console.print(
        Panel(
            f"Adding Source Profile {next_index}",
            border_style="cyan",
        )
    )

    label = questionary.text(
        "Profile label (e.g. 'MyVault Data'):",
        style=BRAND_STYLE,
    ).ask()
    if not label:
        return

    src_path = questionary.text(
        "Source data path (e.g. /mnt/t/MyVault/data):",
        style=BRAND_STYLE,
    ).ask()
    if not src_path:
        return

    profile_id = questionary.text(
        f"Profile ID (default: assets_{next_index}):",
        default=f"assets_{next_index}",
        style=BRAND_STYLE,
    ).ask()

    schema_prefix = os.getenv("SX_POSTGRES_SCHEMA_PREFIX", "sxo")
    schema_name = f"{schema_prefix}_{profile_id}"

    # Confirm
    router.console.print(f"\n  Index:     {next_index}")
    router.console.print(f"  Label:     {label}")
    router.console.print(f"  Path:      {src_path}")
    router.console.print(f"  Profile:   {profile_id}")
    router.console.print(f"  Schema:    {schema_name}")

    proceed = questionary.confirm(
        "\nAdd this profile to .env?",
        default=True,
        style=BRAND_STYLE,
    ).ask()

    if not proceed:
        return

    # Append to .env
    env_path = Path(__file__).resolve().parent.parent.parent.parent / ".env"
    db_name = os.getenv("SXO_LOCAL_1_DB_NAME", "sx_obsidian_unified_db")
    db_user = os.getenv("SXO_LOCAL_1_DB_USER", "jax")
    db_pass = os.getenv("SXO_LOCAL_1_DB_PASSWORD", "2112")
    db_host = os.getenv("SXO_LOCAL_1_DB_HOST", "localhost")
    db_port = os.getenv("SXO_LOCAL_1_DB_PORT", "5432")

    block = f"""
# ══════════════════
# Source Profile {next_index}: {label}
# ══════════════════
SRC_PATH_{next_index}={src_path}
SRC_PATH_{next_index}_LABEL={label}
SRC_PROFILE_{next_index}_ID={profile_id}
SRC_PATH_{next_index}_DB_LOCAL=SXO_LOCAL_{next_index}
DATABASE_PROFILE_{next_index}_LOCAL=SXO_LOCAL_{next_index}
DATABASE_PROFILE_{next_index}={profile_id}

# SXO_LOCAL_{next_index} ({label})
SXO_LOCAL_{next_index}_DB_USER={db_user}
SXO_LOCAL_{next_index}_DB_PASSWORD={db_pass}
SXO_LOCAL_{next_index}_DB_HOST={db_host}
SXO_LOCAL_{next_index}_DB_PORT={db_port}
SXO_LOCAL_{next_index}_DB_NAME={db_name}
SXO_LOCAL_{next_index}_DB_SCHEMA={schema_name}
"""

    try:
        with open(env_path, "a") as f:
            f.write(block)
        router.console.print(
            f"\n[green]✓ Profile {next_index} added to .env[/]"
        )
    except Exception as e:
        router.console.print(f"\n[red]✗ Failed to write .env: {e}[/]")

    _press_enter()


def _refresh_profiles(router: Router) -> None:
    """Re-scan .env and show current profile status."""
    profiles = discover_profiles()

    router.console.print(
        Panel(
            f"Found {len(profiles)} source profile(s)",
            title="Profile Refresh",
            border_style="cyan",
        )
    )

    for p in profiles:
        icon = "[green]✓[/]" if p.active else "[red]✗[/]"
        router.console.print(
            f"  {icon} Profile {p.index}: {p.label}\n"
            f"     Source: {p.src_path}\n"
            f"     Vault: {p.vault_path}\n"
            f"     Schema: {p.schema_name}\n"
        )

    _press_enter()
