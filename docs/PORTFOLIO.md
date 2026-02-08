# SX Obsidian DB — Portfolio case study

## The problem

I wanted to browse and curate a large media library from inside Obsidian.

A naïve approach (generate a Markdown note per item) works at small scale, but breaks down when you reach **10k+ notes**:

- Vault startup becomes slow or unstable due to indexing load.
- “File system operation timed out” errors show up.
- Search and navigation degrade because everything becomes “too many files.”

## The solution (high level)

This project splits the workflow into two layers:

1. **Library layer (SQLite + API)**
   - Store the full dataset in SQLite.
   - Provide a local FastAPI service to power search and paging.
2. **Working set layer (Obsidian vault)**
   - Keep only a small “active set” of pinned notes inside the vault.
   - Notes remain plain Markdown so they play nicely with the Obsidian ecosystem.

This keeps Obsidian fast while still giving a rich library browsing experience.

## Architecture highlights

- **Local-first**: the API binds to `127.0.0.1` by default.
- **Clear data ownership**:
  - *Source-of-truth imports*: CSV → SQLite
  - *User-owned edits*: persisted in a dedicated `user_meta` table (never overwritten by imports)
  - *Vault notes*: generated/pinned Markdown that can be edited safely

A deeper dive is in [`API_ARCHITECTURE.md`](API_ARCHITECTURE.md).

## UX / product features

### Obsidian plugin

- **Search modal** for fast “type → click → pin”
- **Library table** for paging, filters, and bulk workflows
- **Pinning** writes a Markdown note to an active folder (default `_db/media_active/`)
- **Metadata editing** updates SQLite user metadata via API (no CSV mutation)

### Vault safety

- **Managed regions** inside generated Markdown protect manual notes.
- **Logs outside the vault** by default to prevent indexing storms.

See [`PERFORMANCE.md`](PERFORMANCE.md) for the “vault won’t open” recovery playbook.

## Engineering choices & tradeoffs

- **SQLite**: fast enough locally, simple deployment, great for a single-user workflow.
- **FastAPI**: clean API surface, easy local dev, typed request validation.
- **Obsidian plugin**: keeps the experience native; still outputs plain Markdown.

Tradeoff: running a local service is an extra moving part, but it pays for itself by keeping the vault stable at scale.

## How to try it

- Follow [`USAGE.md`](USAGE.md).
- Use `make bootstrap` + `make api-init` + `make api-import` + `make api-serve`.
- Install the plugin and point it at the local API.

## Screenshots / demo

Add screenshots/GIFs to `docs/assets/` and link them here. Suggested shots:

1. Search modal results + pin action
2. SX Library table view with filters
3. Pinned note Markdown (frontmatter + managed section)
4. Performance note: active set folder size vs full dataset size
