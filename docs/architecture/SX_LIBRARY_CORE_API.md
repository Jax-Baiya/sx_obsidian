# SX Library Core API (Phase-2 Scaffold)

`obsidian-plugin/src/libraryCore.ts` now exposes a stable, framework-agnostic API surface intended for cross-project reuse.

## Purpose

- Keep `sx_obsidian` stable while preparing reusable logic for other projects (e.g., SchedulerX frontend).
- Centralize pure table/workflow/link/validation behavior in one place.

## Stable export

- `libraryCoreApi` (versioned: `1.0.0`)

Includes:
- Hover preview sizing: `computeHoverVideoSizePx`
- Links: `parseLinksValue`, `formatLinkChipLabel`, `validateHttpUrlLike`
- Tags: `normalizeTagToken`, `normalizeTagsValue`
- Workflow: `workflowStatuses`, `choosePrimaryWorkflowStatus`
- Keyboard chipify: `shouldCommitLinkChipOnKey`
- Selection model: `cellSelectionKey`, `clearSingleSelectionState`, and single-mode transition helpers
- Column layout: `hasAnyVisibleColumns`, `sanitizeColumnOrder`, `sanitizeColumnWidths`

## Contracts

### `LibraryCoreHostAdapter`
Optional host capabilities that external apps can provide:
- `now()`
- `openExternalUrl(url)`
- `copyToClipboard(text)`

### `LibraryCoreSelectionSnapshot`
Portable representation of selection state for UI adapters.

### `LibraryCoreMediaPreviewConfig`
Portable preview size config (`scale` vs `free` + dimensions/scale).

## Notes

- This scaffold is non-breaking and additive.
- Existing `sx_obsidian` behavior is preserved.
- Future adapters can import either individual helpers or `libraryCoreApi`.
