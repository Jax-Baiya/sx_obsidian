"""Navigation stack manager for screen-based routing."""
from __future__ import annotations


class Navigator:
    """Stack-based navigation with breadcrumbs.
    
    Manages the navigation stack following chisel's router model:
    - Push on enter: navigating forward pushes to stack
    - Pop on Back: returns to previous screen
    - Reset on Home: clears stack to ["main_menu"]
    - Exit from anywhere: graceful shutdown
    """
    
    # Screen ID to human-readable label mapping
    SCREEN_LABELS = {
        "main_menu": "Home",
        "sources_menu": "Sources",
        "sources_add": "Add Source",
        "import_wizard": "Import Data",
        "database_management": "Database management",
        "database_management_advanced": "Database management (Advanced)",
        "api_control": "API Server",
        "build_deploy": "Build & Deploy",
        "install_plugin": "Install Plugin",
        "settings": "Settings",
        "search_menu": "Search",
        "search_results": "Results",
        "help": "Help",
        "userdata_menu": "User Data",
    }
    
    def __init__(self):
        """Initialize with main menu as the starting screen."""
        self.stack: list[str] = ["main_menu"]
    
    def push(self, screen: str) -> None:
        """Navigate to a new screen by pushing onto the stack.
        
        Args:
            screen: Screen identifier to navigate to
        """
        self.stack.append(screen)
    
    def pop(self) -> str | None:
        """Go back to the previous screen.
        
        Returns:
            The screen that was popped, or None if at root
        """
        if len(self.stack) > 1:
            return self.stack.pop()
        return None
    
    def home(self) -> None:
        """Reset navigation to the main menu."""
        self.stack = ["main_menu"]
    
    def current(self) -> str:
        """Get the current screen identifier.
        
        Returns:
            Current screen ID
        """
        return self.stack[-1]
    
    def breadcrumbs(self) -> str:
        """Generate breadcrumb navigation string.
        
        Returns:
            Breadcrumb path like "Home > Sources > Add Source"
        """
        labels = [
            self.SCREEN_LABELS.get(screen, screen)
            for screen in self.stack
        ]
        return " > ".join(labels)
    
    def depth(self) -> int:
        """Get the current navigation depth.
        
        Returns:
            Number of screens in the stack
        """
        return len(self.stack)
