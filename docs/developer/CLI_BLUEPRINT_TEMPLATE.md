# Screen-Based TUI Blueprint — Reusable Template

> Extracted from the sx_obsidian project's Navigator/Router/UIState architecture. Use this when building tools that need **multi-screen navigation**, session memory, and rich terminal UI. For simpler tools (linear workflows), see the DocuMorph blueprint instead.

---

## When to Use This Pattern vs DocuMorph's

| Scenario | Use This Blueprint | Use DocuMorph Blueprint |
|---|---|---|
| Multi-screen navigation (back/forward/home) | ✓ | |
| Wizard-style multi-step flows | ✓ | |
| Session state across screens | ✓ | |
| Many distinct features/views | ✓ | |
| Simple file-in → file-out processing | | ✓ |
| Linear menus (pick → do → repeat) | | ✓ |

---

## 1. Project Scaffold

```
my_tool/
├── main.py                     # Entry point
├── .env                        # Config defaults
├── requirements.txt
└── src/
    ├── __init__.py
    ├── settings.py             # Pydantic Settings
    ├── cli.py                  # Typer CLI (direct commands)
    └── tui/
        ├── __init__.py         # Exports Navigator, Router, UIState
        ├── navigator.py        # Stack-based navigation
        ├── router.py           # Event loop + @register_screen
        ├── state.py            # Session state dataclass
        ├── components.py       # Reusable Rich widgets
        └── screens/
            ├── __init__.py     # Import all screens to register
            ├── main.py         # Main menu
            ├── feature_a.py    # First feature screen
            └── feature_b.py    # Second feature screen
```

---

## 2. Core Dependencies

```txt
typer>=0.9.0              # CLI commands (direct invocations)
questionary>=2.0.0        # Interactive select menus (TUI screens)
rich>=13.0.0              # Panels, tables, progress, styled output
pydantic-settings>=2.0.0  # Typed env-driven config
python-dotenv>=1.0.0      # .env loading
```

---

## 3. Key Patterns

### 3.1 Navigator (`tui/navigator.py`)

```python
"""Stack-based navigation with breadcrumbs."""

class Navigator:
    SCREEN_LABELS = {
        "main_menu": "Home",
        "feature_a": "Feature A",
        "feature_b": "Feature B",
        # Add labels for all screens
    }
    
    def __init__(self):
        self.stack: list[str] = ["main_menu"]
    
    def push(self, screen: str) -> None:
        self.stack.append(screen)
    
    def pop(self) -> str | None:
        if len(self.stack) > 1:
            return self.stack.pop()
        return None
    
    def home(self) -> None:
        self.stack = ["main_menu"]
    
    def current(self) -> str:
        return self.stack[-1]
    
    def breadcrumbs(self) -> str:
        labels = [self.SCREEN_LABELS.get(s, s) for s in self.stack]
        return " > ".join(labels)
    
    def depth(self) -> int:
        return len(self.stack)
```

### 3.2 Router (`tui/router.py`)

```python
"""Main event loop with screen dispatch."""
from typing import Callable

class Router:
    def __init__(self, console, settings, state, nav):
        self.console = console
        self.settings = settings
        self.state = state
        self.nav = nav
    
    def run(self) -> None:
        while True:
            current = self.nav.current()
            self.state.add_to_history(current)
            
            screen_fn = SCREENS.get(current)
            if screen_fn is None:
                self.console.print(f"[yellow]Unknown screen: {current}[/]")
                self.nav.home()
                continue
            
            try:
                result = screen_fn(self)
            except KeyboardInterrupt:
                self.console.print("\n[dim]Interrupted. Returning to menu...[/]")
                self.nav.home()
                continue
            
            if result == "exit":
                self.console.print("\n[dim]Goodbye![/]")
                break
            elif result == "home":
                self.nav.home()
            elif result == "back":
                self.nav.pop()
            elif result:
                self.nav.push(result)

# Screen registry
SCREENS: dict[str, Callable] = {}

def register_screen(screen_id: str):
    """Decorator to register a screen function."""
    def decorator(fn):
        SCREENS[screen_id] = fn
        return fn
    return decorator
```

### 3.3 Session State (`tui/state.py`)

```python
"""Session state for remembering user choices across screens."""
from dataclasses import dataclass, field

@dataclass
class UIState:
    # Smart defaults (pre-fill with last-used values)
    last_source: str | None = None
    last_search_query: str | None = None
    
    # Wizard state (multi-step flows)
    wizard_step: int = 0
    wizard_data: dict = field(default_factory=dict)
    
    # Analytics
    session_history: list[str] = field(default_factory=list)
    
    def remember(self, **kwargs) -> None:
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
    
    def add_to_history(self, screen: str) -> None:
        self.session_history.append(screen)
    
    def clear_wizard(self) -> None:
        self.wizard_step = 0
        self.wizard_data = {}
```

### 3.4 Reusable Components (`tui/components.py`)

```python
"""Reusable UI widgets."""
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Confirm

# Custom questionary styling — apply to ALL select/text calls
import questionary
BRAND_STYLE = questionary.Style([
    ('qmark', 'fg:#00b4d8 bold'),
    ('question', 'bold'),
    ('answer', 'fg:#90e0ef bold'),
    ('highlighted', 'fg:#00b4d8 bold'),
    ('pointer', 'fg:#00b4d8 bold'),
])

def render_header(console, settings) -> None:
    """App header with context info."""
    content = (
        f"[bold cyan]MyTool[/bold cyan] — Description\n\n"
        f"  Context: [dim]{settings.SOME_PATH}[/dim]"
    )
    console.print(Panel.fit(content, border_style="cyan"))
    console.print()

def render_breadcrumbs(router) -> None:
    """Navigation breadcrumbs."""
    router.console.print(f"[dim]{router.nav.breadcrumbs()}[/dim]\n")

def render_result(console, message, stats=None, is_error=False) -> None:
    """Success/failure outcome panel."""
    icon, style = ("✗", "red") if is_error else ("✓", "green")
    content = f"[bold {style}]{icon} {message}[/bold {style}]"
    if stats:
        content += "\n\n" + "\n".join(
            f"  {k}: [cyan]{v:,}[/cyan]" if isinstance(v, int) 
            else f"  {k}: [cyan]{v}[/cyan]"
            for k, v in stats.items()
        )
    console.print(Panel.fit(content, title="Error" if is_error else "Result"))
    console.print()

def render_error(console, title, cause, action=None) -> None:
    """3-part error panel: what / why / fix."""
    content = f"[bold red]✗ {title}[/bold red]\n\n"
    content += f"[yellow]Cause:[/yellow] {cause}\n"
    if action:
        content += f"\n[dim]→ {action}[/dim]"
    console.print(Panel.fit(content, border_style="red", title="Error"))
    console.print()

def confirm_destructive(message, default=False) -> bool:
    """Confirm a destructive action."""
    return Confirm.ask(f"[yellow]⚠[/yellow]  {message}", default=default)

# Standard navigation choices (append to every screen's menu)
from questionary import Choice, Separator

def nav_choices(include_separator=True):
    """Standard back/home navigation choices."""
    choices = []
    if include_separator:
        choices.append(Separator())
    choices.extend([
        Choice(title="← Back", value="back"),
        Choice(title="Home", value="home"),
    ])
    return choices
```

### 3.5 Screen Template (`tui/screens/feature_a.py`)

```python
"""Feature A screen."""
import questionary
from questionary import Choice

from ..components import render_breadcrumbs, render_result, nav_choices, BRAND_STYLE
from ..router import register_screen

@register_screen("feature_a")
def show_feature_a(router):
    """Feature A screen.
    
    Returns: Navigation command (screen_id, "back", "home", "exit", or None)
    """
    router.console.clear()
    render_breadcrumbs(router)
    
    # Your screen content here
    router.console.print("[bold]Feature A[/bold]\n")
    
    # Action menu
    action = questionary.select(
        "Choose action:",
        choices=[
            Choice(title="Do Something", value="do_it"),
            Choice(title="Sub-Feature", value="sub_feature"),
            *nav_choices(),
        ],
        style=BRAND_STYLE,
    ).ask()
    
    if action is None or action == "back":
        return "back"
    elif action == "home":
        return "home"
    elif action == "do_it":
        _do_something(router)
        return "feature_a"  # Refresh
    elif action == "sub_feature":
        return "sub_feature"  # Push to sub-screen
    
    return "back"


def _do_something(router) -> None:
    """Inline action (doesn't navigate away)."""
    from rich.prompt import Confirm
    
    # Your logic here
    render_result(router.console, "Done!", stats={"Items": 42})
    Confirm.ask("Press Enter to continue", default=True, show_default=False)
```

### 3.6 Wizard Screen Template

```python
"""Multi-step wizard pattern."""
import questionary
from questionary import Choice
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.prompt import Confirm

from ..components import render_breadcrumbs, render_result, BRAND_STYLE
from ..router import register_screen

@register_screen("my_wizard")
def show_wizard(router):
    router.console.clear()
    render_breadcrumbs(router)
    
    # Step 1: Select something
    option = questionary.select(
        "Step 1: Choose target",
        choices=[
            Choice(title="Option A", value="a"),
            Choice(title="Option B", value="b"),
            Choice(title="← Back", value="__back__"),
        ],
        style=BRAND_STYLE,
    ).ask()
    
    if option == "__back__" or option is None:
        return "back"
    
    # Step 2: Confirm
    router.console.print(f"\n[bold]Summary:[/bold]\n  Target: [cyan]{option}[/cyan]\n")
    if not Confirm.ask("Proceed?", default=True):
        return "back"
    
    # Step 3: Execute with progress
    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=router.console,
        ) as progress:
            progress.add_task("Processing...", total=None)
            result = do_work(option)  # Your logic
        
        render_result(router.console, "Complete!", stats=result)
    except Exception as e:
        render_result(router.console, f"Failed: {e}", is_error=True)
        Confirm.ask("Press Enter to return", default=True, show_default=False)
        return "back"
    
    # Step 4: What next?
    next_action = questionary.select(
        "What next?",
        choices=[
            Choice(title="Do More", value="my_wizard"),
            Choice(title="Home", value="home"),
        ],
        style=BRAND_STYLE,
    ).ask()
    
    return next_action or "home"
```

### 3.7 Screen Registration (`tui/screens/__init__.py`)

```python
"""Import all screens to register them with the router."""
from . import main, feature_a, feature_b

__all__ = ["main", "feature_a", "feature_b"]
```

Adding a new screen = create file + add import here. That's it.

### 3.8 Entry Point + CLI Coexistence

```python
"""Entry point with both CLI commands AND interactive TUI."""
import typer
from rich.console import Console

app = typer.Typer(help="MyTool: description")
console = Console()

# Direct commands for power users
@app.command("status")
def status():
    """Show current status."""
    console.print("[green]✓[/green] All good")

@app.command("run")
def run():
    """Start server."""
    # ...

# Interactive TUI for everyone else
@app.callback(invoke_without_command=True)
def _root(ctx: typer.Context):
    """Launch interactive TUI when no command is given."""
    if ctx.invoked_subcommand is None:
        _launch_tui()
        raise typer.Exit()

def _launch_tui():
    from .tui.navigator import Navigator
    from .tui.router import Router
    from .tui.state import UIState
    from .tui import screens  # noqa: F401 (triggers registration)
    from .settings import load_settings

    settings = load_settings()
    router = Router(
        console=console,
        settings=settings,
        state=UIState(),
        nav=Navigator(),
    )
    try:
        router.run()
    except KeyboardInterrupt:
        console.print("\n[dim]Goodbye![/]")
```

---

## 4. UX Principles

| Principle | Implementation |
|---|---|
| **Breadcrumbs always visible** | `render_breadcrumbs(router)` at the top of every screen |
| **Back + Home on every screen** | `nav_choices()` appended to every menu |
| **Clear + redraw on navigation** | `router.console.clear()` at start of each screen |
| **Session memory** | `state.remember(last_x=value)` after every user choice |
| **Wizard pattern for multi-step** | Summary → Confirm → Progress → Result → Next-actions |
| **Semantic icons only** | `✓` success, `✗` error, `⚠` warning, `★` bookmarked — nothing decorative |
| **3-part error panels** | What happened / Why / What to do next |
| **Ctrl+C never crashes** | Router catches `KeyboardInterrupt` → nav.home() |
| **Custom brand styling** | `BRAND_STYLE` applied to all questionary calls |
| **Auto-detect first run** | Check if config/DB exists → redirect to setup wizard |

---

## 5. Adding a New Screen

1. Create `tui/screens/my_screen.py`
2. Add `@register_screen("my_screen")` decorator
3. Import in `tui/screens/__init__.py`
4. Add `Navigator.SCREEN_LABELS["my_screen"] = "My Screen"` for breadcrumbs
5. Add a menu item pointing to `"my_screen"` in the parent screen

That's it. No wiring, no registration boilerplate.

---

## 6. Common Gotchas

| Gotcha | Solution |
|---|---|
| Screen function returns `None` | Router stays on current screen — use for "refresh" |
| Forgot to import screen module | Screen won't register — add to `screens/__init__.py` |
| `questionary` returns `None` on Ctrl+C | Always check `if result is None: return "back"` |
| Wizard state persists after cancel | Call `state.clear_wizard()` on cancel/completion |
| `console.clear()` clears breadcrumbs | Call `clear()` first, then `render_breadcrumbs()` |
| CLI and TUI share Settings singleton | Both import `load_settings()` — they get the same instance |
