"""Help and shortcuts screen."""
from __future__ import annotations

from typing import TYPE_CHECKING

try:
    import questionary
    from questionary import Choice
    from rich.panel import Panel
except ImportError:  # pragma: no cover
    questionary = None  # type: ignore

from ..components import BRAND_STYLE, nav_choices, render_breadcrumbs
from ..router import register_screen

if TYPE_CHECKING:
    from ..router import Router


@register_screen("help")
def show_help(router: Router) -> str | None:
    """Help screen with keyboard shortcuts and workflow overview.
    
    Args:
        router: Router instance
        
    Returns:
        Navigation command
    """
    router.console.clear()
    render_breadcrumbs(router)
    
    content = """[bold]Navigation[/bold]
  ↑/↓       Navigate menus
  Enter     Select option
  Ctrl+C    Exit gracefully (from anywhere)

[bold]Typical Workflow[/bold]
  1. Import Data  →  Load CSV into database
  2. Search       →  Browse your library
  3. API Server   →  Start for Obsidian plugin

[bold]Icons[/bold]
  ✓   Success / completed
  ✗   Error / failed
  ⚠   Warning / attention needed
  ★   Bookmarked item

[bold]Command Line Usage[/bold]
  [cyan]sxdb[/cyan]                   Interactive TUI
  [cyan]sxdb status[/cyan]            Quick status
  [cyan]sxdb import[/cyan]            Import CSV
  [cyan]sxdb find "query"[/cyan]      Search
  [cyan]sxdb run[/cyan]               Start API

[dim]Install alias: bash install_alias.sh[/dim]
[dim]For more info, see: docs/USAGE.md[/dim]
"""
    
    router.console.print(Panel.fit(content, title="Help", border_style="cyan"))
    router.console.print()
    
    if questionary is None:  # pragma: no cover
        return "back"
    
    action = questionary.select(
        "",
        choices=nav_choices(include_separator=False),
        style=BRAND_STYLE,
    ).ask()
    
    if action == "home":
        return "home"
    return "back"
