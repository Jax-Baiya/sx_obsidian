"""Reusable UI components for the TUI."""
from __future__ import annotations

from typing import TYPE_CHECKING

try:
    import questionary
    from questionary import Choice, Separator
except ImportError:  # pragma: no cover
    questionary = None  # type: ignore
    Choice = None  # type: ignore
    Separator = None  # type: ignore

try:
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
except ImportError:  # pragma: no cover
    # Fallback stubs
    class Panel:  # type: ignore
        @staticmethod
        def fit(content, **kwargs):
            return content
    
    class Table:  # type: ignore
        def __init__(self, **kwargs):
            pass

    class Text(str):  # type: ignore
        pass

if TYPE_CHECKING:
    from rich.console import Console

    from ..settings import Settings
    from .router import Router


# ═══════════════════════════════════════════════════════════════════════════════
# BRAND STYLING
# ═══════════════════════════════════════════════════════════════════════════════

BRAND_STYLE = None
if questionary is not None:
    BRAND_STYLE = questionary.Style([
        ("qmark", "fg:#00b4d8 bold"),         # Cyan accent
        ("question", "bold"),
        ("answer", "fg:#90e0ef bold"),         # Light cyan for answers
        ("highlighted", "fg:#00b4d8 bold"),    # Highlighted item
        ("pointer", "fg:#00b4d8 bold"),        # Arrow pointer
        ("selected", "fg:#90e0ef"),            # Selected item
    ])


# ═══════════════════════════════════════════════════════════════════════════════
# NAVIGATION HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def nav_choices(include_separator: bool = True) -> list:
    """Standard Back/Home navigation choices.

    Append to every screen's menu for consistent navigation.
    """
    choices: list = []
    if include_separator and Separator is not None:
        choices.append(Separator())
    if Choice is not None:
        choices.extend([
            Choice(title="← Back", value="back"),
            Choice(title="Home", value="home"),
        ])
    return choices


# ═══════════════════════════════════════════════════════════════════════════════
# WELCOME BANNER
# ═══════════════════════════════════════════════════════════════════════════════

_BANNER_ART = """\
[bold cyan]╔═══════════════════════════════════════════════════════════════╗
║                                                               ║
║     ███████╗██╗  ██╗    ██████╗ ██████╗                       ║
║     ██╔════╝╚██╗██╔╝    ██╔══██╗██╔══██╗                      ║
║     ███████╗ ╚███╔╝     ██║  ██║██████╔╝                      ║
║     ╚════██║ ██╔██╗     ██║  ██║██╔══██╗                      ║
║     ███████║██╔╝ ██╗    ██████╔╝██████╔╝                      ║
║     ╚══════╝╚═╝  ╚═╝    ╚═════╝ ╚═════╝                       ║
║                                                               ║
║     [white]SQLite Library for Obsidian[/white]                             ║
╚═══════════════════════════════════════════════════════════════╝[/bold cyan]"""


def render_welcome_banner(console: Console) -> None:
    """Render the styled ASCII welcome banner."""
    console.print(_BANNER_ART)
    console.print()


# ═══════════════════════════════════════════════════════════════════════════════
# HEADER (context bar below banner)
# ═══════════════════════════════════════════════════════════════════════════════

def render_header(console: Console, settings: Settings) -> None:
    """Render app header with database context and stats.
    
    Args:
        console: Rich Console for output
        settings: Application settings
    """
    from ..db import connect, init_db
    
    # Try to get DB stats
    try:
        conn = connect(settings.SX_DB_PATH)
        init_db(conn, enable_fts=settings.SX_DB_ENABLE_FTS)
        
        total = conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0]
        sources_count = conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
        db_exists = True
    except Exception:
        total, sources_count = 0, 0
        db_exists = False
    
    # Compact context bar
    if db_exists:
        content = (
            f"  [bold]DB[/bold] [dim]{settings.SX_DB_PATH}[/dim]  "
            f"[bold]Items[/bold] [cyan]{total:,}[/cyan]  "
            f"[bold]Sources[/bold] [cyan]{sources_count}[/cyan]  "
            f"[bold]API[/bold] [dim]http://{settings.SX_API_HOST}:{settings.SX_API_PORT}[/dim]"
        )
    else:
        content = (
            f"  [yellow]Database not initialized[/yellow]  "
            f"[dim]→ Run Setup to get started[/dim]"
        )
    
    console.print(Panel.fit(content, border_style="dim"))
    console.print()


def render_breadcrumbs(router: Router) -> None:
    """Render navigation breadcrumbs.
    
    Args:
        router: Router instance with navigator
    """
    breadcrumbs = router.nav.breadcrumbs()
    router.console.print(f"[dim]{breadcrumbs}[/dim]\n")


def render_result_panel(
    console: Console,
    message: str,
    stats: dict[str, str | int] | None = None,
    is_error: bool = False,
) -> None:
    """Render a success/failure outcome panel.
    
    Args:
        console: Rich Console for output
        message: Main result message
        stats: Optional statistics to display
        is_error: Whether this is an error result
    """
    if is_error:
        icon = "✗"
        style = "red"
    else:
        icon = "✓"
        style = "green"
    
    content = f"[bold {style}]{icon} {message}[/bold {style}]"
    
    if stats:
        content += "\n\n"
        content += "\n".join(f"  {k}: [cyan]{v:,}[/cyan]" if isinstance(v, int) else f"  {k}: [cyan]{v}[/cyan]" 
                            for k, v in stats.items())
    
    console.print(Panel.fit(content, title="Result" if not is_error else "Error"))
    console.print()


def render_error(
    console: Console,
    title: str,
    cause: str,
    action: str | None = None,
) -> None:
    """Render a friendly error panel with 3-part structure.
    
    Args:
        console: Rich Console for output
        title: Error title
        cause: What caused the error
        action: Suggested action to resolve
    """
    content = f"[bold red]✗ {title}[/bold red]\n\n"
    content += f"[yellow]Cause:[/yellow] {cause}\n"
    
    if action:
        content += f"\n[dim]→ {action}[/dim]"
    
    console.print(Panel.fit(content, border_style="red", title="Error"))
    console.print()


def render_stats_table(console: Console, stats: dict[str, str | int], title: str = "Stats") -> None:
    """Render a two-column statistics table.
    
    Args:
        console: Rich Console for output
        stats: Statistics to display
        title: Table title
    """
    table = Table(title=f"[bold]{title}[/bold]", show_header=False)
    table.add_column("Metric", style="bold")
    table.add_column("Value", style="cyan", justify="right")
    
    for key, value in stats.items():
        if isinstance(value, int):
            table.add_row(key, f"{value:,}")
        else:
            table.add_row(key, str(value))
    
    console.print(table)
    console.print()


def confirm_destructive_action(message: str, default: bool = False) -> bool:
    """Confirm a destructive action with explicit warning.
    
    Args:
        message: Confirmation message
        default: Default choice
        
    Returns:
        True if confirmed, False otherwise
    """
    try:
        from rich.prompt import Confirm
        return Confirm.ask(f"[yellow]⚠[/yellow]  {message}", default=default)
    except ImportError:  # pragma: no cover
        response = input(f"{message} (y/N): ").strip().lower()
        return response in ("y", "yes")
