"""Unit tests for UIState class."""
from __future__ import annotations

import pytest

from sx_db.tui.state import UIState


def test_uistate_initial_state():
    """Test UIState starts with default values."""
    state = UIState()
    
    assert state.last_source is None
    assert state.last_search_query is None
    assert state.last_import_csv is None
    assert state.last_import_source is None
    assert state.session_history == []
    assert state.import_wizard_step == 0
    assert state.import_wizard_data == {}


def test_uistate_remember():
    """Test remember() updates state attributes."""
    state = UIState()
    
    state.remember(last_source="default", last_search_query="test query")
    assert state.last_source == "default"
    assert state.last_search_query == "test query"


def test_uistate_remember_ignores_unknown():
    """Test remember() ignores unknown attributes."""
    state = UIState()
    
    # Should not raise an error
    state.remember(unknown_attr="value", last_source="default")
    assert state.last_source == "default"
    assert not hasattr(state, "unknown_attr")


def test_uistate_add_to_history():
    """Test adding screens to session history."""
    state = UIState()
    
    state.add_to_history("main_menu")
    state.add_to_history("sources_menu")
    state.add_to_history("import_wizard")
    
    assert state.session_history == ["main_menu", "sources_menu", "import_wizard"]


def test_uistate_clear_wizard_state():
    """Test clearing wizard state."""
    state = UIState()
    
    # Set some wizard state
    state.import_wizard_step = 3
    state.import_wizard_data = {"csv_path": "/path/to/file.csv"}
    
    # Clear it
    state.clear_wizard_state()
    
    assert state.import_wizard_step == 0
    assert state.import_wizard_data == {}


def test_uistate_session_workflow():
    """Test a complete session workflow."""
    state = UIState()
    
    # User navigates to import wizard
    state.add_to_history("main_menu")
    state.add_to_history("import_wizard")
    
    # User selects a source
    state.remember(last_import_source="my_source")
    
    # User completes import
    state.clear_wizard_state()
    
    # User searches
    state.add_to_history("search_menu")
    state.remember(last_search_query="travel videos")
    
    # Verify state
    assert state.last_import_source == "my_source"
    assert state.last_search_query == "travel videos"
    assert len(state.session_history) == 3
