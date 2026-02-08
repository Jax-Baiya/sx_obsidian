# SX Obsidian DB

> **Repo description (suggested for GitHub):**
> Local-first SQLite + FastAPI backend + Obsidian plugin for browsing a large SX media library and pinning an active working set into your vault.

[![CI](https://github.com/Jax-Baiya/sx_obsidian/actions/workflows/ci.yml/badge.svg)](https://github.com/Jax-Baiya/sx_obsidian/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.10-blue)
![Node](https://img.shields.io/badge/node-%3E%3D18-brightgreen)
![Obsidian](https://img.shields.io/badge/Obsidian-Desktop-purple)

**A local-first SX library system for Obsidian**: SQLite + FastAPI API + an Obsidian plugin, with an optional CSV→Markdown generator.

If you’ve ever tried to shove 10k–50k generated notes into an Obsidian vault, you already know the pain: startup indexing storms, timeouts, and a vault that feels like it’s wading through syrup.

This project’s main goal is simple:

> Keep Obsidian fast while still giving you a powerful “library browser” + a lightweight set of pinned, editable notes.

## Short introduction

This project lets you **search and curate a very large library** from inside Obsidian *without* generating tens of thousands of Markdown notes.

It does that by:

1. importing your CSV exports into **SQLite**,
2. serving a local **FastAPI** backend on `localhost`,
3. giving you an **Obsidian plugin UI** for search + a library table,
4. letting you “pin” only a small active working set (e.g. `_db/media_active/`) into the vault.

## Technologies used

Backend:

- Python 3.10
- FastAPI + Uvicorn
- SQLite

Plugin:

- TypeScript
- Obsidian Plugin API
- esbuild (bundling)

Tooling:

- pytest (tests)
- GitHub Actions CI (`.github/workflows/ci.yml`)

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

## Features

- **Fast local search** (search modal) and a **paged library table** (table view)
- **Pin items into the vault** as Markdown notes (active working set)
- **User-owned metadata** persisted in SQLite (rating/status/tags/notes, etc.)
- **Sync workflows**:
    - DB → vault (fetch/pin notes)
    - vault → DB (push edits back)
- **Vault safety** defaults:
    - generator logs default outside the vault to avoid indexing storms
    - “active set” pattern to keep Obsidian responsive

## What users can do

- Browse and filter the library from inside Obsidian
- Pin items into a dedicated notes folder
- Edit metadata fields and keep those edits stable across CSV re-imports
- Preview media (cover/video) when paths exist and API can access them
- Keep their vault fast by storing the full dataset in SQLite rather than files

## Commands / keyboard shortcuts

The plugin exposes Obsidian commands (Command Palette). You can bind hotkeys in:
**Settings → Hotkeys**.

Available commands (from `obsidian-plugin/src/main.ts`):

- `SX: Search library`
- `SX: Pin item by ID…`
- `SX: Open library table`
- `SX: Refresh library table`
- `SX: Sync current library selection → vault`
- `SX: Fetch notes (DB → vault) using Fetch settings`
- `SX: Push notes (vault → DB) from _db folders`
- `SX: Test API connection`
- `SX: Open API docs`
- `SX: Preview video for current note`
- `SX: Open plugin settings`
- Settings deep-links:
    - `SX: Open settings → Connection tab`
    - `SX: Open settings → Sync tab`
    - `SX: Open settings → Fetch tab`
    - `SX: Open settings → Backend tab`
    - `SX: Open settings → Views tab`
    - `SX: Open settings → Advanced tab`
- Convenience:
    - `SX: Copy backend command (sxctl api serve)`
    - `SX: Copy backend command (python -m sx_db serve)`

## Build process (how I built it)

This repo is intentionally split into two layers:

1) **Data layer** (SQLite + API)

- CSV exports are imported into SQLite (`python -m sx_db import-csv`).
- A FastAPI app (`sx_db/api.py`) exposes endpoints for:
    - search (`/search`)
    - paging/filtering (`/items`)
    - rendering Markdown notes (`/items/{id}/note`)
    - user meta persistence (`/items/{id}/meta`)
    - media streaming (`/media/...`)

2) **UX layer** (Obsidian plugin)

- TypeScript sources live in `obsidian-plugin/src/`.
- The build uses **esbuild** (`obsidian-plugin/esbuild.config.mjs`) to bundle into `obsidian-plugin/main.js`.
- Installing the plugin is automated by `scripts/install_plugin.sh` (copies `manifest.json`, `main.js`, `styles.css` into your vault’s `.obsidian/plugins/` directory).

## What I learned

- How to design for **performance constraints** in Obsidian (file count is a real scaling limit).
- How to separate **source-of-truth imports** (CSV) from **user-owned edits** (SQLite `user_meta`).
- How to build a local-first developer experience with:
    - one-command bootstrap (`make bootstrap`)
    - CI that runs tests on every push/PR
- How to ship a plugin UX that still outputs **plain Markdown** for compatibility.

## How it could be improved

- Add an API client layer in the plugin (typed SDK + shared models) to reduce duplicated URL building.
- Add more integration tests for:
    - plugin → API flows
    - edge cases around media paths and Range requests
- Improve search ranking and filtering UX (saved views, presets, better relevance).
- Add a release pipeline (tagged builds + plugin distribution artifacts).
- Add optional containerization for the API (Docker) for easier onboarding.

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

## Media

Add screenshots/GIFs to `docs/assets/` and link them here.

Suggested media to include:

1. Search modal → pin action
2. Library table with filters
3. Example pinned note (frontmatter + managed region)

Placeholders:

- `docs/assets/search-modal.png`
- `docs/assets/library-table.png`
- `docs/assets/pinned-note.png`



