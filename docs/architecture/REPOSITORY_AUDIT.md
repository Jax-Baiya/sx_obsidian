# Repository Audit (2026-02-21)

Owner: @platform

## Executive summary

The repository is feature-rich but currently in a high-churn state with significant worktree drift, large multi-responsibility files, and fragmented documentation. The highest near-term risk is accidental regression during parallel refactors.

## Priority findings

### P0 — Stability and delivery risk

1. Dirty worktree with many staged/untracked functional surfaces (CLI, plugin, API, docs) increases merge conflict and release risk.
2. Oversized critical files with mixed responsibilities:
   - `obsidian-plugin/src/libraryView.ts` (~3726 LOC)
   - `sx_db/api.py` (~2240 LOC)
   - `obsidian-plugin/src/settings.ts` (~1834 LOC)
   - `sx_db/cli.py` (~1714 LOC)
3. Runtime behavior spread across CLI/TUI/plugin boundaries with partial duplication (open/reveal, profile routing, note refresh triggers).

### P1 — Maintainability and coupling

1. TUI screen modules contain both orchestration and low-level process logic.
2. Database management action/menu wiring was embedded in the same controller module.
3. Vault memory UX previously lacked deterministic single-item keyboard deletion.

### P2 — Docs and operational scalability

1. Documentation was broad but not consistently structured by audience/domain.
2. Top-level docs hub lacked explicit ownership and lifecycle conventions.
3. Existing runbooks and architecture references were not consistently grouped.

## Code smells and architecture hotspots

- Large classes/modules with mixed IO, business logic, and view rendering.
- Ad hoc helper duplication for path/profile handling.
- Tight coupling between user interaction and persistence concerns in TUI workflows.

## CI/DevOps gaps

- No enforced guardrail visible here for max-file-size or complexity budget.
- High-risk files do not appear to have explicit decomposition milestones in CI gates.
- Worktree hygiene checks (e.g., required clean tree before release build) are not documented as mandatory process.

## Recommendations

1. Continue staged extraction for heavy modules with behavior-preserving tests first.
2. Add CI checks for:
   - Lint + tests + type checks
   - Optional complexity/size warnings on hotspot files
3. Keep refactor slices small and reversible; document each move in migration notes.
4. Enforce docs ownership + update index on feature PRs.
