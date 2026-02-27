"""Manage Sources screen — select active source profiles."""
from __future__ import annotations

import questionary
from rich.table import Table

from ..components import BRAND_STYLE, nav_choices, render_header
from ..profiles import discover_profiles
from ..router import Router, register_screen


@register_screen("sources_menu")
def show_sources_menu(router: Router) -> str | None:
    """Show all source profiles from .env with active status."""
    render_header(router.console, router.settings)

    profiles = discover_profiles()

    if not profiles:
        router.console.print(
            "[yellow]No source profiles found in .env[/]\n"
            "Add profiles via Settings > Add Profile."
        )
        choice = questionary.select(
            "Actions:",
            choices=nav_choices(),
            style=BRAND_STYLE,
        ).ask()
        return choice

    # ── Profile table ──────────────────────────────────────────────
    table = Table(
        title="Source Profiles",
        show_header=True,
        header_style="bold cyan",
        expand=True,
    )
    table.add_column("Idx", width=4, justify="center")
    table.add_column("Active", width=6, justify="center")
    table.add_column("Label", min_width=20)
    table.add_column("Profile ID", min_width=12)
    table.add_column("Schema", min_width=14)
    table.add_column("Source Path", min_width=20)

    for p in profiles:
        status = "[green]✓[/]" if p.active else "[red]✗[/]"
        table.add_row(
            str(p.index),
            status,
            p.label,
            p.profile_id,
            p.schema_name,
            p.src_path,
        )

    router.console.print(table)
    router.console.print()

    # ── Multi-select active profiles ───────────────────────────────
    active_profiles = [p for p in profiles if p.active]
    if active_profiles:
        selected = questionary.checkbox(
            "Select active source profiles for import:",
            choices=[
                questionary.Choice(
                    f"{p.label} ({p.profile_id})",
                    value=p.index,
                    checked=True,
                )
                for p in active_profiles
            ],
            style=BRAND_STYLE,
        ).ask()

        if selected is not None:
            router.state.data["active_profile_indices"] = selected
            count = len(selected)
            router.console.print(
                f"\n[green]✓[/] {count} profile(s) marked active for import.\n"
            )
    else:
        router.console.print(
            "[yellow]No profiles have valid source directories.[/]\n"
            "Check that your source paths exist.\n"
        )

    # ── Navigation ─────────────────────────────────────────────────
    choice = questionary.select(
        "Actions:",
        choices=nav_choices(),
        style=BRAND_STYLE,
    ).ask()

    return choice
