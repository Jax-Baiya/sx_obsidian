# SX Obsidian DB (SQLite) + Plugin

This integration keeps Obsidian fast by **not** requiring 14k+ generated notes inside the vault.

Instead:
- A local SQLite database stores the full library.
- The Obsidian plugin searches the library via a local API.
- You “pin” only ~1k active items into the vault as Markdown notes.

## Quickstart

1) Bootstrap:
- `make bootstrap`

2) Initialize + import the database:
- `make api-init`
- `make api-import`

Optional (multi-source): import into a specific source id:
- `./.venv/bin/python -m sx_db import --source default`

By default, `import-csv` reads these from `.env`:
- `CSV_consolidated_1`
- `CSV_authors_1`
- `CSV_bookmarks_1`

3) Run the API:
- `make api-serve`

4) Build + install the plugin into your vault:
- `make plugin-build`
- `export OBSIDIAN_VAULT_PATH=/mnt/t/AlexNova`
- `make plugin-install`

Or use the helper launcher (wraps the same Make targets):

- `./sxctl.sh plugin update`

Enable the plugin in Obsidian:
- Settings → Community plugins → Enable “SX Obsidian DB”

## Using the plugin

- Command palette: **SX: Search library**
- Click a result to pin it into your active notes folder (default: `_db/media_active`).

### Plugin settings

Settings → Community plugins → SX Obsidian DB:

- API base URL
- Active source ID (or choose from Source registry)
- Active notes folder
- Search limit + debounce
- Bookmarked-only filter
- Open note after pin
- Test connection (calls `/health` + `/stats`)

### Source registry (Connection tab)

You can manage sources directly from plugin settings:

- list/reload backend sources
- add a new source id
- set plugin active source
- set backend default source
- delete empty non-default sources

## Notes

- Keep the database and logs outside the vault.
- If your vault won’t open due to `_db/media`, see `docs/PERFORMANCE.md`.

## Next reading

- [Usage Guide](USAGE.md)
- [API Architecture](API_ARCHITECTURE.md)
- [Portfolio / case study](PORTFOLIO.md)
