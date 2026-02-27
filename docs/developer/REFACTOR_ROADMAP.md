# SX Obsidian Refactor Roadmap

This roadmap stabilizes the current feature set first, then incrementally modularizes the codebase for scale without losing behavior.

## Goals

- Preserve all current user-facing capabilities and data contracts
- Reduce risk in a large dirty worktree through staged, test-backed changes
- Improve maintainability via smaller modules and clearer boundaries
- Professionalize documentation structure and cross-linking

## Phase 0 — Stabilize Runtime (Current)

- [x] Split source/vault path handling (`SRC_PATH_N` vs `VAULT_N`)
- [x] Markdown template versioning + stale-cache regeneration
- [x] Add note cache refresh tooling (`refresh-notes`)
- [x] Harden plugin shell selection and protocol open/reveal fallbacks
- [x] Add focused regression tests for these flows

## Phase 1 — TUI Modularization

### Current pain

- `sx_db/tui/screens/database_management.py` contains mixed concerns:
  - profile selection
  - Prisma execution and lifecycle
  - process management
  - log UX rendering

### Target modules

- `sx_db/tui/prisma/commands.py` — command building + env prep
- `sx_db/tui/prisma/processes.py` — start/stop/status + PID handling
- `sx_db/tui/prisma/logs.py` — log path, tail, display formatting
- `sx_db/tui/prisma/actions.py` — action dispatch map
- `sx_db/tui/screens/database_management.py` — thin view/controller only

## Phase 2 — API/Render Separation

### Current pain

- `sx_db/api.py` mixes request routing, source resolution, render/cache behavior, and media path derivation

### Target modules

- `sx_db/services/source_resolution.py`
- `sx_db/services/media_paths.py`
- `sx_db/services/note_cache.py`
- `sx_db/services/group_links.py`

`api.py` should become orchestration only (route in/out + service calls).

## Phase 3 — Plugin Structure Cleanup

### Current pain

- `obsidian-plugin/src/libraryView.ts` is feature-rich but large

### Target modules

- `obsidian-plugin/src/library/actions/` (open/reveal, pin, metadata writes)
- `obsidian-plugin/src/library/renderers/` (table row/cell rendering)
- `obsidian-plugin/src/library/state/` (filters/sort/paging)
- `obsidian-plugin/src/library/io/` (API + local note helpers)

## Phase 4 — Docs Information Architecture

### Proposed doc tree

- `docs/architecture/`
  - `system-overview.md`
  - `data-flow.md`
  - `profile-routing.md`
- `docs/runbooks/`
  - `api-operations.md`
  - `prisma-operations.md`
  - `migration-split-paths.md`
- `docs/developer/`
  - `tui-development.md`
  - `plugin-development.md`
  - `testing-strategy.md`
- `docs/user/`
  - `quickstart.md`
  - `settings-guide.md`
  - `troubleshooting.md`

### Standards

- Every page includes: Purpose, Preconditions, Steps, Verification, Rollback
- Use relative links and add a docs index map in `docs/README.md`

## Safety Rules for Refactor Execution

- No behavior changes without regression tests added first
- Keep public CLI commands and API contracts backward-compatible unless versioned
- Refactor in slices (<500 LOC changed per PR where practical)
- Maintain migration notes for any env/config key changes

## Immediate Next Slices

1. Extract Prisma process control from `database_management.py`
2. Extract note-cache service from `api.py`
3. Split plugin open/reveal and author-fetch logic into dedicated modules
4. Rebuild docs navigation and add cross-links
