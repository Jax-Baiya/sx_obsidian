"""Session state for remembering user choices across screens."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class UIState:
    """UI session state - remembers user preferences and last choices.
    
    This state persists across screen transitions during a single TUI session,
    enabling smart defaults and improved UX.
    """
    
    # Last selected values (smart defaults)
    last_source: str | None = None
    last_search_query: str | None = None
    last_import_csv: str | None = None
    last_import_source: str | None = None
    
    # Session history for analytics/debugging
    session_history: list[str] = field(default_factory=list)
    
    # Import wizard state (multi-step)
    import_wizard_step: int = 0
    import_wizard_data: dict = field(default_factory=dict)

    # Generic cross-screen data store
    data: dict = field(default_factory=dict)

    # Active database server: "local" or "cloud"
    active_db_server: str = "local"
    
    def remember(self, **kwargs) -> None:
        """Update state with new values.
        
        Args:
            **kwargs: Attributes to update (e.g., last_source="my_source")
        
        Example:
            state.remember(last_source="default", last_search_query="travel")
        """
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
    
    def add_to_history(self, screen: str) -> None:
        """Record screen visit in session history.
        
        Args:
            screen: Screen identifier that was visited
        """
        self.session_history.append(screen)
    
    def clear_wizard_state(self) -> None:
        """Reset wizard state (called when wizard completes or is cancelled)."""
        self.import_wizard_step = 0
        self.import_wizard_data = {}
