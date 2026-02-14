# SX Library Portability Plan (Reuse as Shared Package)

This plan lets us reuse the SX Library experience across projects (e.g., SchedulerX frontend) **without destabilizing** the current `sx_obsidian` plugin.

## Why this is a great idea

SX Library now has mature UX primitives:

- high-density table layout
- sticky/frozen columns
- interactive inline metadata edits
- chip-based link rendering
- preview behaviors
- performance-oriented interaction constraints

These can be generalized and reused.

---

## Recommended architecture

Use an **extract-by-layer** approach instead of a big-bang migration.

### Layer 1: `@sx/library-core` (framework-agnostic)

Purpose: Pure TS utilities and contracts.

Includes:

- Column definitions and visibility/order models
- Selection state machine (single-mode selection)
- Validation rules (rating, URL-like fields)
- Link parsing/chip-label helpers
- Size-mode calculator for hover preview (`scale` vs `free`)

No DOM, no Obsidian API.

Current scaffold status:
- A versioned stable export object exists (`libraryCoreApi`, v1.0.0)
- Host adapter/contracts are defined for future app integration

### Layer 2: `@sx/library-ui-web` (web/frontend adapter)

Purpose: Shared browser UI components for non-Obsidian frontends.

Candidates:

- table shell
- header/column resize interactions
- link chip components
- hover-preview controller interfaces

Can target React first (SchedulerX likely), while keeping interface-compatible for plain TS/vanilla usage.

### Layer 3: `sx_obsidian` adapter (existing plugin)

Purpose: Keep Obsidian-specific integration in this repo:

- Obsidian view lifecycle
- Vault operations
- Obsidian commands/popovers
- Plugin settings storage

This layer consumes `library-core` and stays source-of-truth for Obsidian behavior.

---

## Migration phases

### Current status

- ✅ **Phase 1 (started/completed for first utility slice)** in `sx_obsidian` plugin:
	- Added shared core helper module: `obsidian-plugin/src/libraryCore.ts`
	- Moved pure utilities (link parsing/chip labels, URL validation, selection keying, hover-size calculation)
	- Added pure single-selection transition helpers (column/row/cell/table toggle semantics)
	- Added pure column-layout helpers (visibility check, order normalization, width sanitization)
	- Unified workflow status semantics into shared core (single source of truth for status lists/ranking)
	- Added shared tag normalization helpers used by SX Library vault/frontmatter sync paths
	- `libraryView.ts` now consumes these helpers through compatibility wrappers
	- Behavior preserved to avoid destabilizing current project

### Phase 1 (low risk, immediate)

Extract utility-only modules from current code into `library-core` candidates:

- link parsing + chip labels
- validation helpers
- preview size calculator
- selection state transitions

Keep behavior unchanged in `sx_obsidian` by importing extracted modules.

### Phase 2

Extract table model/state contracts:

- column schema
- row action contracts
- settings shape for reusable parts

### Phase 3

Build SchedulerX-first web package adapter that reuses the same core logic.

### Phase 4

Optional: publish private package(s) (GitHub Packages/registry) for org-wide reuse.

---

## Suggested monorepo layout (future)

- `packages/library-core/`
- `packages/library-ui-web/`
- `apps/sx-obsidian-plugin/`
- `apps/schedulerx-frontend/`

If monorepo is not desired now, start by vendoring `library-core` as a local package reference.

---

## Guardrails to avoid breaking current project

- Keep `sx_obsidian` plugin behavior as the reference implementation.
- Introduce extraction behind tests/snapshots before replacing local logic.
- Export only stable APIs from core package (no Obsidian types).
- Add compatibility shims in plugin during transition.

---

## SchedulerX fit (example)

SX Library’s table UX maps naturally to SchedulerX needs:

- content queue/workflow statuses
- per-item metadata edits
- preview + action pipelines
- compact, high-throughput operations interface

A SchedulerX frontend can reuse the same:

- selection logic
- validation logic
- link chip transformation
- hover preview sizing model

while providing a project-specific backend adapter.

---

## Recommendation

Yes — we should do this. The safest next step is **Phase 1 extraction of pure utilities** into a shared `library-core` module while keeping current plugin behavior intact.
