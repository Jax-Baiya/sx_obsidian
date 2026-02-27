# Migration Notes — 2026-02-21

Owner: @cli

## Scope

Behavior-preserving modularization and TUI UX hardening.

## Changes

1. Added in-list remembered-vault deletion UX in `sx_db/tui/screens/build_deploy.py`.
2. Added keyboard handling for delete workflow:
   - Primary: `Delete`
   - Fallbacks: `Backspace`, `d`
3. Added deterministic deletion state helper: `_delete_memory_at_cursor(...)`.
4. Added focused tests in `tests/test_tui_vault_memory.py`.
5. Extracted database action/menu configuration from
   `sx_db/tui/screens/database_management.py` to
   `sx_db/tui/screens/database_management_menu.py`.

## Compatibility

- No CLI command names changed.
- No API contract changes.
- Existing navigation flow preserved.

## Rollback (module-level)

1. Revert `sx_db/tui/screens/build_deploy.py` to previous memory-management flow.
2. Remove `sx_db/tui/screens/database_management_menu.py` and inline choices/handlers back in `database_management.py`.
3. Re-run focused TUI tests.
