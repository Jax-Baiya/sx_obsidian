# Plugin Scalability Architecture (No-Break Refactor Plan)

Owner: @plugin

## Problem statement

The plugin currently has several very large files (`libraryView.ts`, `settings.ts`, `main.ts`) and repeated helper logic spread across modules. This increases cognitive load, slows debugging, and makes safe changes harder.

## Refactor goals

1. Keep all existing behavior stable while reducing file complexity.
2. Move pure helpers into shared modules first (low risk).
3. Introduce explicit boundaries so issues are easier to localize.

## Design principles

- **Strangler pattern for refactor**: extract gradually behind existing call sites.
- **Single responsibility**: keep UI orchestration separate from pure logic/helpers.
- **Functional core, imperative shell**:
  - pure modules for parsing/formatting/selection/validation
  - Obsidian side-effects at edges (view lifecycle, vault IO, notices, commands)
- **Behavior parity first**: no semantic changes during extraction phases.

## Current extracted modules (implemented)

- `obsidian-plugin/src/libraryCore.ts` (existing core utility layer)
- `obsidian-plugin/src/shared/vaultFs.ts`
  - `slugFolderName`
  - `collectMarkdownFiles`
  - `ensureFolder`
  - `ensureFolderDeep`
  - `clearMarkdownInFolder`
- `obsidian-plugin/src/shared/clipboard.ts`
  - `copyToClipboard`
- `obsidian-plugin/src/libraryTypes.ts`
  - `ApiItem`, `ApiAuthor`, `ApiNote`

These are now consumed by `actions.ts`, `settings.ts`, `main.ts`, and `libraryView.ts` to reduce duplication and make future extraction safer.

## Target module boundaries

### 1) `libraryView.ts` split (highest impact)

Planned submodules:

- `library/ui/hoverVideo.ts` (hover video lifecycle + positioning)
- `library/ui/hoverMarkdown.ts` (Ctrl/Cmd hover markdown preview)
- `library/ui/notePeek.ts` (inline/leaf/hover-editor/popout preview)
- `library/ui/tableSelection.ts` (selection orchestration + CSS state application)
- `library/ui/tableLayout.ts` (sticky offsets + freeze panes)
- `library/data/libraryApi.ts` (typed API calls used by the view)
- `library/vault/libraryVaultBridge.ts` (vault note lookup/update operations)

### 2) `settings.ts` split

Planned by tab:

- `settings/tabs/databaseTab.ts`
- `settings/tabs/profilesTab.ts`
- `settings/tabs/dataFlowTab.ts`
- `settings/tabs/viewsTab.ts`
- `settings/tabs/dangerTab.ts`
- `settings/tabs/advancedTab.ts`

### 3) `main.ts` split

- `plugin/commands.ts` (command registration)
- `plugin/routing.ts` (source/profile alignment + guards)
- `plugin/serverControl.ts` (shell/sxctl lifecycle helpers)
- `plugin/autopush.ts` (vault modify event handling)

## Safe migration sequence

1. Extract pure/shared helpers (done).
2. Extract type contracts (done).
3. Move one feature controller at a time from `libraryView.ts`, keeping method signatures stable.
4. Build after each extraction.
5. Add targeted tests for extracted pure modules.

## Phase completion status (this refactor wave)

- ✅ **Phase 1 — Utility extraction completed**
  - shared vault FS helpers
  - shared clipboard helper
  - shared frontmatter/meta parser
- ✅ **Phase 2 — Table/type contracts completed**
  - shared library API types
  - shared default table schema/order contracts
- ✅ **Phase 3 — UI bootstrap decomposition completed (safe slice)**
  - modal UI classes extracted from `main.ts` to `modals.ts`
  - `main.ts` now focuses more on plugin orchestration
- ✅ **Phase 4 — Architecture governance completed**
  - phase plan documented in this file
  - portability doc cross-links maintained

Additional completed controlled slices:

- `libraryView` link/protocol routing extracted to `shared/linkRouting.ts`
- `libraryView` note preview/frontmatter helpers extracted to `shared/notePreview.ts`
- `libraryView` Hover Editor integration extracted to `shared/hoverEditor.ts`
- `libraryView` vault note lookup/open helpers extracted to `shared/vaultNotes.ts`
- `libraryView` selection styling extracted to `shared/selectionUi.ts`
- `libraryView` hover video positioning extracted to `shared/hoverVideo.ts`
- `libraryView` sticky/freeze table layout extracted to `shared/tableLayout.ts`

Notes:

- All changes were done in small controlled slices with repeated plugin builds after each slice.
- No endpoint IDs, command IDs, or runtime routing semantics were changed.
- Final checkpoint build status: ✅ `obsidian-plugin` build passes (`[sx-obsidian-db] build complete`).

## Wave closure

This controlled modularization wave is complete for the low-risk extraction scope.

Remaining work (if pursued) should be treated as **next-phase optional refactor** focused on deeper controller decomposition inside `libraryView.ts` (higher-touch behavior surfaces).

## Change safety checklist

For every modularization PR:

1. No endpoint/command IDs changed.
2. Build passes (`obsidian-plugin` build).
3. No behavior changes unless explicitly intended.
4. Keep wrappers/shims until migration is complete.
5. Keep source/profile safety guard behavior untouched.
