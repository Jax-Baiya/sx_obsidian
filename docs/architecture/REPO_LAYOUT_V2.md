# Repository Layout V2 (Scaffold)

Status: **Phase 1 scaffold-only** (no runtime moves yet).

## Goals

- Separate runnable apps from reusable packages.
- Keep operational scripts stable.
- Preserve backward compatibility during migration.

## Boundaries

### `apps/`
Runtime products and user-facing app surfaces.

### `packages/`
Reusable Python package code (`sx`, `sx_db`, `sx_scheduler`) in future phases.

### `scripts/`
Stable operator entrypoints and wrappers; remains backward-compatible.

### `compat/`
Temporary compatibility layer for legacy import paths and wrappers.

### `infra/`
Infrastructure and deployment-adjacent assets.

## Migration Safety Rules

1. Move-only first; no logic/behavior changes.
2. Keep existing commands/imports working using shims and wrappers.
3. Validate after each phase with tests + smoke checks.
4. Use small, traceable commits.
