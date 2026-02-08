# SX Obsidian DB

**A local-first SX library system for Obsidian**: SQLite + FastAPI API + an Obsidian plugin, with an optional CSV→Markdown generator.

If you’ve ever tried to shove 10k–50k generated notes into an Obsidian vault, you already know the pain: startup indexing storms, timeouts, and a vault that feels like it’s wading through syrup.

This project’s main goal is simple:

> Keep Obsidian fast while still giving you a powerful “library browser” + a lightweight set of pinned, editable notes.

## What’s in the box

- **`sx_db/`** — SQLite + FastAPI service
    - Imports CSV exports into a local DB
    - Serves search, paging, media, and note-rendering endpoints
- **`obsidian-plugin/`** — Obsidian community plugin
    - Search modal + SX Library table view
    - Pin notes into an “active” folder (e.g. `_db/media_active`)
    - Edit user-owned metadata without touching source CSVs
- **`sx/`** — generator workflow (CSV → Markdown)
    - Idempotent sync into your vault
    - Managed regions to protect manual edits

## Why this is portfolio-worthy

This isn’t a “toy script.” It’s an end-to-end, real workflow system:

- **Performance-aware UX**: designed specifically to avoid vault meltdown at scale.
- **Clear data ownership**: source data (CSV) vs user edits (SQLite `user_meta`) vs pinned notes (vault).
- **Local-first**: everything runs on `localhost` by default.
- **Operational ergonomics**: one-command bootstrap, tests, and helper launchers.

If you want the engineering story: see **[`docs/PORTFOLIO.md`](docs/PORTFOLIO.md)**.

## Quickstart (recommended): SQLite + API + Obsidian plugin ⭐

### 1) Bootstrap

```bash
make bootstrap
```

This creates `.venv/`, installs Python deps, and runs `npm install` for the plugin.

### 2) Configure

```bash
cp .env.example .env
```

Edit `.env` to point at your vault and CSV exports.

### 3) Import database

```bash
make api-init
make api-import
```

### 4) Run the API

```bash
make api-serve
```

Default URL: `http://127.0.0.1:8123`

### 5) Build + install the plugin into your vault

```bash
export OBSIDIAN_VAULT_PATH=/path/to/your/vault
make plugin-build
make plugin-install
```

Or use the convenience launcher:

```bash
./sxctl.sh plugin update
```

Then enable **“SX Obsidian DB”** in Obsidian → Community plugins.

## Quickstart (optional): CSV → Markdown generator

If you want files generated directly into your vault:

```bash
./deploy.sh
cp .env.example .env
./run.sh --mode sync
```

## Documentation

Start here: **[`docs/README.md`](docs/README.md)**

Most-used:

- [Usage Guide](docs/USAGE.md)
- [SQLite + Plugin workflow](docs/PLUGIN_DB.md)
- [API architecture](docs/API_ARCHITECTURE.md)
- [Performance & large vault safety](docs/PERFORMANCE.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)

## Architecture (high level)

```mermaid
flowchart LR
    subgraph Obsidian[Obsidian]
        P["SX Obsidian DB\nCommunity Plugin"]
        V[Vault\n(_db/media_active/*.md)]
    end

    subgraph Local[Local machine]
        API[FastAPI\n(sx_db/api.py)]
        DB[(SQLite\n(data/sx_obsidian.db))]
        CSV[(CSV exports)]
    end

    CSV -->|import-csv| DB
    P <-->|HTTP localhost| API
    API <--> DB
    P -->|pin notes| V
```

## Development

- Run tests: `make test`
- Python entrypoints:
    - generator: `./run.sh ...` (wraps `python -m sx`)
    - API/DB: `./.venv/bin/python -m sx_db ...`
- Pre-commit (optional): `./.venv/bin/pre-commit run --all-files`

## Security notes

This system is designed to be **local-only**.

- Keep the API bound to `127.0.0.1` unless you *really* mean to expose it.
- Do not put secrets in `.env` that you wouldn’t want on your machine.



