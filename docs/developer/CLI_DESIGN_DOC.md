# sx_obsidian CLI/TUI — Design Document & Improvement Roadmap

> A comprehensive analysis of the sx_obsidian project's CLI and TUI interfaces, capturing the current architecture, strengths, identified UX pain points, and a concrete improvement plan. Modeled after the DocuMorph CLI Design Doc.

---

## 1. Project Overview & What It Does

**sx_obsidian** is a local-first library system for Obsidian. It stores 10K–50K media records in SQLite (instead of individual Markdown files), serves them via a FastAPI backend, and lets an Obsidian plugin browse/search/pin items into the vault.

### The CLI/TUI's Role

The CLI is the **control plane** for the entire system:

| Function | How Users Access It |
|---|---|
| Initialize database | `python -m sx_db setup` or TUI wizard |
| Import CSV data | `python -m sx_db import` or TUI import wizard |
| Search the library | `python -m sx_db find "query"` or TUI search |
| Start API server | `python -m sx_db run` or TUI API control |
| Manage sources | `python -m sx_db sources add/list/set-default` or TUI sources |
| Export/import user data | `python -m sx_db export-userdata` or TUI userdata |
| Index media paths | `python -m sx_db media-index` |
| Prune missing media | `python -m sx_db prune-missing-media` |
| Full orchestration | `./scripts/sxctl.sh` (context + actions) |

### Three CLI Layers

```
┌──────────────────────────────────────────────────────────┐
│  scripts/sxctl.sh (40KB bash)                            │
│  Context setup + profile management + action menu        │
│  Entry: ./scripts/sxctl.sh or ./scripts/sxctl.sh menu    │
├──────────────────────────────────────────────────────────┤
│  sx_db/cli.py (Typer, 1315 lines)                        │
│  15+ commands: status, import, find, run, setup, db,     │
│  export-userdata, import-userdata, media-index,          │
│  prune-missing-media, sources {list,add,set-default,     │
│  remove}, pg-bootstrap                                   │
│  Entry: python -m sx_db <command>                         │
├──────────────────────────────────────────────────────────┤
│  sx_db/tui/ (questionary + Rich, 8 screens)              │
│  Navigator/Router/UIState/Components architecture        │
│  Entry: python -m sx_db --menu (or no args)               │
└──────────────────────────────────────────────────────────┘
```

---

## 2. Architecture — What's Already Great

### 2.1 Screen-Based Router (TUI)

```
sx_db/tui/
├── __init__.py          # Exports Navigator, Router, UIState
├── navigator.py         # Stack-based navigation + breadcrumbs
├── router.py            # Main loop + @register_screen decorator
├── state.py             # UIState dataclass (session memory)
├── components.py        # Reusable Rich widgets
└── screens/
    ├── main.py           # Main menu
    ├── search.py          # Search with pre-filled queries
    ├── sources.py         # Source CRUD
    ├── import_wizard.py   # Multi-step import flow
    ├── settings.py        # Config display (read-only)
    ├── api_control.py     # API server control panel
    ├── userdata.py        # Export/import user data
    └── help.py            # Shortcuts & workflow guide
```

**Strengths:**

| Pattern | Implementation | Why It Works |
|---|---|---|
| **Decorator registry** | `@register_screen("main_menu")` | Zero wiring — just create a file, add the decorator, done |
| **Stack navigation** | `Navigator.push/pop/home` + breadcrumbs | Natural forward/back/home matches user mental model |
| **Session state** | `UIState.remember(last_source="x")` | Smart defaults for repeated actions |
| **Reusable components** | `render_header`, `render_result_panel`, `render_error`, `confirm_destructive_action` | Consistent look across all screens |
| **Import wizard** | Multi-step: source → CSV → confirm → progress → next-actions | Best screen in the TUI — guided, informative, non-destructive |
| **Graceful interrupts** | `KeyboardInterrupt` → back to menu, never crash | Professional feel |

### 2.2 Typer CLI (Command Layer)

**Strengths:**
- Command aliases (`import` / `import-csv` / `load`, `find` / `search`, `run` / `serve`)
- Subcommand groups (`sources list|add|set-default|remove`)
- Rich output everywhere (panels, tables, progress spinners)
- `--json` flag on search for scripting
- Hidden backwards-compat aliases
- Sensible fallback shims when `typer` or `rich` aren't installed

### 2.3 Configuration (Settings)

- 30+ typed fields via `pydantic-settings`
- Smart defaults, `.env` driven
- Handles SQLite, PostgreSQL mirror, and PostgreSQL primary backends
- Media path resolution for WSL/Linux/Windows

---

## 3. UX Audit — What Needs Improvement

### 3.1 Emoji Overload

**Current main menu:**
```
📊 Status & Stats
📥 Import Data
🔍 Search Library
🚀 API Server
📦 Manage Sources
💾 User Data (Export/Import)
⚙️  Settings
❓ Help & Shortcuts
🚪 Exit
```

**Problem:** Every single item has a decorative emoji. They add visual noise without aiding scannability. The eye has to parse both the emoji and the text, making the menu *harder* to read quickly.

**Fix — Semantic icons only:**
```
   Status & Stats
   Import Data
   Search Library
   API Server
 ─────────────────
   Manage Sources
   User Data
 ─────────────────
   Settings
   Help
 ─────────────────
   Exit
```

Use icons only where they carry meaning (e.g., `✓` for success, `✗` for error, `★` for bookmarked). The help screen already defines this vocabulary — the main menu should follow it.

### 3.2 No Custom questionary Styling

**Current:** Default questionary theme — plain white text, no accent colors.

**Fix:** Apply a custom `questionary.Style` like DocuMorph does:
```python
SX_STYLE = questionary.Style([
    ('qmark', 'fg:#00b4d8 bold'),      # Cyan accent
    ('question', 'bold'),
    ('answer', 'fg:#90e0ef bold'),      # Light cyan for selections
    ('highlighted', 'fg:#00b4d8 bold'), # Highlighted item
    ('pointer', 'fg:#00b4d8 bold'),     # Arrow pointer
])
```

Apply this to every `questionary.select` and `questionary.text` call.

### 3.3 Settings Is Read-Only

**Current:** The settings screen displays config values and tells users to "edit your .env file."

**Problem:** Users must find the `.env` file, figure out the variable names, edit them by hand, and restart. This is the opposite of user-friendly.

**Proposed improvements:**
1. **Quick-edit** for the most common settings (API host/port, default source, CSV paths)
2. **Live-edit** using `questionary.text` with current value as default
3. **Save → .env** with dotenv writer
4. **Settings validation** before saving (check paths exist, ports are valid)

### 3.4 No Path History / Browser

**Current:** When importing user data or selecting CSV files, users type paths manually.

**Problem:** Long paths (`/mnt/c/Users/.../SchedulerX/assets_1/xlsx_files/consolidated.csv`) are typed every time.

**Fix (DocuMorph pattern):**
- Add a `PathManager` service (same as DocuMorph's) for MRU path history
- Add the interactive directory browser for CSV selection
- Pre-fill with history on import wizard's Step 2

### 3.5 Import Wizard CSV Lock-in

**Current:** The import wizard reads CSV paths exclusively from `.env` vars (`CSV_consolidated_1`, `CSV_authors_1`, `CSV_bookmarks_1`). If they're not set, it shows an error and returns.

**Problem:** Users can't interactively pick CSV files. They're locked into whatever's in `.env`.

**Fix:**
- If `.env` has paths → show them as defaults, allow override
- If `.env` is empty → browse filesystem to select
- Remember last-used CSV paths in state

### 3.6 Search UX Gaps

**Current search flow:**
1. Type query (pre-filled with last search)
2. See results table
3. Choose: "New Search", "Back", or "Main Menu"

**Missing:**
- **No pagination** — only first 25 results shown, no "Next Page"
- **No result actions** — can't pin, view details, or copy ID from search results
- **No filter by source** — always uses default source, no way to switch in search
- **No empty state guidance** — just "No results found" with no suggestions

### 3.7 Inconsistent Navigation Patterns

**Current issues:**
- `← Back` and `🏠 Main Menu` appear on every screen — good
- But their styling differs (some have emoji `🏠`, some don't)
- "Press Enter to continue" appears after some actions but not others
- No keyboard hints visible (the help screen mentions ↑/↓ but menus don't show this)

**Fix:** Standardize a `NAV_CHOICES` constant:
```python
NAV_CHOICES = [
    Separator(),
    Choice(title="← Back", value="back"),
    Choice(title="Home", value="home"),
]
```

### 3.8 Dual Menu Systems

**The old menu system** (`MENU_OPTIONS` variable in `cli.py`, lines 163-183) still exists:
```
  [S]tatus     Show database stats
  [I]mport     Import CSV data
  [F]ind       Search the library
  [R]un        Start the API server
  [Q]uickstart First-time setup wizard
  [D]atabase   Initialize or rebuild database
  [U]serdata   Export/import user-owned data
  [X] Exit
```

This is **dead code** — it's defined but never rendered because `_interactive_menu()` launches the TUI router instead. This should be removed to prevent confusion.

### 3.9 API Control Is Bare

**Current:** Shows connection info panel, then "Start API Server" (blocking). No way to check if server is already running, no health check, no stop option.

**Improvements:**
- **Health check** before start (hit `http://host:port/docs` and report status)
- **Background mode** option (don't block the TUI)
- **Show live log tail** after starting

### 3.10 No Onboarding Flow

**Current:** First-time users see the same menu as returning users. The only clue is "Database not initialized" in the header.

**Fix:** Detect first run (no DB file) and auto-route to setup wizard:
```python
if not settings.SX_DB_PATH.exists():
    return "setup_wizard"  # Auto-redirect
```

---

## 4. Current Tech Stack

| Component | Library | Role |
|---|---|---|
| CLI framework | `typer` | Command parsing, help generation, subcommands |
| Interactive prompts | `questionary` | Select menus, confirms (TUI screens) |
| Terminal styling | `rich` | Panels, tables, progress, tracebacks |
| Configuration | `pydantic-settings` | 30+ typed fields from `.env` |
| Database | `sqlite3` (stdlib) | Core data store |
| API server | `fastapi` + `uvicorn` | REST API for Obsidian plugin |
| Search | FTS5 (SQLite) | Full-text search |
| Shell orchestrator | `bash` (`scripts/sxctl.sh`) | Context management + dispatch |

---

## 5. File-by-File Reference

### TUI Infrastructure

| File | Lines | Purpose |
|---|---|---|
| `tui/__init__.py` | 10 | Exports `Navigator`, `Router`, `UIState` |
| `tui/navigator.py` | 88 | Stack-based navigation with breadcrumbs, screen labels |
| `tui/router.py` | 103 | Main event loop, `@register_screen` decorator, SCREENS registry |
| `tui/state.py` | 53 | `UIState` dataclass with `remember()`, `add_to_history()`, wizard state |
| `tui/components.py` | 170 | `render_header`, `render_breadcrumbs`, `render_result_panel`, `render_error`, `render_stats_table`, `confirm_destructive_action` |

### TUI Screens

| File | Lines | Key Feature |
|---|---|---|
| `screens/main.py` | 90 | Main menu + inline status display |
| `screens/search.py` | 105 | Search with pre-filled query, results table |
| `screens/sources.py` | 170 | Source CRUD with Rich table, inline add/set-default flows |
| `screens/import_wizard.py` | 181 | Multi-step: source → CSV → confirm → progress → next-actions |
| `screens/settings.py` | 76 | Read-only config display in Rich panel |
| `screens/api_control.py` | 91 | API info panel + blocking server start |
| `screens/userdata.py` | 90 | Export/import with path prompts |
| `screens/help.py` | 76 | Shortcuts, workflow overview, CLI commands |

### CLI Layer

| File | Lines | Purpose |
|---|---|---|
| `cli.py` | 1315 | Typer app with 15+ commands, fallback shims, interactive menu launcher |
| `settings.py` | 86 | `Settings` class, 30+ typed fields |

---

## 6. Improvement Roadmap — Prioritized

### Tier 1: Quick Wins (1-2 hours each)

| # | Improvement | Impact |
|---|---|---|
| 1 | **Remove emoji from menus** — use text-only labels with semantic icons where needed | Cleaner, more scannable |
| 2 | **Add custom questionary Style** — consistent brand colors (cyan/purple/white) | Polished, premium feel |
| 3 | **Remove dead MENU_OPTIONS** — clean up old unreachable code from `cli.py` | Less confusion |
| 4 | **Standardize NAV_CHOICES** — consistent back/home pattern across all screens | Professional consistency |
| 5 | **Auto-detect first run** — redirect to setup wizard when DB doesn't exist | Smooth onboarding |

### Tier 2: Medium Effort (half day each)

| # | Improvement | Impact |
|---|---|---|
| 6 | **Add pagination to search** — "Next 25" / "Previous 25" with offset tracking | Usable for large libraries |
| 7 | **Interactive settings editor** — edit top 5-6 settings inline, save to `.env` | No more manual file editing |
| 8 | **CSV file browser in import wizard** — browse for CSV instead of relying on `.env` | Self-service data loading |
| 9 | **API health check** — pre-check if server is running before start | Prevents confusion |
| 10 | **Search result actions** — "Copy ID", "View Details" on selected result | Actionable search |

### Tier 3: Larger Effort (1-2 days each)

| # | Improvement | Impact |
|---|---|---|
| 11 | **Path history manager** — MRU for CSV paths, vault paths, export paths | Never re-type paths |
| 12 | **Source-scoped search** — source picker before search query | Multi-source usability |
| 13 | **Dashboard screen** — replace "Status & Stats" with rich at-a-glance panel | Premium landing experience |
| 14 | **Profile-aware context** — unify `scripts/sxctl.sh` context model into Python TUI | Single tool, no shell scripts |

---

## 7. Comparison with DocuMorph

| Dimension | DocuMorph | sx_obsidian | Gap |
|---|---|---|---|
| **Menu styling** | Custom `questionary.Style` (purple/red) | Default styling | Add brand style |
| **Path management** | `PathManager` with MRU history, directory browser | Manual path entry via `.env` | Add path manager |
| **File status** | `[✓]`/`[ ]` indicators on file listing | No file status in TUI | Not directly applicable (DB-driven) |
| **Strategy pattern** | Pluggable cleaners via ABC | N/A (different domain) | N/A |
| **Navigation** | Loop-based menu | Stack-based router with breadcrumbs | sx_obsidian is *more* advanced |
| **Session state** | Basic (path history only) | `UIState` with session memory, wizard state | sx_obsidian is *more* advanced |
| **Reusable components** | `menu.py` monolith | Dedicated `components.py` + decorator registry | sx_obsidian is better structured |
| **Error handling** | try/except → Rich traceback | 3-part error panels + graceful Ctrl+C | sx_obsidian is more thorough |
| **Shell alias** | `dm` via `install_alias.sh` | `scripts/sxctl.sh` (40KB orchestrator) | Different scope |
| **Emoji usage** | Minimal, semantic only | Heavy decorative emoji | Reduce to semantic |

**Key Takeaway:** sx_obsidian's TUI architecture is actually *more sophisticated* than DocuMorph's (decorator registry, stack navigation, session state, component library). The improvements needed are mostly **surface-level UX polish** — not architectural changes.

---

## 8. Lessons from Building This System

| Lesson | Detail |
|---|---|
| **Typer + TUI coexistence works** | The `--menu` flag and fallback-to-TUI pattern lets power users use CLI flags while beginners get the interactive UI |
| **Decorator registry scales** | Adding a new screen = one file + one decorator. No wiring needed |
| **Session state transforms UX** | Pre-filling last search query, remembering last source — small changes, massive usability improvement |
| **Wizard pattern for multi-step** | The import wizard's source → CSV → confirm → progress → next-actions flow prevents user errors |
| **Consistent components matter** | `render_result_panel` and `render_error` ensure every screen looks the same |
| **Read-only settings screens frustrate** | Telling users to "edit .env" is a dead-end. Even a basic inline editor is better |
| **Emoji is seasoning, not substance** | One or two meaningful icons per screen. Not one per menu item |
