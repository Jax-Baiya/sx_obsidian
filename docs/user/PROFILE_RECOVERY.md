# Profile-Targeted Recovery (User Guide)

Owner: @plugin

This guide explains how to safely recover **only one affected profile** when data gets mixed, media previews fail for one source, or vault notes for a single profile need a clean rebuild.

## What this does

The recovery command is profile-scoped by `N` and will:

1. Resolve profile mapping from `.env` (`SRC_PROFILE_N_ID`, schema, vault path, CSV paths)
2. Truncate only that profile schema in PostgreSQL
3. Delete only that profile vault markdown under `VAULT_PATH_N/_db/**/*.md`
4. Re-import CSVs for that profile only
5. Refresh notes for that profile/source only

## Safety first

- This is destructive for the selected profile (`N`) only.
- Always run **dry-run** first.
- Make sure `.env` has correct `VAULT_PATH_N` and `CSV_*_N` (or `ASSETS_PATH_N`).

## Commands

### 1) Preview resolved target (no changes)

- `make recover-profile-dry N=2`

### 2) Run full recovery for the affected profile

- `make recover-profile N=2`

### 3) Optional flags (pass through with `ARGS`)

- Dry-run via full target:
  - `make recover-profile N=2 ARGS="--dry-run"`
- Skip reset (import + refresh only):
  - `make recover-profile N=2 ARGS="--skip-reset"`
- Skip refresh (reset + import only):
  - `make recover-profile N=2 ARGS="--skip-refresh"`
- Smoke refresh first 10 notes:
  - `make recover-profile N=2 ARGS="--limit 10"`

## Direct Python commands (equivalent)

- `./.venv/bin/python scripts/recover_profile.py --profile-index 2 --dry-run`
- `./.venv/bin/python scripts/recover_profile.py --profile-index 2`

## After recovery (Obsidian)

1. Open the matching Obsidian profile/vault
2. In SX Library view, run **Sync** or **Clear + Re-sync**
3. Confirm notes are rebuilt under `_db/media_active` (or your configured active folder)

## Expected output markers

Look for these markers in terminal output:

- `PROFILE_RECOVERY_PLAN` (target/source/schema/path preview)
- `PROFILE_RECOVERY_DONE` (workflow completed)
- `backup_file=...` (JSON snapshot in `_logs/`)

## Troubleshooting

- If dry-run shows wrong source/schema/path, fix `.env` mapping keys for that `N` first.
- If media previews still fail after recovery, run plugin **Sync/Clear + Re-sync** to materialize fresh vault notes.
- If command cannot lock tables, stop active API processes and retry.
