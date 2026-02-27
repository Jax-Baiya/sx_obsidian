# Performance & Large Vault Safety

If Obsidian shows **“File system operation timed out”** while loading, it’s usually because the vault contains a directory with **too many files** for your storage + plugins to index quickly (common culprits: `_db/media/`, `_logs/`).

This project supports a scalable workflow: keep only an **active working set** of generated notes inside the vault, and archive the rest outside.

## Emergency recovery (vault won’t open)

1. Close Obsidian.
2. In your vault folder, temporarily rename the DB folder:
   - `_db` → `_db__DISABLED` (or just `_db/media` → `_db/media__DISABLED`)
3. Reopen Obsidian.

If the vault opens, you’ve confirmed `_db/media` was the bottleneck.

## Recommended long-term strategy

### Option A — Active set in vault + archive the rest (recommended)

Keep the vault lightweight by generating only what you actively work on (e.g., bookmarked items), and archive everything else.

Examples:

- Sync only bookmarked items (much fewer notes):
  - `./run.sh --mode sync --only-bookmarked`

- Sync a specific set of IDs:
  - Create `ids.txt` with one id per line
  - `./run.sh --mode sync --only-ids-file ids.txt`

- After syncing an active set, archive everything else out of the vault:
  - `./run.sh --mode sync --only-bookmarked --archive-stale`

Archived notes are moved to `ARCHIVE_DIR` (default: `./_archive/sx_obsidian_db/` next to the project).

> Safety: archiving skips "dirty" notes (manual edits) unless you pass `--force`.

### Option B — Separate vault for generated DB

Create a dedicated Obsidian vault folder for generated database notes (with minimal plugins). Point `VAULT` for a profile to that folder.

This keeps your main vault fast and makes the DB vault purpose-built for browsing.

## Plugin/indexing tips

- Dataview/Bases/Omnisearch can dramatically increase startup indexing time on large vaults.
- If you must keep many notes, consider disabling heavy plugins in the DB vault.
- Keep vaults on fast local storage when possible.
