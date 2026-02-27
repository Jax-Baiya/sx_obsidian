# Usage Guide

If you’re new here, start with the project overview in `../README.md`, then come back for the hands-on steps below.

This project supports **two ways** to work with your SchedulerX exports:

1. **Generator (file sync)** — creates/updates Markdown notes in your vault from CSVs.
2. **SQLite + API + Obsidian plugin (recommended for huge libraries)** — keeps the _full_ library in SQLite and only “pins” a small active set (~1k) into the vault.

If your vault struggles to load with `_db/media` at 14k+ notes, use the **SQLite + plugin** workflow and keep only an active subset in Obsidian.

## Quickstart (generator)

1. Deploy:

```bash
./scripts/deploy.sh
```

2. Configure:

```bash
cp .env.example .env
```

Update `.env` values (examples):

```env
SX_PROFILE=default
VAULT_default=/mnt/t/AlexNova
VAULT_WINDOWS_default=T:\\AlexNova
PATH_STYLE=windows

CSV_consolidated_1=/path/to/consolidated.csv
CSV_authors_1=/path/to/authors.csv
CSV_bookmarks_1=/path/to/bookmarks.csv

# Where generated notes go (inside vault)
DB_DIR=_db/media_active

# Logs default outside vault to avoid Obsidian timeouts
LOG_IN_VAULT=0
LOG_DIR=_logs
```

3. Dry-run a small sample:

```bash
./scripts/run.sh --mode sync --limit 25 --dry-run
```

4. Full sync:

```bash
./scripts/run.sh --mode sync
```

## Quickstart (SQLite + API + Obsidian plugin) ⭐

This path is designed to keep Obsidian fast:

- SQLite stores the full library.
- You search from inside Obsidian (plugin → local API).
- You pin only the items you actually need as Markdown notes.

1. Deploy with dev tooling (installs API/CLI deps too):

```bash
./scripts/deploy.sh --dev
```

2. Initialize + import database (reads the same `.env` CSV paths):

```bash
./.venv/bin/python -m sx_db init
./.venv/bin/python -m sx_db import-csv
```

Source-aware import example:

```bash
./.venv/bin/python -m sx_db import --source default
```

3. Run the API:

```bash
./.venv/bin/python -m sx_db serve
```

### Convenience launcher (recommended)

From the `sx_obsidian` repo root you can use:

```bash
./scripts/sxctl.sh api serve
```

And for plugin updates:

```bash
export OBSIDIAN_VAULT_PATH=/mnt/t/AlexNova
./scripts/sxctl.sh plugin update
```

Interactive target selection is available in `./scripts/sxctl.sh` menu mode.
You can choose:

- profile index from detected `SRC_PATH_N` / `SRC_PROFILE_N`
- custom source label/path/id overrides
- vault override
- pipeline DB mode (`LOCAL|SESSION|TRANSACTION`) or explicit DB alias

Tip: `scripts/Makefile` wraps the same flow (`make -f scripts/Makefile api-init`, `make -f scripts/Makefile api-import`, `make -f scripts/Makefile api-serve`, `make -f scripts/Makefile plugin-build`, `make -f scripts/Makefile plugin-install`).

The plugin does **not** need to be “launched” each time.

- You only need to **build + install** when the plugin code changes.
- In Obsidian, keep it enabled; it loads automatically.

4. Build + install the Obsidian plugin:

```bash
cd obsidian-plugin
npm install
npm run build
cd ..

# Install into a vault (set OBSIDIAN_VAULT_PATH to your vault root)
export OBSIDIAN_VAULT_PATH=/mnt/t/AlexNova
./scripts/install_plugin.sh
```

5. In Obsidian:

- Settings → Community plugins → enable **SX Obsidian DB**
- Settings → SX Obsidian DB → Connection → set/select **Active source ID**
- Command palette → **SX: Search library**
- Click a result → it gets pinned to your active notes folder (default `_db/media_active/<id>.md`)

To pull Markdown notes from SQLite into your vault (DB → vault):

- Settings → Community plugins → **SX Obsidian DB** → **Fetch** tab → configure filters → run **Fetch notes (DB → vault)**
- Or: Command palette → **SX: Open library table** → apply filters → **Sync selection → vault**

See also: [SQLite DB + Plugin](PLUGIN_DB.md)

## Generator CLI options (python -m sx)

These are the options supported by `./scripts/run.sh` (which runs `python -m sx`).

| Option             | Description                                                                   |
| ------------------ | ----------------------------------------------------------------------------- | ------------------------------------------------------------------- | -------------------------------------------- |
| `--profile NAME`   | Active profile name (from `.env` like `VAULT_<NAME>` / `CSV_consolidated_*`). |
| `--vault PATH`     | Vault root override. Required unless provided by your `.env` profile.         |
| `--csv PATH`       | Consolidated CSV override. May be repeated (`--csv A --csv B`).               |
| `--add-csv PATH`   | Add extra CSV sources (in addition to profile/config).                        |
| `--authors PATH`   | Optional authors.csv override (author detail joins).                          |
| `--bookmarks PATH` | Optional bookmarks.csv override (bookmark/favorites flag).                    |
| `--set KEY=VALUE`  | Override a config value (repeatable).                                         |
| `--data-dir NAME`  | Data directory name under vault (defaults via `DATA_DIR`).                    |
| `--db-dir NAME`    | Notes directory under vault (defaults via `DB_DIR`).                          |
| `--log-dir NAME`   | Log directory (defaults via `LOG_DIR`).                                       |
| `--schema PATH`    | Path to `schema.yaml` file.                                                   |
| `--mode create     | update                                                                        | sync`                                                               | Run the sync pipeline (recommended: `sync`). |
| `--limit N`        | Process only the first N rows (testing).                                      |
| `--dry-run`        | Don’t write files; show what would change.                                    |
| `--validate`       | Run validation checks during the run.                                         |
| `--cleanup soft    | hard`                                                                         | Reset generated output. `hard` may remove more; requires `--force`. |
| `--force`          | Required for dangerous cleanup/archive operations.                            |
| `--interactive`    | Launch an interactive menu.                                                   |
| `--add-profile`    | Prompts to add a new profile into `.env`.                                     |

### Scalability / vault safety flags

| Option                 | Description                                                                                      |
| ---------------------- | ------------------------------------------------------------------------------------------------ |
| `--only-bookmarked`    | Only sync items that appear in bookmarks CSV (shrinks note count).                               |
| `--only-ids-file PATH` | Only sync IDs listed in a text file (one id per line).                                           |
| `--archive-stale`      | Move notes _not_ in the current selection to `ARCHIVE_DIR` (skips dirty notes unless `--force`). |
| `--archive-dir PATH`   | Override archive directory (otherwise `ARCHIVE_DIR` env or `_archive/sx_obsidian_db`).           |

## sx_db CLI options (python -m sx_db)

The SQLite subsystem has its own CLI:

- `python -m sx_db init`
- `python -m sx_db import-csv` (reads `CSV_consolidated_1`, `CSV_authors_1`, `CSV_bookmarks_1` from `.env` unless overridden)
- `python -m sx_db search "query"`
- `python -m sx_db serve` (starts FastAPI)

Source registry commands:

- `python -m sx_db sources list`
- `python -m sx_db sources add <id> --label "My Source"`
- `python -m sx_db sources set-default <id>`
- `python -m sx_db sources remove <id>`

Source-scoped command options:

- `python -m sx_db status --source <id>`
- `python -m sx_db find "query" --source <id>`
- `python -m sx_db import --source <id>`
- `python -m sx_db export-userdata --source <id>`
- `python -m sx_db import-userdata --source <id>`

If you prefer a guided interface:

- `python -m sx_db --menu`

## PostgreSQL profile integration (SchedulerX pipeline)

`sx_obsidian` API remains SQLite-based for library serving and plugin features.

However, launch/config now integrates SchedulerX pipeline DB profiles for targeting awareness:

- resolves `SRC_PATH_N_DB_LOCAL|SESSION|TRANSACTION`
- resolves optional `SQL_DB_PATH_N` (SQL mode)
- resolves DB aliases like `LOCAL_1`, `SUPABASE_SESSION_1`
- surfaces redacted PostgreSQL URLs in launcher context and plugin Config tab

### PostgreSQL backend mode (safe workaround)

To avoid breaking plugin contracts, PostgreSQL runtime mode is implemented as a **mirror**:

- set `SX_DB_BACKEND_MODE=POSTGRES_MIRROR`
- set `SX_PIPELINE_DB_MODE=LOCAL|SESSION|TRANSACTION`
- API mirrors SchedulerX PostgreSQL rows (`consolidated/authors/bookmarks/media`) into sqlite `videos` for the active source
- plugin/API endpoints continue using the same sqlite schema and behavior

If you want pure sqlite path selection instead, set:

- `SX_PIPELINE_DB_MODE=SQL`
- optional `SQL_DB_PATH_N=...` for explicit indexed sqlite DB paths

This gives users one `_N` indexed targeting model across source paths, sqlite DB naming, and pipeline DB profile awareness.

## Profile management

Store multi-vault paths in `.env`:

```env
VAULT_work=/mnt/f/WorkVault
VAULT_personal=/mnt/f/PersonalVault
```

Run with:

```bash
./scripts/run.sh --profile work --mode sync
```

## Where outputs go (and why it matters)

- Notes are generated into your vault under `DB_DIR` (default: `_db/media`).
- Logs default to a project-local `_logs/` folder (outside the vault) to avoid Obsidian indexing storms.
  - Opt-in to in-vault logs with `LOG_IN_VAULT=1`.

If your vault becomes sluggish or won’t open, reduce note count by switching to an “active” folder (example: `DB_DIR=_db/media_active`) and using the filters + archiving.

## Managing manual notes safely

Generated files contain a managed section:

```markdown
<!-- sx-managed:start -->

... generated content ...

<!-- sx-managed:end -->
```

Everything inside the managed block is regenerated on sync.
Write your manual notes **outside** the managed block to keep them across runs.
