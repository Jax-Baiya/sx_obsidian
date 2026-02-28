"""Main router and screen registry for the TUI."""
from __future__ import annotations

from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from rich.console import Console

    from ..settings import Settings
    from .navigator import Navigator
    from .state import UIState


class Router:
    """Main navigation loop with screen dispatch.
    
    The router maintains the main event loop and dispatches to registered
    screen functions based on the current navigation state.
    """
    
    def __init__(
        self,
        console: Console,
        settings: Settings,
        state: UIState,
        nav: Navigator,
    ):
        """Initialize router with dependencies.
        
        Args:
            console: Rich Console for output
            settings: Application settings
            state: UI session state
            nav: Navigator instance
        """
        self.console = console
        self.settings = settings
        self.state = state
        self.nav = nav
    
    def run(self) -> None:
        """Run the main navigation loop.
        
        Dispatches to screen functions until "exit" is received.
        Handles navigation commands: exit, home, back, or screen_id.
        """
        while True:
            current_screen = self.nav.current()
            self.state.add_to_history(current_screen)
            
            # Get screen function from registry
            screen_fn = SCREENS.get(current_screen)
            
            if screen_fn is None:
                # Unknown screen - reset to home
                self.console.print(
                    f"[yellow]Warning:[/yellow] Unknown screen '{current_screen}', "
                    "returning to main menu"
                )
                self.nav.home()
                continue
            
            # Execute screen and get navigation command
            try:
                result = screen_fn(self)
            except KeyboardInterrupt:
                # Graceful Ctrl+C handling
                self.console.print("\n[dim]👋 Interrupted. Returning to main menu...[/]")
                self.nav.home()
                continue
            
            result = self._normalize_nav_result(result)

            # Handle navigation result
            if result == "exit":
                self.console.print("\n[dim]👋 Goodbye![/]")
                break
            elif result == "home":
                self.nav.home()
            elif result == "back":
                if self.nav.depth() > 1:
                    self.nav.pop()
                else:
                    self.nav.home()
            elif result:
                # Navigate to new screen. Avoid duplicate pushes when a screen
                # returns itself to indicate "refresh"; duplicate stack entries
                # make Back appear broken.
                if result != current_screen:
                    self.nav.push(result)
            # If result is None/empty, stay on current screen

    @staticmethod
    def _normalize_nav_result(result: str | None) -> str | None:
        """Normalize common nav aliases/titles to canonical commands.

        Some prompts may accidentally return rendered labels such as
        "← Back" instead of the internal value "back".
        """
        if result is None:
            return None
        s = str(result).strip().lower()
        if not s:
            return None
        if s in {"back", "← back", "< back", "go back", "previous", "prev", "b"}:
            return "back"
        if s in {"home", "main", "main menu", "h"}:
            return "home"
        return str(result)


# Screen registry - maps screen IDs to handler functions
# Will be populated as screen modules are implemented
SCREENS: dict[str, Callable[[Router], str | None]] = {}


def register_screen(screen_id: str):
    """Decorator to register a screen function.
    
    Usage:
        @register_screen("main_menu")
        def show_main_menu(router: Router) -> str | None:
            ...
    """
    def decorator(fn: Callable[[Router], str | None]):
        SCREENS[screen_id] = fn
        return fn
    return decorator
