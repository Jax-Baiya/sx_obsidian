# Usage Guide

If you’re new here, start with the project overview in `../README.md`, then come back for the hands-on steps below.

This project supports **two ways** to work with your SchedulerX exports:

1. **Generator (file sync)** — creates/updates Markdown notes in your vault from CSVs.
2. **SQLite + API + Obsidian plugin (recommended for huge libraries)** — keeps the _full_ library in SQLite and only “pins” a small active set (~1k) into the vault.

If your vault struggles to load with `_db/media` at 14k+ notes, use the **SQLite + plugin** workflow and keep only an active subset in Obsidian.

## Quickstart (generator)

1. Deploy:

```bash
./deploy.sh
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
./run.sh --mode sync --limit 25 --dry-run
```

4. Full sync:

```bash
./run.sh --mode sync
```

## Quickstart (SQLite + API + Obsidian plugin) ⭐

This path is designed to keep Obsidian fast:

- SQLite stores the full library.
- You search from inside Obsidian (plugin → local API).
- You pin only the items you actually need as Markdown notes.

1. Deploy with dev tooling (installs API/CLI deps too):

```bash
./deploy.sh --dev
```

2. Initialize + import database (reads the same `.env` CSV paths):

```bash
./.venv/bin/python -m sx_db init
./.venv/bin/python -m sx_db import-csv
```

3. Run the API:

```bash
./.venv/bin/python -m sx_db serve
```

### Convenience launcher (recommended)

From the `sx_obsidian` repo root you can use:

```bash
./sxctl.sh api serve
```

And for plugin updates:

```bash
export OBSIDIAN_VAULT_PATH=/mnt/t/AlexNova
./sxctl.sh plugin update
```

Tip: the `Makefile` wraps the same flow (`make api-init`, `make api-import`, `make api-serve`, `make plugin-build`, `make plugin-install`).

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
- Command palette → **SX: Search library**
- Click a result → it gets pinned to your active notes folder (default `_db/media_active/<id>.md`)

To pull Markdown notes from SQLite into your vault (DB → vault):

- Settings → Community plugins → **SX Obsidian DB** → **Fetch** tab → configure filters → run **Fetch notes (DB → vault)**
- Or: Command palette → **SX: Open library table** → apply filters → **Sync selection → vault**

See also: [SQLite DB + Plugin](PLUGIN_DB.md)

## Generator CLI options (python -m sx)

These are the options supported by `./run.sh` (which runs `python -m sx`).

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

If you prefer a guided interface:

- `python -m sx_db --menu`

## Profile management

Store multi-vault paths in `.env`:

```env
VAULT_work=/mnt/f/WorkVault
VAULT_personal=/mnt/f/PersonalVault
```

Run with:

```bash
./run.sh --profile work --mode sync
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
