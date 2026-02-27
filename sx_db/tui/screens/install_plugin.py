"""Install Plugin screen — install already-built plugin to vaults."""
from __future__ import annotations

import questionary
from rich.panel import Panel

from ..components import BRAND_STYLE, nav_choices, render_header
from ..router import Router, register_screen

# Re-use deployment logic from build_deploy
from .build_deploy import PLUGIN_ARTIFACTS, PLUGIN_DIR, _collect_vault_paths, _deploy_to_vault


@register_screen("install_plugin")
def show_install_plugin(router: Router) -> str | None:
    """Install the already-built plugin to selected vaults (no rebuild)."""
    render_header(router.console, router.settings)

    router.console.print(
        Panel(
            "Install the latest built plugin to vault paths\n"
            "without rebuilding from source.",
            title="Install Plugin",
            border_style="cyan",
        )
    )

    # ── Check build artifacts exist ────────────────────────────────
    missing = [a for a in PLUGIN_ARTIFACTS if not (PLUGIN_DIR / a).exists()]
    if missing:
        router.console.print(
            f"[yellow]⚠ Missing build artifacts: {', '.join(missing)}[/]\n"
            "Run Build & Deploy first to build the plugin."
        )
        choice = questionary.select(
            "Actions:",
            choices=[
                questionary.Choice("Build & Deploy", value="build_deploy"),
                *nav_choices(),
            ],
            style=BRAND_STYLE,
        ).ask()
        return choice

    router.console.print("[green]✓ Build artifacts found[/]\n")

    # ── Select vaults ──────────────────────────────────────────────
    vault_paths = _collect_vault_paths(router)
    if isinstance(vault_paths, str):
        return vault_paths
    if not vault_paths:
        router.console.print("[yellow]No vault selected; plugin was not installed.[/]")
        return "back"

    # ── Deploy ─────────────────────────────────────────────────────
    router.console.print("\n[bold]Installing plugin...[/]\n")

    success = 0
    for vp in vault_paths:
        if _deploy_to_vault(router, vp):
            success += 1

    router.console.print(
        Panel(
            f"✓ Installed to {success}/{len(vault_paths)} vault(s)",
            border_style="green" if success == len(vault_paths) else "yellow",
        )
    )

    choice = questionary.select(
        "Next:",
        choices=nav_choices(),
        style=BRAND_STYLE,
    ).ask()
    return choice
