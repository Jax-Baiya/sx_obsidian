"""Menu/action configuration for Database Management screens.

Keeps the screen/controller file focused on orchestration and rendering.
"""
from __future__ import annotations

import questionary

from ..components import nav_choices


def db_action_handlers() -> dict[str, tuple[str, list[str]]]:
    """Map UI action IDs to (target, prisma_args)."""
    return {
        "run_studio_local": ("local", ["run_studio"]),
        "logs_local": ("local", ["logs"]),
        "validate_local": ("local", ["validate"]),
        "pull_local": ("local", ["db", "pull"]),
        "generate_local": ("local", ["generate"]),
        "studio_local": ("local", ["studio"]),
        "stop_studio_local": ("local", ["stop_studio"]),
        "run_studio_cloud": ("cloud", ["run_studio"]),
        "logs_cloud": ("cloud", ["logs"]),
        "validate_cloud": ("cloud", ["validate"]),
        "pull_cloud": ("cloud", ["db", "pull"]),
        "generate_cloud": ("cloud", ["generate"]),
        "studio_cloud": ("cloud", ["studio"]),
        "stop_studio_cloud": ("cloud", ["stop_studio"]),
        "stop_studio_all": ("all", ["stop_studio"]),
        "refresh_notes": ("shared", ["refresh_notes"]),
    }


def database_management_choices() -> list:
    """Primary database-management screen choices."""
    return [
        questionary.Separator("── Local DB (schema.local.prisma) ──"),
        questionary.Choice(
            "Run Prisma Studio (Local: validate + pull + generate + studio)",
            value="run_studio_local",
        ),
        questionary.Choice("Show Prisma Logs (Local)", value="logs_local"),
        questionary.Choice("Stop Prisma Studio (Local)", value="stop_studio_local"),
        questionary.Separator("── Cloud DB (schema.cloud.prisma) ──"),
        questionary.Choice(
            "Run Prisma Studio (Cloud: validate + pull + generate + studio)",
            value="run_studio_cloud",
        ),
        questionary.Choice("Show Prisma Logs (Cloud)", value="logs_cloud"),
        questionary.Choice("Stop Prisma Studio (Cloud)", value="stop_studio_cloud"),
        questionary.Separator("── Shared ──"),
        questionary.Choice("Re-render cached notes (selected profile)", value="refresh_notes"),
        questionary.Choice("Stop Prisma Studio (All)", value="stop_studio_all"),
        questionary.Choice("Advanced Prisma actions…", value="database_management_advanced"),
        questionary.Separator(""),
        *nav_choices(include_separator=False),
    ]


def database_management_advanced_choices() -> list:
    """Advanced database-management screen choices."""
    return [
        questionary.Separator("── Local DB (schema.local.prisma) ──"),
        questionary.Choice("Prisma Validate (Local)", value="validate_local"),
        questionary.Choice("Prisma DB Pull / Introspect (Local)", value="pull_local"),
        questionary.Choice("Prisma Generate Client (Local)", value="generate_local"),
        questionary.Choice("Prisma Studio (Local)", value="studio_local"),
        questionary.Choice("Stop Prisma Studio (Local)", value="stop_studio_local"),
        questionary.Separator("── Cloud DB (schema.cloud.prisma) ──"),
        questionary.Choice("Prisma Validate (Cloud)", value="validate_cloud"),
        questionary.Choice("Prisma DB Pull / Introspect (Cloud)", value="pull_cloud"),
        questionary.Choice("Prisma Generate Client (Cloud)", value="generate_cloud"),
        questionary.Choice("Prisma Studio (Cloud)", value="studio_cloud"),
        questionary.Choice("Stop Prisma Studio (Cloud)", value="stop_studio_cloud"),
        questionary.Separator("── Shared ──"),
        questionary.Choice("Re-render cached notes (selected profile)", value="refresh_notes"),
        questionary.Choice("Show Prisma Logs (Local)", value="logs_local"),
        questionary.Choice("Show Prisma Logs (Cloud)", value="logs_cloud"),
        questionary.Choice("Stop Prisma Studio (All)", value="stop_studio_all"),
        questionary.Separator(""),
        *nav_choices(include_separator=False),
    ]
