"""Unit tests for Navigator class."""
from __future__ import annotations

import pytest

from sx_db.tui.navigator import Navigator


def test_navigator_initial_state():
    """Test navigator starts at main menu."""
    nav = Navigator()
    assert nav.current() == "main_menu"
    assert nav.depth() == 1
    assert nav.breadcrumbs() == "Home"


def test_navigator_push():
    """Test pushing screens onto the stack."""
    nav = Navigator()
    
    nav.push("sources_menu")
    assert nav.current() == "sources_menu"
    assert nav.depth() == 2
    assert nav.breadcrumbs() == "Home > Sources"
    
    nav.push("sources_add")
    assert nav.current() == "sources_add"
    assert nav.depth() == 3
    assert nav.breadcrumbs() == "Home > Sources > Add Source"


def test_navigator_pop():
    """Test popping screens from the stack."""
    nav = Navigator()
    nav.push("sources_menu")
    nav.push("sources_add")
    
    popped = nav.pop()
    assert popped == "sources_add"
    assert nav.current() == "sources_menu"
    assert nav.depth() == 2
    
    popped = nav.pop()
    assert popped == "sources_menu"
    assert nav.current() == "main_menu"
    assert nav.depth() == 1


def test_navigator_pop_at_root():
    """Test popping at root returns None and doesn't change state."""
    nav = Navigator()
    
    popped = nav.pop()
    assert popped is None
    assert nav.current() == "main_menu"
    assert nav.depth() == 1


def test_navigator_home():
    """Test home resets to main menu."""
    nav = Navigator()
    nav.push("sources_menu")
    nav.push("sources_add")
    nav.push("import_wizard")
    
    nav.home()
    assert nav.current() == "main_menu"
    assert nav.depth() == 1
    assert nav.breadcrumbs() == "Home"


def test_navigator_unknown_screen():
    """Test unknown screens get generic labels in breadcrumbs."""
    nav = Navigator()
    nav.push("unknown_screen")
    
    assert nav.current() == "unknown_screen"
    assert nav.breadcrumbs() == "Home > unknown_screen"


def test_navigator_complex_navigation():
    """Test a complex navigation flow."""
    nav = Navigator()
    
    # Complex flow: main -> import -> back -> search -> home
    nav.push("import_wizard")
    assert nav.breadcrumbs() == "Home > Import Data"
    
    nav.pop()
    assert nav.breadcrumbs() == "Home"
    
    nav.push("search_menu")
    nav.push("search_results")
    assert nav.breadcrumbs() == "Home > Search > Results"
    
    nav.home()
    assert nav.breadcrumbs() == "Home"


def test_navigator_database_management_label():
    """Database management screen should have a friendly breadcrumb label."""
    nav = Navigator()
    nav.push("database_management")

    assert nav.current() == "database_management"
    assert nav.breadcrumbs() == "Home > Database management"
