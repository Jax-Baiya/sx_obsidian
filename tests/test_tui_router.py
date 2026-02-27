"""Unit tests for Router class."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from rich.console import Console

from sx_db.tui.navigator import Navigator
from sx_db.tui.router import Router, register_screen
from sx_db.tui.state import UIState


@pytest.fixture
def mock_settings():
    """Create mock settings."""
    settings = MagicMock()
    settings.SX_DB_PATH = "test.db"
    settings.SX_API_HOST = "127.0.0.1"
    settings.SX_API_PORT = 8123
    return settings


@pytest.fixture
def router_components(mock_settings):
    """Create router components for testing."""
    console = Console()
    state = UIState()
    nav = Navigator()
    router = Router(
        console=console,
        settings=mock_settings,
        state=state,
        nav=nav,
    )
    return router, state, nav


def test_router_initialization(router_components, mock_settings):
    """Test router initializes with correct components."""
    router, state, nav = router_components
    
    assert router.console is not None
    assert router.settings == mock_settings
    assert router.state == state
    assert router.nav == nav


def test_register_screen_decorator():
    """Test screen registration decorator."""
    from sx_db.tui.router import SCREENS
    
    # Clear existing screens for clean test
    original_screens = SCREENS.copy()
    SCREENS.clear()
    
    @register_screen("test_screen")
    def test_screen_fn(router):
        return "exit"
    
    assert "test_screen" in SCREENS
    assert SCREENS["test_screen"] == test_screen_fn
    
    # Restore original screens
    SCREENS.clear()
    SCREENS.update(original_screens)


def test_router_navigation_commands(router_components):
    """Test router handles navigation commands correctly."""
    router, state, nav = router_components
    
    # Test home command
    nav.push("sources_menu")
    nav.push("sources_add")
    assert nav.depth() == 3
    
    # Simulate home command (in actual run() this would come from screen)
    nav.home()
    assert nav.current() == "main_menu"
    assert nav.depth() == 1


def test_router_screen_history(router_components):
    """Test router records screen visits in state."""
    router, state, nav = router_components
    
    # Manually simulate what router.run() does
    state.add_to_history(nav.current())
    nav.push("sources_menu")
    state.add_to_history(nav.current())
    nav.push("import_wizard")
    state.add_to_history(nav.current())
    
    assert state.session_history == [
        "main_menu",
        "sources_menu",
        "import_wizard",
    ]


def test_router_unknown_screen_handling(router_components):
    """Test router handles unknown screens gracefully."""
    router, state, nav = router_components
    
    # Push an unknown screen
    nav.push("nonexistent_screen")
    assert nav.current() == "nonexistent_screen"
    
    # In actual router.run(), this would trigger nav.home()
    # We just verify the navigation state is trackable
    assert nav.depth() == 2


def test_router_normalize_nav_result_aliases():
    """Router should normalize common Back/Home label variants."""
    assert Router._normalize_nav_result("back") == "back"
    assert Router._normalize_nav_result("← Back") == "back"
    assert Router._normalize_nav_result("Home") == "home"
    assert Router._normalize_nav_result("main menu") == "home"
    assert Router._normalize_nav_result("some_screen") == "some_screen"


def test_router_does_not_push_duplicate_screen_ids(router_components):
    """Returning the current screen should refresh in-place, not grow the nav stack."""
    router, _, nav = router_components

    from sx_db.tui import router as router_module

    original = router_module.SCREENS.copy()
    calls = {"n": 0}

    def _main(_router):
        calls["n"] += 1
        return "main_menu" if calls["n"] == 1 else "exit"

    router_module.SCREENS.clear()
    router_module.SCREENS.update({"main_menu": _main})

    try:
        router.run()
        assert nav.depth() == 1
    finally:
        router_module.SCREENS.clear()
        router_module.SCREENS.update(original)
