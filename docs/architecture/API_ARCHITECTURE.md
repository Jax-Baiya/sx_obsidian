# API Architecture: Plugin ↔ Database Interaction

This document explains how the **Obsidian plugin** communicates with the data backend through the **FastAPI server**.

Runtime backends:

- `SQLITE` (legacy/default)
- `POSTGRES_MIRROR` (transitional compatibility, deprecated)
- `POSTGRES_PRIMARY` (target architecture: one schema per source profile)

---

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     OBSIDIAN PLUGIN                             │
│                  (obsidian-plugin/src/main.ts)                  │
├─────────────────────────────────────────────────────────────────┤
│  1. User opens search modal (Command: "SX: Search library")     │
│     - debounced GET /search?q=...                               │
│     - click result → GET /items/{id}/note (pin a note)          │
│                                                                 │
│  2. User opens library table (Command: "SX: Open library table")│
│     - paged GET /items?q=...&limit=...&offset=...               │
│     - inline edits → PUT /items/{id}/meta                       │
│     - thumbnails → GET /media/cover/{id}                        │
│     - video preview → GET /media/video/{id}                     │
└──────────────────────┬──────────────────────────────────────────┘
                       │ HTTP requests to localhost
                       │ (default: http://127.0.0.1:8123)
┌──────────────────────▼──────────────────────────────────────────┐
│                     FASTAPI SERVER                              │
│                      (sx_db/api.py)                             │
├─────────────────────────────────────────────────────────────────┤
│  Endpoints:                                                     │
│  • GET /           → API info + endpoint list                   │
│  • GET /health     → {"ok": true, "source_id": "..."}         │
│  • GET /stats      → item counts, FTS status                    │
│  • GET /sources    → source registry + default source           │
│  • POST /sources   → create/upsert source                       │
│  • PATCH /sources/{id} → update source metadata                 │
│  • POST /sources/{id}/activate → set default source             │
│  • DELETE /sources/{id} → remove empty non-default source       │
│  • GET /search     → FTS5 + LIKE fallback search                │
│  • GET /authors    → author aggregation + filters               │
│  • GET /items       → paged list for table/grid UI              │
│  • GET /items/{id}  → raw item data as JSON                     │
│  • GET /items/{id}/note → rendered markdown note                │
│  • GET/PUT /items/{id}/meta → user-editable columns             │
│  • GET /notes      → paged list of notes (for sync workflows)   │
│  • GET /media/cover/{id} → cover/thumbnail bytes                │
│  • GET /media/video/{id} → video bytes (supports Range)         │
└──────────────────────┬──────────────────────────────────────────┘
                       │ SQLite connection (WAL mode)
┌──────────────────────▼──────────────────────────────────────────┐
│                     SQLITE DATABASE                             │
│                   (data/sx_obsidian.db)                         │
├─────────────────────────────────────────────────────────────────┤
│  Tables:                                                        │
│  • videos        → main data (id, caption, author, paths...)    │
│  • user_meta     → user-owned columns (rating/status/tags/notes)│
│  • videos_fts    → FTS5 full-text search index (contentless)    │
└─────────────────────────────────────────────────────────────────┘
```

---

## Detailed Flow: Search & Pin

### 1. Search Flow

```
PLUGIN                     API                        DATABASE
  │                         │                            │
  │ GET /search?q=nike&limit=50                         │
  │─────────────────────────>                           │
  │                         │ FTS5 MATCH 'nike'         │
  │                         │ ──────────────────────────>│
  │                         │                            │
  │                         │ (if FTS returns empty,     │
  │                         │  fallback to LIKE '%nike%')│
  │                         │                            │
  │                         │ <── results ───────────────│
  │ <─── JSON ──────────────│                            │
  │ {results: [...]}        │                            │
```

All data endpoints are source-scoped.

- Source is resolved from: `X-SX-Source-ID` header → `source_id` query param → backend default source.
- The API echoes active scope via response header: `X-SX-Source-ID`.

**Search Logic** (`sx_db/search.py`):

1. If query is empty → return all items sorted by `bookmarked DESC, updated_at DESC`
2. If FTS table exists → try FTS5 MATCH query with BM25 ranking
3. If FTS returns empty OR query syntax invalid → fallback to LIKE match
4. LIKE searches: `caption`, `author_unique_id`, `author_name`, `id`

### 2. Pin to Vault Flow

```
PLUGIN                     API                        DATABASE
  │                         │                            │
  │ GET /items/123/note     │                            │
  │─────────────────────────>                           │
  │                         │ SELECT * FROM videos       │
  │                         │ WHERE id='123'             │
  │                         │──────────────────────────> │
  │                         │ <── row data ──────────────│
  │                         │                            │
  │                         │ render_note(row)           │
  │                         │ (builds markdown with      │
  │                         │  YAML frontmatter +        │
  │                         │  sxopen:/sxreveal: links)  │
  │                         │                            │
  │ <─── JSON ──────────────│                            │
  │ {markdown: "---\n..."}  │                            │
  │                         │                            │
  │ vault.create(path, md)  │                            │
  │ (writes to _db/media_active/123.md)                 │
```

**Note Generation** (`sx_db/markdown.py`):

- Builds YAML frontmatter with item metadata
- Creates managed block with Quick Actions (Open/Reveal links)
- Uses `PathResolver` to generate platform-specific paths

---

## API Endpoints Reference

| Endpoint                 | Method | Purpose                   | Returns                                |
| ------------------------ | ------ | ------------------------- | -------------------------------------- |
| `/`                      | GET    | API info                  | Endpoint list                          |
| `/health`                | GET    | Health check              | `{"ok": true, "source_id": "..."}`     |
| `/stats`                 | GET    | Database statistics       | Item counts, FTS status                |
| `/sources`               | GET    | List source registry      | `{sources: [...], default_source_id}`  |
| `/sources`               | POST   | Create/upsert source      | `{ok, source_id}`                      |
| `/sources/{id}`          | PATCH  | Update source metadata    | `{ok, source_id}`                      |
| `/sources/{id}/activate` | POST   | Set default source        | `{ok, default_source_id}`              |
| `/sources/{id}`          | DELETE | Delete source (guarded)   | `{ok, deleted}`                        |
| `/search`                | GET    | Search library (modal)    | `{results: [...], limit, offset}`      |
| `/items`                 | GET    | Paged items list (table)  | `{items: [...], limit, offset, total}` |
| `/items/{id}`            | GET    | Get item details          | `{item: {...}}`                        |
| `/items/{id}/note`       | GET    | Get markdown note         | `{id, markdown}`                       |
| `/items/{id}/meta`       | GET    | Get user meta             | `{meta: {...}}`                        |
| `/items/{id}/meta`       | PUT    | Upsert user meta          | `{meta: {...}}`                        |
| `/media/cover/{id}`      | GET    | Thumbnail/cover bytes     | Image bytes                            |
| `/media/video/{id}`      | GET    | Video bytes (Range-ready) | Video bytes                            |

### Query Parameters

**`/search`:**

- `q` (string): Search query
- `limit` (int, default 50): Max results
- `offset` (int, default 0): Pagination offset
- `source_id` (string, optional): Source scope override

**`/items`:**

- `q` (string): Substring filter (LIKE)
- `caption_q` (string): Caption-only filter (supports simple advanced syntax)
- `limit` (int, default 50, max 2000): Page size
- `offset` (int, default 0): Page offset
- `bookmarked_only` (bool, default false): Filter to bookmarked rows
- `bookmark_from` / `bookmark_to` (YYYY-MM-DD): Bookmark timestamp window
- `author_unique_id` (csv list): Filter by author unique id
- `author_id` (csv list): Filter by raw author id
- `status` (csv list): Filter by user-owned status (supports blank for unassigned)
- `rating_min` / `rating_max` (0..5): Filter by rating
- `tag` (csv list): Filter by tags (comma-separated tags stored in user meta)
- `has_notes` (bool): Filter by whether user notes exist
- `order` (`recent|bookmarked|author|status|rating`): Sort order
- `source_id` (string, optional): Source scope override

### `caption_q` advanced syntax

The caption-only filter accepts a simple “power user” syntax:

- Quoted phrases: `"long phrase"`
- Exclusions: `-term` (exclude captions containing `term`)

Examples:

- `"morning routine" -ad`
- `nike -"paid partnership"`

---

## Detailed Flow: Library Table (Thumbnails + Inline Edit)

1. Plugin view requests a page of items:

- `GET /items?q=...&limit=...&offset=...&bookmarked_only=...`

For caption-only searching (without affecting author/id):

- `GET /items?caption_q=...&limit=...&offset=...`

2. For each row, the plugin may:

- render a thumbnail via `GET /media/cover/{id}` (only when `cover_path` exists)
- open a video preview via `GET /media/video/{id}` (only when `video_path` exists)

3. Inline edits (Status/Rating/Tags/Notes) are persisted with:

- `PUT /items/{id}/meta` → stored in `user_meta` (never overwritten by CSV imports)

### Media note

Thumbnails/preview require `videos.cover_path` / `videos.video_path` to be populated and readable by the API process.

- Configure the filesystem root via `SX_MEDIA_VAULT` (or `VAULT_default` if you reuse your vault root)
- Configure the media subfolder via `SX_MEDIA_DATA_DIR`
- Use `SX_MEDIA_STYLE=linux` when the API runs on Linux/WSL paths (e.g., `/mnt/c/...`)

If your CSVs don't include media paths, you can populate them by scanning a folder of downloaded files:

- `python -m sx_db media-index --root /path/to/vault --data-dir data` (dry run)
- `python -m sx_db media-index --root /path/to/vault --data-dir data --apply` (write to DB)

---

## Plugin Settings

The Obsidian plugin is configured via Settings > Community plugins > SX Obsidian DB:

| Setting          | Default                 | Description                        |
| ---------------- | ----------------------- | ---------------------------------- |
| API Base URL     | `http://127.0.0.1:8123` | Where the API server is running    |
| Active Notes Dir | `_db/media_active`      | Where pinned notes are created     |
| Search Limit     | 50                      | Max results to fetch               |
| Debounce (ms)    | 250                     | Delay before search query is sent  |
| Bookmarked Only  | false                   | Filter results to bookmarked items |
| Open After Pin   | true                    | Open note after pinning            |

---

## Data Flow Summary

1. **CSV Import** → `sx_db import` → SQLite database
2. **API Server** → `sx_db run` → FastAPI on localhost:8123
3. **Plugin Search** → HTTP GET → API → SQLite FTS5 query → JSON results
4. **Plugin Pin** → HTTP GET → API → markdown generation → vault file write

---

## Key Files

| File                                 | Purpose                          |
| ------------------------------------ | -------------------------------- |
| `sx_db/api.py`                       | FastAPI endpoint definitions     |
| `sx_db/search.py`                    | FTS5 + LIKE search logic         |
| `sx_db/markdown.py`                  | Note rendering with frontmatter  |
| `sx_db/db.py`                        | SQLite schema + connection       |
| `obsidian-plugin/src/main.ts`        | Plugin: search modal + pin logic |
| `obsidian-plugin/src/libraryView.ts` | Plugin: table/grid UI + edits    |
| `obsidian-plugin/src/settings.ts`    | Plugin settings UI               |
