"""User data export/import screen."""
from __future__ import annotations

from typing import TYPE_CHECKING

try:
    import questionary
    from questionary import Choice
except ImportError:  # pragma: no cover
    questionary = None  # type: ignore

from ..components import BRAND_STYLE, nav_choices, render_breadcrumbs
from ..router import register_screen

if TYPE_CHECKING:
    from ..router import Router


@register_screen("userdata_menu")
def show_userdata_menu(router: Router) -> str | None:
    """User data export/import menu (calls existing CLI commands).
    
    Args:
        router: Router instance
        
    Returns:
        Navigation command
    """
    router.console.clear()
    render_breadcrumbs(router)
    
    if questionary is None:  # pragma: no cover
        router.console.print("[yellow]questionary not installed[/yellow]")
        return "back"
    
    router.console.print(
        "[bold]User Data Management[/bold]\n\n"
        "Export and import user-owned data (ratings, tags, notes)\n"
        "across database rebuilds.\n"
    )
    
    action = questionary.select(
        "Choose action:",
        choices=[
            Choice(title="Export User Data", value="export"),
            Choice(title="Import User Data", value="import"),
            *nav_choices(),
        ],
        style=BRAND_STYLE,
    ).ask()
    
    if action is None or action == "back":
        return "back"
    elif action == "home":
        return "home"
    elif action == "export":
        # Call existing export command
        from ...cli import export_userdata
        from rich.prompt import Confirm, Prompt
        
        router.console.print()
        out_path = Prompt.ask("Output path", default="exports/sx_userdata.jsonl.gz").strip()
        
        try:
            export_userdata(out=out_path, include_meta=True, include_notes=True)
        except Exception as e:
            router.console.print(f"\n[red]Error:[/red] {e}\n")
        
        Confirm.ask("Press Enter to continue", default=True, show_default=False)
        return "userdata_menu"
        
    elif action == "import":
        # Call existing import command
        from ...cli import import_userdata
        from rich.prompt import Confirm, Prompt
        
        router.console.print()
        in_path = Prompt.ask("Input path", default="exports/sx_userdata.jsonl.gz").strip()
        overwrite = Confirm.ask("Overwrite existing rows?", default=True)
        
        try:
            import_userdata(input_path=in_path, overwrite=overwrite, strict=False, max_rows=0)
        except Exception as e:
            router.console.print(f"\n[red]Error:[/red] {e}\n")
        
        Confirm.ask("Press Enter to continue", default=True, show_default=False)
        return "userdata_menu"
    
    return "back"
