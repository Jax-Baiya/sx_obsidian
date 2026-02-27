# Migration: Active-only vault write strategy

This guide helps you migrate from the legacy “split folders” workflow (writing notes into both `_db/bookmarks/` and `_db/authors/`) to the **Active-only** strategy, where the vault has a single canonical location for DB-materialized notes.

## Why migrate?

Active-only fixes the main source of duplicate note accumulation:

- **Before**: pull/sync could write the same note ID into multiple vault locations.
- **After**: pull/sync writes to **one** folder only (default: `_db/media_active/`).

It also makes “vault → DB” push behavior deterministic (one file per ID).

## Preconditions

- You’re on a plugin version that includes **Vault write strategy** and the **Consolidate legacy notes → active folder (dedupe)** command.
- Your active notes folder is set (default: `_db/media_active`).

## Migration steps

### 1) Switch to Active-only

In Obsidian:

- Settings → Community Plugins → **SX Obsidian DB** → **Sync** tab
- Set **Vault write strategy** to **Active-only**

From this point forward:

- **Sync selection → vault** writes only to your Active notes folder.
- **Fetch (DB → vault)** writes only to your Active notes folder.

### 2) Consolidate legacy folders (dedupe)

Run the consolidation tool to merge old notes into the Active folder:

- Settings → SX Obsidian DB → **Sync** tab → **Consolidate now**
  - or Command palette → **SX: Consolidate legacy notes → active folder (dedupe)**

What it does:

- Moves/merges legacy notes from `_db/bookmarks/` and `_db/authors/…` into `_db/media_active/`.
- If multiple files share the same ID, it keeps one canonical copy and archives the rest into:
  - `_db/_archive_legacy_notes/<timestamp>/…`

### 3) Verify

A quick sanity check inside the vault:

- Confirm notes exist under `_db/media_active/<id>.md`.
- Confirm legacy duplicates were archived under `_db/_archive_legacy_notes/…`.

If you had custom manual edits, consolidation uses the same “preserve user edits” merge behavior used elsewhere in the plugin.

## Notes on autosave (vault → DB)

If **Auto-push edits to DB** is enabled:

- In **Active-only** mode, the plugin will *still* auto-push edits from legacy `_db/bookmarks/` and `_db/authors/…` folders by default (compatibility during migration).
- If you want strict canonical behavior, disable: **Auto-push legacy folders in Active-only mode**.

If you want legacy folders to remain first-class, switch **Vault write strategy** back to **Split**.

## Rollback

You can switch back any time:

- Settings → SX Obsidian DB → Sync tab → **Vault write strategy** → **Split**

This restores legacy routing behavior for pull/sync operations.
