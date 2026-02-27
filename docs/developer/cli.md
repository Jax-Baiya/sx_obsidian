# sxctl CLI Guide

`sxctl` now uses a two-stage flow:

1. **Context setup** (profile + vault root + DB backend) and save to `./.sxctl/context.env`
2. **Actions menu** that reuses saved context without re-prompting

This prevents profile drift between commands and keeps API/plugin operations aligned.

## Commands

- `./scripts/sxctl.sh` (same as `./scripts/sxctl.sh menu`)
- `./scripts/sxctl.sh context init` — set or replace context
- `./scripts/sxctl.sh context show` — print saved context summary
- `./scripts/sxctl.sh context clear` — remove saved context
- `./scripts/sxctl.sh diagnostics` — run context, vault, DB, and API checks
- `./scripts/sxctl.sh verify` — run a comprehensive CLI/backend smoke-test matrix

Legacy command families remain:

- `./scripts/sxctl.sh api <serve|serve-bg|stop|server-status|init|import|status|menu>`
- `./scripts/sxctl.sh plugin <update|build|install>`

## Context model

Saved file: `./.sxctl/context.env`

Fields include:

- `SXCTL_PROFILE_INDEX`
- `SXCTL_SOURCE_ID`
- `SXCTL_SOURCE_PATH`
- `SXCTL_DB_BACKEND=postgres_primary|postgres|sqlite` (defaults to `postgres_primary`)
- `SXCTL_DB_PATH` (sqlite)
- `SXCTL_PIPELINE_DB_PROFILE` (postgres)
- `SXCTL_PIPELINE_DB_URL` (postgres)
- `SXCTL_PIPELINE_DB_MODE`
- `SXCTL_VAULT_ROOT`

All actions load this file first.

Context display in the menu is intentionally concise and focused on source + backend essentials.
`Vault Root` is tracked in saved context but omitted from the default summary view.

## UI behavior

- Menus use a keyboard navigation picker (`↑/↓` + `Enter`) with a `>>` pointer.
- The main action menu also uses the same picker in interactive mode.
- Source profile rows are intentionally concise:
  - `[N] <label> | source_id=<id> | path=<path>`
- During context setup, vault root defaults to the selected source profile path.
  - You are asked once whether to override it.
  - If you choose override, the picker shows grouped sections:
    - `History: <path>`
    - compact explicit actions (`Browse filesystem`, `Use source profile path`, `Back`)

## Vault validation

Vault root must:

- exist
- be a directory
- contain `.obsidian/`

This avoids confusing profile "target path" with true Obsidian vault root.

Vault history is auto-pruned on each launcher start:

- removes invalid/non-existent paths
- normalizes `.../.obsidian` entries to the vault root
- drops ephemeral temp entries like `/tmp/tmp.*` and `/var/tmp/tmp.*`

## DB backend selection

When creating context:

- **PostgreSQL Primary (recommended)**:
  - Uses one PostgreSQL database with per-source schema isolation.
  - Selects a DB profile alias (for example `SXO_LOCAL_N`, `SXO_SESSION_N`, `SXO_TRANS_N`) to derive DSN.
  - Uses dedicated `sx_obsidian` schemas (`<prefix>_<source_id>`, default prefix `sx`).
  - `Init DB` performs schema bootstrap for the selected source.
- **PostgreSQL Mirror**:
  - Mirrors selected schema data into sqlite-compatible local tables.
- **SQLite Legacy (explicit)**:
  - Uses `data/sx_obsidian_assets_N.db`.
  - Treated as legacy mode in context rendering.

Important: API server selection and DB backend selection are independent.

## Noninteractive mode (for automation/tests)

Use:

- `SXCTL_NONINTERACTIVE=1`
- `SXCTL_PROFILE_INDEX=<N>`
- `SXCTL_VAULT_ROOT=/path/to/vault`
- `SXCTL_DB_BACKEND=postgres_primary|postgres|sqlite`
- `SXCTL_DB_PROFILE=<ALIAS>` (required for postgres when not inferable)

Example:

`SXCTL_NONINTERACTIVE=1 SXCTL_PROFILE_INDEX=2 SXCTL_VAULT_ROOT=/path/to/vault SXCTL_DB_BACKEND=postgres_primary SXCTL_DB_PROFILE=SXO_LOCAL_2 ./scripts/sxctl.sh context init`

## Troubleshooting

### Invalid vault root

Error examples:

- `path does not exist`
- `path is not a directory`
- `missing .obsidian directory`

Fix: point to your real Obsidian vault root.

### PostgreSQL alias has no URL

If context init fails with missing URL for an alias, check SchedulerX env profile mappings and required `*_DB_*` keys.

### API status confusion

`Start API server` controls FastAPI process only.

DB backend is selected in context and applied separately.

### CSV import uses wrong profile files

`Import CSV` resolves files by selected profile index in this order:

1. Explicit env vars: `CSV_consolidated_N`, `CSV_authors_N`, `CSV_bookmarks_N`
2. Fallback: `../SchedulerX/assets_N/xlsx_files/{consolidated,authors,bookmarks}.csv`

This prevents profile/source mismatch during import.
