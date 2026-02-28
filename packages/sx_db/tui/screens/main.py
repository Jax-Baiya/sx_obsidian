"""Main menu screen — entry point for the TUI."""
from __future__ import annotations

import questionary

from ..components import BRAND_STYLE, render_header, render_welcome_banner
from ..router import Router, register_screen


@register_screen("main_menu")
def show_main_menu(router: Router) -> str | None:
    """Display the main menu with correct workflow options."""
    render_welcome_banner(router.console)
    render_header(router.console, router.settings)

    CHOICES = [
        questionary.Separator("── Data ──"),
        questionary.Choice("Import Data", value="import_wizard"),
        questionary.Choice("Database management", value="database_management"),
        questionary.Choice("API Server", value="api_control"),
        questionary.Choice("Manage Sources", value="sources_menu"),
        questionary.Separator("── Plugin ──"),
        questionary.Choice("Build & Deploy", value="build_deploy"),
        questionary.Choice("Install Plugin", value="install_plugin"),
        questionary.Separator("── System ──"),
        questionary.Choice("Settings", value="settings"),
        questionary.Choice("Help", value="help"),
        questionary.Separator(""),
        questionary.Choice("Exit", value="exit"),
    ]

    choice = questionary.select(
        "What would you like to do?",
        choices=CHOICES,
        style=BRAND_STYLE,
        use_shortcuts=True,
    ).ask()

    if choice is None or choice == "exit":
        return "exit"

    return choice
