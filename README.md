# SX Obsidian DB Layer Generator

Mission: Build a reliable, production-quality script system that syncs SchedulerX pipeline outputs (CSV) with an Obsidian vault's media store.

## Quickstart

1.  **Deploy**: Setup the environment.
    ```bash
    ./deploy.sh
    ```
    To include test tooling (pytest):
    ```bash
    ./deploy.sh --dev
    ```
2.  **Configure**: (Optional but recommended) create a `.env` file based on `.env.example`.
    ```bash
    cp .env.example .env
    # Edit .env with your paths
    ```
3.  **Run**: Execute the sync process.
    ```bash
    ./run.sh --mode sync
    ```

## Recommended entrypoints (compatibility-first)

- Primary (stable): `./run.sh ...` (uses the project venv and runs `python -m sx`)
- Also supported: `python -m sx ...`
- Legacy wrappers (kept to avoid breaking old habits): `generator.py`, `validate.py`

## Key Features
- **Environment Support**: Configuration via `.env` file (like the pipeline system).
- **Idempotent**: Re-running only updates files that have changed.
- **Managed Regions**: Keeps your manual notes safe using special tags.
- **Detailed Logging**: Logs default to a project-local `_logs/` folder **outside the vault** (to avoid Obsidian indexing storms). You can opt-in to in-vault logs via `LOG_IN_VAULT=1`.
- **Schema Resilience**: Field mappings are configurable in `schema.yaml`.

## Documentation
- [Usage Guide](docs/USAGE.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Expected Outcomes](docs/EXPECTED_OUTCOMES.md)
- [Developer Notes](docs/DEV_NOTES.md)
- [Performance & Large Vault Safety](docs/PERFORMANCE.md)
- [SQLite DB + Obsidian Plugin (avoid 14k notes)](docs/PLUGIN_DB.md)

## Project layout (high level)

- `sx/` — Python package (canonical implementation)
- `run.sh` / `deploy.sh` — operational scripts
- `docs/` — documentation
- `tests/` — tests
- `tools/` — protocol tooling, helpers
- `legacy/` — extra wrappers/stubs for older flows

## Tests

- Install dev deps: `./deploy.sh --dev`
- Run tests: `./.venv/bin/python -m pytest -q`

> Note: Python virtual environments are not relocatable. If you move this folder,
> delete `.venv/` and re-run `./deploy.sh` (or `./deploy.sh --dev`).

## Development

- Install pre-commit hooks (after `./deploy.sh --dev`): `./.venv/bin/pre-commit install`
- Run hooks on demand: `./.venv/bin/pre-commit run --all-files`


