# SX Library Features (Current)

This is a practical, user-oriented feature index for the SX Obsidian plugin's **SX Library** view.

## Open the SX Library

- In Obsidian, open the **SX Library (DB)** view from the plugin command/menu.
- The view loads from the configured API base URL and shows paginated items.

---

## Core table controls

### Global search

- **What it does:** Filters rows quickly by free-text query.
- **How to use:** Type in the `Search…` input.
- **Behavior:** Debounced refresh to reduce request spam.

### Bookmark-only filter

- **What it does:** Shows only bookmarked records.
- **How to use:** Toggle **Bookmarked only**.

### Status filter chips

- **What it does:** Multi-select workflow statuses (`raw`, `reviewing`, `reviewed`, `scheduling`, `scheduled`, `published`, `archived`).
- **How to use:** Check one or more statuses; click **Any** to clear.

### Pagination

- **What it does:** Navigates current result set.
- **How to use:** **Prev** / **Next** buttons.

---

## Menubar actions

### Refresh

- **What it does:** Re-fetches current page with current filters.

### Sync

- **What it does:** Materializes current filtered selection into vault markdown notes.
- **How to use:** Click **Sync**.
- **Notes:** Respects configured write strategy and sync limits.

### Clear

- **What it does:** Resets all active filters/sorts and reloads table.

### Data panel

- **What it does:** Shows active pin folder path and copy action.

### Filters panel

- **What it does:** Advanced filters and sort controls.
- **Includes:**
  - Sort mode
  - Tag filter
  - Caption filter
  - Rating min/max
  - Has notes only
  - Author search + author select

### Columns panel

- **What it does:** Full column layout management.
- **Includes:**
  - Show/hide columns
  - Drag to reorder
  - Per-column width (px)
  - Auto-fit, Show all, Reset columns, Reset layout

### View panel

- **What it does:** View behavior controls.
- **Includes:**
  - Cell wrapping mode (`ellipsis`, `clip`, `wrap`) for entire table
  - Freeze panes (none / ID / Thumb+ID)
  - Freeze first data row

---

## Table interaction features

### Index column (`#`)

- **What it does:** Displays row index using current pagination offset.
- **How to use:** Left-most column before thumbnail.

### Row resize handle

- **What it does:** Lets you increase/decrease row height.
- **How to use:** Drag the bottom edge handle in the index cell.

### Selection model (single-mode)

- **What it does:** Prevents lag/confusion by allowing only one active selection mode at a time.
- **Modes:**
  - Whole table
  - One column
  - One row
  - One cell
- **How to use:**
  - Click index header `#` → select whole table (toggle off by clicking again)
  - Click a non-index header → select that column (single)
  - Click index cell in a row → select that row (single)
  - Click any normal cell background → select that cell (single)

### In-cell editing

- **What it does:** Edit metadata fields inline and save automatically on change.
- **Editable columns include:** status, rating, tags, notes, links, platform targets, post URL, published time, workflow log.

---

## Link chips / smart links

### Smart chip rendering

- **What it does:** Converts URL fields to concise chips with readable labels (host/path).
- **Fields:** Product link, Author links, Post URL.

### Chipify action button

- **What it does:** Normalizes input into deduplicated URL list and updates chip row.
- **How to use:** Click per-field chip action button (label is configurable).

### Chipify button visibility toggle

- **What it does:** Lets you hide/show the smart-link action button for cleaner table UI.
- **How to use:** Settings → **Views** → **Show smart-link action button**.
- **Note:** Even when hidden, keyboard chipify (Tab/Enter per setting) still works.

### Key-trigger chipify

- **What it does:** Chipifies on keyboard trigger.
- **Config options:** Tab / Enter / Both (settings).

### Link click behavior

- **What it does:** Opens protocol links/URLs; supports modifier-based copy behavior.

---

## Validation rules

### Rating validation

- Must be an integer in range `0..5`.

### URL validation

- Link fields must contain valid `http://` or `https://` URLs.

### Invalid field UX

- Invalid fields are highlighted.
- Save is blocked until invalid values are corrected.

---

## Preview and note operations

### Thumbnail hover video preview

- **What it does:** Shows floating video preview above table layers.
- **Performance design:** Uses a single shared player to reduce DOM overhead.
- **Size modes (Settings → Views):**
  - **Scale from TikTok default ratio:** scales portrait baseline (`240 x 426`) up/down by percentage while preserving ratio.
  - **Free width/height:** explicit pixel dimensions for custom sizing.

### ID actions

- **Open:** Click ID to open local note if present.
- **Copy:** Copy item ID.
- **Peek:** Open note peek (if enabled).
- **Shift+Click ID:** Fast open note peek.
- **Ctrl/Cmd hover on ID:** Triggers markdown hover preview engine (config-dependent).

### Action buttons

- **Preview:** Open backend media URL.
- **Open / Reveal:** Use generated links or note frontmatter fallback.
- **Pin / Unpin:** Materialize/remove active note.

---

## Commands and quick usage notes

The view uses UI actions primarily. Depending on your command palette setup, these common operations are available via plugin commands/hooks:

- Refresh current SX Library selection.
- Sync current SX Library selection to vault notes.

If command names differ in your environment, check Obsidian **Command Palette** and search for `SX` or plugin name.

---

## Performance tips

- Keep page limit moderate (very high limits increase DOM and event cost).
- Use Filters panel instead of loading overly broad datasets.
- Keep only needed columns visible for smoother scrolling/interactions.
- Prefer floating hover preview (enabled) over opening many preview panes.

---

## Troubleshooting: plugin install path error

If `./sxctl.sh` fails with:

- `mkdir: cannot create directory ... No such device`

it usually means `OBSIDIAN_VAULT_PATH` points to a mount/path not available in your current shell environment.

Quick fix:

1. Use the real vault path for your current OS/shell (Linux/WSL path).
2. Re-run `./sxctl.sh` and provide that path when prompted.
3. Or set it explicitly before install:

- `export OBSIDIAN_VAULT_PATH="/your/real/vault/path"`

The launcher now validates the path before running plugin install and will re-prompt on invalid paths.
