# Profile-Targeted Recovery Runbook

Owner: @devops

## When to use this

Use this runbook when one profile/source is contaminated, mis-synced, or needs a clean rebuild without touching other profiles.

Typical symptoms:

- many media previews show not found for one profile only
- schema/source look correct in UI but notes/media are mismatched
- wrong CSV dataset appears to have been imported into the affected source

## Safety model

This flow is **profile-scoped** and uses explicit `source_id`, schema, and CSV paths for index `N`.

- It truncates only schema `*_N`
- It deletes only vault markdown under `VAULT_PATH_N/_db/**/*.md`
- It re-imports from `CSV_*_N` (or `ASSETS_PATH_N/xlsx_files/*` fallback)
- It refreshes notes only for `source_id` mapped to `N`

## One-command recovery (recommended)

Run from repo root:

- `./.venv/bin/python scripts/recover_profile.py --profile-index 2`

Dry run first (prints resolved source/schema/paths without changing data):

- `./.venv/bin/python scripts/recover_profile.py --profile-index 2 --dry-run`

## Advanced flags

- Skip reset but re-import + refresh:
  - `--skip-reset`
- Reset + import, but skip note refresh:
  - `--skip-refresh`
- Refresh only first N notes (smoke check):
  - `--limit 10`

## Manual fallback sequence

If you need to run each stage explicitly:

1. Stop API server processes (prevents lock contention)
2. Hard reset only affected profile schema/vault notes
3. Re-import with explicit `--source` + explicit CSV paths for that profile
4. Run `refresh-notes --source <source_id>`
5. Open Obsidian profile and run Sync / Clear + Re-sync to materialize vault notes

## Verification checklist

After recovery, verify all of the following:

1. API health for source header returns expected schema:
   - `X-SX-Source-ID: <source_id>` → `schema = expected`
2. `/items` total is non-zero for target source
3. `video_notes` count is populated for target schema after refresh
4. vault note folder starts empty after reset and repopulates only after plugin sync

## Common pitfall to avoid

`import-csv --source assets_2` can still pick profile-1 default CSV if CSV paths are not explicitly profile-scoped in invocation.

Always use explicit profile-targeted CSV paths during incident recovery.
