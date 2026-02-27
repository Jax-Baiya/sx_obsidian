"""Search screen."""
from __future__ import annotations

from typing import TYPE_CHECKING

try:
    import questionary
    from questionary import Choice
    from rich.prompt import Prompt
    from rich.table import Table
except ImportError:  # pragma: no cover
    questionary = None  # type: ignore

from ..components import BRAND_STYLE, nav_choices, render_breadcrumbs
from ..router import register_screen

if TYPE_CHECKING:
    from ..router import Router


@register_screen("search_menu")
def show_search_menu(router: Router) -> str | None:
    """Interactive search interface.
    
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
    
    # Get search query (pre-fill with last search if available)
    default_query = router.state.last_search_query or ""
    
    query = Prompt.ask(
        "Search query (leave empty to browse all)",
        default=default_query
    ).strip()
    
    router.state.remember(last_search_query=query)
    
    # Perform search
    from ...db import connect, get_default_source_id, init_db
    from ...search import search
    
    conn = connect(router.settings.SX_DB_PATH)
    init_db(conn, enable_fts=router.settings.SX_DB_ENABLE_FTS)
    
    source_id = get_default_source_id(
        conn,
        router.settings.SX_DEFAULT_SOURCE_ID or "default"
    )
    
    try:
        results = search(conn, query, limit=25, offset=0, source_id=source_id)
    except Exception as e:
        router.console.print(f"\n[red]Search error:[/red] {e}\n")
        from rich.prompt import Confirm
        Confirm.ask("Press Enter to return", default=True, show_default=False)
        return "back"
    
    # Display results
    if not results:
        router.console.print(f"\n[yellow]No results found for:[/yellow] {query or '(all)'}")
        router.console.print("[dim]Try a different query or check your source.[/dim]\n")
    else:
        table = Table(title=f"[bold]Search Results: [cyan]{query or '(all)'}[/cyan][/bold]")
        table.add_column("ID", style="cyan", no_wrap=True)
        table.add_column("★", justify="center", width=2)
        table.add_column("Author", style="magenta", max_width=20)
        table.add_column("Caption", max_width=60)
        
        for r in results:
            table.add_row(
                str(r.get("id", "")),
                "★" if r.get("bookmarked") else "",
                str(r.get("author_unique_id") or r.get("author_name") or "")[:20],
                str(r.get("snippet") or "")[:60],
            )
        
        router.console.print(table)
        router.console.print(f"\n[dim]Showing {len(results)} results[/dim]\n")
    
    # Next actions
    action = questionary.select(
        "What next?",
        choices=[
            Choice(title="New Search", value="again"),
            *nav_choices(),
        ],
        style=BRAND_STYLE,
    ).ask()
    
    if action == "again":
        return "search_menu"  # Restart search
    elif action == "home":
        return "home"
    else:
        return "back"
