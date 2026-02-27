# sxctl Refactor Map (Context-First Launcher)

This document captures the **intended flow** and the **file-by-file implementation map** for the `sxctl` refactor.

---

## ASCII flow (current launcher behavior)

```text
┌────────────────────────────┐
│ ./scripts/sxctl.sh (entrypoint)    │
└──────────────┬─────────────┘
               │
               ▼
      ┌───────────────────┐
      │ context exists?   │
      └───────┬───────────┘
              │yes
              ▼
     ┌───────────────────────┐
     │ load .sxctl/context   │
     │ export runtime env    │
     └──────────┬────────────┘
                │
                ▼
     ┌───────────────────────┐
     │ action stage          │
     │ - api serve/init/...  │
     │ - plugin build/install│
     │ - diagnostics         │
     └───────────────────────┘

              no
              │
              ▼
   ┌───────────────────────────────┐
   │ context init wizard           │
   │ 1) select profile index       │
   │ 2) validate vault root        │
   │    (must contain .obsidian/)  │
   │ 3) select DB backend          │
   │    sqlite | postgres          │
   │ 4) persist .sxctl/context.env │
   └──────────────┬────────────────┘
                  │
                  ▼
         ┌──────────────────┐
         │ continue to      │
         │ action stage     │
         └──────────────────┘
```

---

## Noninteractive flow

```text
SXCTL_NONINTERACTIVE=1
  + SXCTL_PROFILE_INDEX
  + SXCTL_VAULT_ROOT
  + SXCTL_DB_BACKEND
  (+ SXCTL_DB_PROFILE when postgres)
            │
            ▼
      deterministic init
      (no prompts; fail-fast)
            │
            ▼
        context saved
            │
            ▼
        action command
```

---

## File-by-file refactor map

### `scripts/sxctl.sh`

- Introduced **two-stage architecture**:
  - context stage (`context init/show/clear`, `ensure_context`)
  - action stage (`api`, `plugin`, `diagnostics`, menu)
- Added context persistence in `./.sxctl/context.env`.
- Added strict vault validation (`.obsidian/` required).
- Added deterministic noninteractive mode for automation.
- Added diagnostics for context validity, backend readiness, and API pid health.

### `scripts/profile_adapter.sh`

- Centralized profile/path/source/db derivation for launcher + Make targets.
- Supports SchedulerX key variants (`SRC_PROFILE_N`, `SRC_PATH_N`).
- Fixes runtime precedence bug:
  - env-file load now preserves already-exported runtime selections,
  - preventing profile index drift after selection.

### `scripts/Makefile`

- API/plugin targets now run through profile adapter context application.
- Each launch path prints effective targeting context for traceability.

### `docs/cli.md`

- Documents the context-first launcher model, noninteractive variables, and troubleshooting.

### `.gitignore`

- Ignores runtime context artifacts under `.sxctl/`.

### `tests/shell/sxctl_context.bats`

- Regression tests for:
  - explicit profile index retention,
  - noninteractive context write behavior,
  - invalid vault fail-fast,
  - postgres context capture.

### `.github/workflows/ci.yml`

- Adds shell-focused quality steps (lint/format/shell tests) alongside Python tests.

---

## Why this design

1. **No drift**: context is explicit and persisted.
2. **No ambiguous prompts**: backend selection is explicit (`sqlite|postgres`).
3. **Automation-safe**: noninteractive mode is deterministic.
4. **Plugin-safe backend evolution**: postgres path can be integrated without changing plugin contracts.
