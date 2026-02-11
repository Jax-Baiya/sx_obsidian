from __future__ import annotations

import json
import re
import gzip
from datetime import datetime
from pathlib import Path
from typing import Annotated, Optional

try:
    import typer  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    typer = None

try:
    from rich import print  # type: ignore
    from rich.console import Console  # type: ignore
    from rich.panel import Panel  # type: ignore
    from rich.progress import Progress, SpinnerColumn, TextColumn  # type: ignore
    from rich.prompt import Confirm, IntPrompt, Prompt  # type: ignore
    from rich.table import Table  # type: ignore
    from rich.text import Text  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    # Minimal fallbacks so importing this module doesn't require rich.
    import builtins as _builtins  # type: ignore

    print = _builtins.print  # type: ignore

    class Console:  # type: ignore
        def print(self, *args, **kwargs):
            print(*args)

    class Panel:  # type: ignore
        @staticmethod
        def fit(content, *args, **kwargs):
            return content

    class _NoopCM:  # type: ignore
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def add_task(self, *args, **kwargs):
            return 0

    class Progress(_NoopCM):  # type: ignore
        pass

    class SpinnerColumn:  # type: ignore
        pass

    class TextColumn:  # type: ignore
        def __init__(self, *args, **kwargs):
            pass

    class Confirm:  # type: ignore
        @staticmethod
        def ask(*args, **kwargs):
            return False

    class IntPrompt:  # type: ignore
        @staticmethod
        def ask(*args, **kwargs):
            return 0

    class Prompt:  # type: ignore
        @staticmethod
        def ask(*args, **kwargs):
            return ""

    class Table:  # type: ignore
        def __init__(self, *args, **kwargs):
            pass

        def add_column(self, *args, **kwargs):
            pass

        def add_row(self, *args, **kwargs):
            pass

    class Text(str):  # type: ignore
        pass


if typer is None:  # pragma: no cover
    # Lightweight Typer shim so tests can import and call functions.
    class _TyperShim:  # type: ignore
        def __init__(self, *args, **kwargs):
            pass

        def callback(self, *args, **kwargs):
            def deco(fn):
                return fn

            return deco

        def command(self, *args, **kwargs):
            def deco(fn):
                return fn

            return deco

        def __call__(self, *args, **kwargs):
            raise RuntimeError("typer is not installed")

    class _Exit(SystemExit):
        def __init__(self, code: int = 0):
            super().__init__(code)

    def _opt(*args, **kwargs):
        return None

    def _arg(*args, **kwargs):
        return None

    class _Context:  # type: ignore
        invoked_subcommand = None

    class typer:  # type: ignore
        Typer = _TyperShim
        Exit = _Exit
        Option = staticmethod(_opt)
        Argument = staticmethod(_arg)
        Context = _Context

from .db import connect, init_db, rebuild_fts
from .importer import import_all
from .search import search as search_fn
from .settings import load_settings
from sx.paths import PathResolver

app = typer.Typer(
    add_completion=False,
    help="sx_db: SQLite library + API for sx_obsidian",
    rich_markup_mode="rich",
)
console = Console()

# ═══════════════════════════════════════════════════════════════════════════════
# BANNER & HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

BANNER = """
[bold cyan]╔═══════════════════════════════════════════════════════════════╗
║           [white]sx_db[/white] - SQLite Library for sx_obsidian            ║
╚═══════════════════════════════════════════════════════════════╝[/bold cyan]
"""

MENU_OPTIONS = """
[bold]Main Menu[/bold]

  [cyan][S][/cyan]tatus     Show database stats and configuration
  [cyan][I][/cyan]mport     Import CSV data into database
  [cyan][F][/cyan]ind       Search the library
  [cyan][R][/cyan]un        Start the API server
  
  [dim]────────────────────────────────────────[/dim]
  
  [cyan][Q][/cyan]uickstart First-time setup wizard (init → import → run)
  [cyan][D][/cyan]atabase   Initialize or rebuild database

    [dim]────────────────────────────────────────[/dim]

    [cyan][U][/cyan]serdata   Export/import user-owned data (notes + meta)
  
  [dim]────────────────────────────────────────[/dim]
  
  [red][X][/red] Exit
"""


def _open_text_maybe_gzip(path: Path, mode: str):
        """Open a text stream, using gzip when suffix is .gz.

        Mode should be 'rt' or 'wt'.
        """

        if path.suffix.lower() == ".gz":
                return gzip.open(path, mode, encoding="utf-8")
        return path.open(mode, encoding="utf-8")


def _print_next_steps(steps: list[str]) -> None:
    """Print suggested next steps."""
    console.print("\n[bold green]✓ Done![/bold green]")
    if steps:
        console.print("\n[bold]Next steps:[/bold]")
        for i, step in enumerate(steps, 1):
            console.print(f"  {i}. {step}")


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN CALLBACK
# ═══════════════════════════════════════════════════════════════════════════════

@app.callback(invoke_without_command=True)
def _root(
    ctx: typer.Context,
    menu: bool = typer.Option(
        False,
        "--menu",
        help="Launch the interactive menu (same as running with no command)",
    ),
):
    """
    [bold]sx_db[/bold]: SQLite library + API for the sx_obsidian Obsidian plugin.
    
    [dim]Run without arguments to launch the interactive menu.[/dim]
    
    [bold]Quick Commands:[/bold]
      sx_db status      Show database stats
      sx_db import      Import CSV data
      sx_db find        Search the library
      sx_db run         Start the API server
      sx_db setup       First-time quickstart wizard
    
    [bold]Examples:[/bold]
      python -m sx_db setup              # First time? Start here!
      python -m sx_db find "travel"      # Search for "travel"
      python -m sx_db run                # Start API for Obsidian plugin
    """
    if menu and ctx.invoked_subcommand is None:
        _interactive_menu()
        raise typer.Exit(code=0)

    if ctx.invoked_subcommand is None:
        _interactive_menu()
        raise typer.Exit(code=0)


# ═══════════════════════════════════════════════════════════════════════════════
# COMMANDS
# ═══════════════════════════════════════════════════════════════════════════════

@app.command("status", help="[bold cyan]S[/bold cyan]how database stats and configuration")
@app.command("stats", hidden=True)  # Alias
def status():
    """Show database stats and current configuration."""
    s = load_settings()
    
    console.print(Panel.fit(
        "\n".join([
            f"[bold]Database:[/bold]     {s.SX_DB_PATH}",
            f"[bold]API Server:[/bold]   http://{s.SX_API_HOST}:{s.SX_API_PORT}",
            f"[bold]FTS Enabled:[/bold]  {s.SX_DB_ENABLE_FTS}",
            "",
            f"[dim]CSV Sources:[/dim]",
            f"  consolidated: {s.CSV_consolidated_1 or '[red](not set)[/red]'}",
            f"  authors:      {s.CSV_authors_1 or '[dim](not set)[/dim]'}",
            f"  bookmarks:    {s.CSV_bookmarks_1 or '[dim](not set)[/dim]'}",
        ]),
        title="[bold]Configuration[/bold]"
    ))
    
    try:
        conn = connect(s.SX_DB_PATH)
        init_db(conn, enable_fts=s.SX_DB_ENABLE_FTS)
        
        total = conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0]
        bookmarked = conn.execute("SELECT COUNT(*) FROM videos WHERE bookmarked=1").fetchone()[0]
        authors_count = conn.execute(
            "SELECT COUNT(DISTINCT author_unique_id) FROM videos WHERE author_unique_id IS NOT NULL AND author_unique_id != ''"
        ).fetchone()[0]
        
        has_fts = bool(conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='videos_fts'"
        ).fetchone())
        fts_rows = conn.execute("SELECT COUNT(*) FROM videos_fts").fetchone()[0] if has_fts else 0
        
        t = Table(title="[bold]Database Stats[/bold]", show_header=False)
        t.add_column("Metric", style="bold")
        t.add_column("Value", style="cyan", justify="right")
        t.add_row("Total items", f"{total:,}")
        t.add_row("Bookmarked", f"{bookmarked:,}")
        t.add_row("Unique authors", f"{authors_count:,}")
        t.add_row("FTS indexed", f"{fts_rows:,}" if has_fts else "[dim]N/A[/dim]")
        console.print(t)
        
    except Exception as e:
        console.print(f"[yellow]Database not ready:[/yellow] {e}")
        console.print("\n[dim]Run[/dim] [cyan]sx_db setup[/cyan] [dim]to get started.[/dim]")


@app.command("import", help="[bold cyan]I[/bold cyan]mport CSV data into database")
@app.command("import-csv", hidden=True)  # Backwards compatibility
@app.command("load", hidden=True)  # Alias
def import_data(
    consolidated: Optional[str] = typer.Option(None, "--csv", "-c", help="Consolidated CSV path"),
    authors: Optional[str] = typer.Option(None, "--authors", "-a", help="Authors CSV path"),
    bookmarks: Optional[str] = typer.Option(None, "--bookmarks", "-b", help="Bookmarks CSV path"),
    rebuild_index: bool = typer.Option(True, "--index/--no-index", help="Rebuild FTS after import"),
):
    """Import CSV sources into the SQLite database."""
    s = load_settings()

    # When called as a normal Python function (e.g. from the interactive menu),
    # Typer's defaults are OptionInfo objects, not actual strings.
    if consolidated is not None and not isinstance(consolidated, str):
        consolidated = None
    if authors is not None and not isinstance(authors, str):
        authors = None
    if bookmarks is not None and not isinstance(bookmarks, str):
        bookmarks = None
    
    consolidated = consolidated or s.CSV_consolidated_1
    authors = authors or s.CSV_authors_1
    bookmarks = bookmarks or s.CSV_bookmarks_1
    
    if not consolidated:
        console.print("[red]Error:[/red] No consolidated CSV provided.")
        console.print("[dim]Set CSV_consolidated_1 in .env or use --csv path/to/file.csv[/dim]")
        raise typer.Exit(code=1)
    
    console.print(f"[dim]Importing from:[/dim] {consolidated}")
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        progress.add_task("Connecting to database...", total=None)
        conn = connect(s.SX_DB_PATH)
        init_db(conn, enable_fts=s.SX_DB_ENABLE_FTS)
        
        progress.add_task("Importing CSV data...", total=None)
        stats = import_all(conn, consolidated, authors, bookmarks)
        
        if rebuild_index:
            progress.add_task("Rebuilding search index...", total=None)
            rebuild_fts(conn)
    
    console.print(Panel.fit(
        f"[bold green]✓ Import complete![/bold green]\n\n"
        f"  Inserted: [cyan]{stats.inserted:,}[/cyan]\n"
        f"  Updated:  [cyan]{stats.updated:,}[/cyan]\n"
        f"  Skipped:  [dim]{stats.skipped:,}[/dim]",
        title="Results"
    ))
    
    _print_next_steps([
        "[cyan]sx_db run[/cyan] - Start the API server for the Obsidian plugin",
        "[cyan]sx_db find \"query\"[/cyan] - Search your library",
    ])


@app.command("prune-missing-media", help="Delete DB rows whose expected media files are missing")
def prune_missing_media(
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Actually delete rows (default is dry-run).",
    ),
    require_cover: bool = typer.Option(
        True,
        "--require-cover/--no-require-cover",
        help="If enabled, treat missing cover as missing media too.",
    ),
    limit: int = typer.Option(
        0,
        "--limit",
        help="Optional safety limit for how many rows to delete (0 = no limit).",
    ),
):
    """Audit (and optionally delete) rows whose media isn't present on disk.

    This is intentionally conservative:
    - By default it's a dry-run.
    - Deletion cascades to user-owned tables via foreign keys.

    It uses VAULT_default/DATA_DIR and checks the *runtime OS* filesystem
    (important when PATH_STYLE=windows but running under Linux/WSL).
    """

    s = load_settings()
    conn = connect(s.SX_DB_PATH)
    init_db(conn, enable_fts=s.SX_DB_ENABLE_FTS)

    resolver = PathResolver(
        {
            "path_style": s.PATH_STYLE,
            "vault": s.VAULT_default,
            "vault_windows": s.VAULT_WINDOWS_default,
            "data_dir": s.DATA_DIR,
        }
    )

    if not resolver.vault_os_root and not resolver.vault_root:
        console.print("[red]Error:[/red] VAULT_default is not configured; cannot check filesystem existence.")
        raise typer.Exit(code=1)

    rows = conn.execute(
        "SELECT id, author_id, bookmarked, video_path, cover_path FROM videos"
    ).fetchall()

    missing: list[str] = []
    missing_video = 0
    missing_cover = 0
    checked = 0

    for r in rows:
        checked += 1
        vid = str(r["id"])
        author_id = str(r["author_id"] or "").strip() or None
        is_bookmarked = bool(int(r["bookmarked"] or 0))

        video_path = (r["video_path"] or "").strip() or None
        cover_path = (r["cover_path"] or "").strip() or None

        # Canonical fallback when DB row lacks explicit paths.
        if not video_path or not cover_path:
            base = "Favorites" if is_bookmarked else (f"Following/{author_id}" if author_id else "Following")
            if not video_path:
                video_path = f"{base}/videos/{vid}.mp4"
            if not cover_path:
                cover_path = f"{base}/covers/{vid}.jpg"

        has_video = resolver.exists(video_path)
        has_cover = resolver.exists(cover_path) if cover_path else True

        if not has_video:
            missing_video += 1
        if cover_path and not has_cover:
            missing_cover += 1

        is_missing = (not has_video) or (require_cover and cover_path and not has_cover)
        if is_missing:
            missing.append(vid)
            if limit and len(missing) >= limit:
                break

    console.print(
        Panel.fit(
            "\n".join(
                [
                    f"Checked: [cyan]{checked:,}[/cyan]",
                    f"Missing video: [yellow]{missing_video:,}[/yellow]",
                    f"Missing cover: [yellow]{missing_cover:,}[/yellow]",
                    f"Rows to prune (per rules): [bold red]{len(missing):,}[/bold red]",
                    "",
                    f"Mode: {'APPLY (deleting)' if apply else 'DRY-RUN (no deletions)'}",
                ]
            ),
            title="[bold]Media Presence Audit[/bold]",
        )
    )

    if not missing:
        return

    if not apply:
        console.print("\n[dim]Nothing deleted. Re-run with --apply to delete the rows above.[/dim]")
        return

    # Delete in chunks to keep SQL parameter lists reasonable.
    deleted = 0
    chunk_size = 500
    for i in range(0, len(missing), chunk_size):
        chunk = missing[i : i + chunk_size]
        conn.execute(
            "DELETE FROM videos WHERE id IN (" + ",".join(["?"] * len(chunk)) + ")",
            chunk,
        )
        deleted += len(chunk)
    conn.commit()

    console.print(f"\n[bold green]✓ Deleted {deleted:,} row(s) from videos[/bold green] (cascades to notes/meta).")


@app.command("find", help="[bold cyan]F[/bold cyan]ind items in the library")
@app.command("search", hidden=True)  # Alias
def find(
    query: str = typer.Argument("", help="Search query (FTS5 if enabled)"),
    limit: int = typer.Option(25, "-n", "--limit", help="Max results"),
    offset: int = typer.Option(0, "--offset", help="Offset for paging"),
    json_out: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Search the library by caption, author, or ID."""
    s = load_settings()
    conn = connect(s.SX_DB_PATH)
    init_db(conn, enable_fts=s.SX_DB_ENABLE_FTS)
    
    results = search_fn(conn, query, limit=limit, offset=offset)
    
    if json_out:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return
    
    if not results:
        console.print(f"[yellow]No results found for:[/yellow] {query!r}")
        return
    
    t = Table(title=f"[bold]Results for: [cyan]{query or '(all)'}[/cyan][/bold]")
    t.add_column("ID", style="cyan", no_wrap=True)
    t.add_column("★", justify="center", width=2)
    t.add_column("Author", style="magenta")
    t.add_column("Caption", max_width=60)
    
    for r in results:
        t.add_row(
            str(r.get("id")),
            "★" if r.get("bookmarked") else "",
            str(r.get("author_unique_id") or r.get("author_name") or ""),
            str(r.get("snippet") or "")[:60],
        )
    
    console.print(t)
    console.print(f"[dim]Showing {len(results)} results. Use --limit to see more.[/dim]")


@app.command("run", help="[bold cyan]R[/bold cyan]un the API server")
@app.command("serve", hidden=True)  # Alias
def run(
    host: Annotated[
        Optional[str],
        typer.Option(help="Host to bind"),
    ] = None,
    port: Annotated[
        Optional[int],
        typer.Option(help="Port to bind"),
    ] = None,
):
    """Start the FastAPI server for the Obsidian plugin."""
    import uvicorn

    from .logging import setup_api_logging
    
    s = load_settings()
    host = host or s.SX_API_HOST
    port = port or s.SX_API_PORT

    # Enable bounded diagnostic logs (rotating file, auto-deletes older files).
    log_file = setup_api_logging(s)
    
    console.print(Panel.fit(
        f"[bold]API Server starting...[/bold]\n\n"
        f"  URL:  [cyan]http://{host}:{port}[/cyan]\n"
        f"  Docs: [cyan]http://{host}:{port}/docs[/cyan]\n\n"
        f"  Logs: [cyan]{log_file}[/cyan]\n\n"
        f"[dim]Press CTRL+C to stop[/dim]",
        title="[bold green]sx_db API[/bold green]"
    ))
    
    uvicorn.run(
        "sx_db.app:app",
        host=host,
        port=port,
        reload=False,
        access_log=bool(getattr(s, "SX_API_LOG_ACCESS", False)),
        log_config=None,
    )


@app.command("setup", help="[bold cyan]Q[/bold cyan]uickstart wizard for first-time setup")
@app.command("quickstart", hidden=True)  # Alias
def setup():
    """First-time setup wizard: initialize database, import data, and start server."""
    console.print(BANNER)
    console.print("[bold]Welcome to the sx_db setup wizard![/bold]")
    console.print("[dim]This will guide you through setting up the database and API.[/dim]\n")
    
    s = load_settings()
    
    # Step 1: Check configuration
    console.print("[bold]Step 1: Configuration Check[/bold]")
    if not s.CSV_consolidated_1:
        console.print("[red]✗[/red] No CSV_consolidated_1 configured in .env")
        console.print("[dim]Please edit .env and set CSV_consolidated_1=/path/to/consolidated.csv[/dim]")
        raise typer.Exit(code=1)
    console.print(f"[green]✓[/green] CSV source: {s.CSV_consolidated_1}")
    
    # Step 2: Initialize database
    console.print("\n[bold]Step 2: Initialize Database[/bold]")
    with Progress(SpinnerColumn(), TextColumn("{task.description}"), console=console) as progress:
        progress.add_task("Creating database...", total=None)
        conn = connect(s.SX_DB_PATH)
        init_db(conn, enable_fts=s.SX_DB_ENABLE_FTS)
    console.print(f"[green]✓[/green] Database ready at: {s.SX_DB_PATH}")
    
    # Step 3: Import data
    console.print("\n[bold]Step 3: Import Data[/bold]")
    if Confirm.ask("Import CSV data now?", default=True):
        with Progress(SpinnerColumn(), TextColumn("{task.description}"), console=console) as progress:
            progress.add_task("Importing data...", total=None)
            stats = import_all(conn, s.CSV_consolidated_1, s.CSV_authors_1, s.CSV_bookmarks_1)
            progress.add_task("Building search index...", total=None)
            rebuild_fts(conn)
        console.print(f"[green]✓[/green] Imported {stats.inserted + stats.updated:,} items")
    else:
        console.print("[dim]Skipped. Run 'sx_db import' later.[/dim]")
    
    # Step 4: Start server
    console.print("\n[bold]Step 4: Start API Server[/bold]")
    console.print(f"[dim]The Obsidian plugin will connect to http://{s.SX_API_HOST}:{s.SX_API_PORT}[/dim]")
    
    if Confirm.ask("Start the API server now?", default=True):
        run()
    else:
        console.print("\n[bold green]Setup complete![/bold green]")
        console.print("Run [cyan]sx_db run[/cyan] when you're ready to start the API server.")


@app.command("db", help="[bold cyan]D[/bold cyan]atabase operations (init/rebuild)")
@app.command("init", hidden=True)  # Alias
def database(
    rebuild: bool = typer.Option(False, "--rebuild", "-r", help="Rebuild FTS index"),
):
    """Initialize database or rebuild the search index."""
    s = load_settings()
    
    with Progress(SpinnerColumn(), TextColumn("{task.description}"), console=console) as progress:
        progress.add_task("Initializing database...", total=None)
        conn = connect(s.SX_DB_PATH)
        init_db(conn, enable_fts=s.SX_DB_ENABLE_FTS)
        
        if rebuild:
            progress.add_task("Rebuilding search index...", total=None)
            rebuild_fts(conn)
    
    console.print(f"[green]✓[/green] Database ready at: [cyan]{s.SX_DB_PATH}[/cyan]")
    if rebuild:
        console.print("[green]✓[/green] Search index rebuilt")


@app.command("export-userdata", help="Export user-owned tables (user_meta + video_notes) to JSONL")
def export_userdata(
    out: str = typer.Option(
        "exports/sx_userdata.jsonl.gz",
        "--out",
        "-o",
        help="Output path (.jsonl or .jsonl.gz). Relative paths are relative to CWD.",
    ),
    include_meta: bool = typer.Option(True, "--meta/--no-meta", help="Include user_meta"),
    include_notes: bool = typer.Option(True, "--notes/--no-notes", help="Include video_notes"),
):
    """Export user-owned data so you can rebuild the DB without losing your edits.

    Typical flow after a DB reset:
      1) sx_db import
      2) sx_db import-userdata --in exports/sx_userdata.jsonl.gz
    """

    out_path = Path(out).expanduser()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    s = load_settings()
    conn = connect(s.SX_DB_PATH)
    init_db(conn, enable_fts=s.SX_DB_ENABLE_FTS)

    exported_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    header = {
        "type": "sx_userdata_export",
        "version": 2,
        "exported_at": exported_at,
        "db_path": str(s.SX_DB_PATH),
        "includes": {"user_meta": bool(include_meta), "video_notes": bool(include_notes)},
    }

    meta_rows = []
    note_rows = []
    if include_meta:
        meta_rows = conn.execute(
                        """
                        SELECT
                            video_id,
                            rating,
                            status,
                            statuses,
                            tags,
                            notes,
                            product_link,
                            platform_targets,
                            workflow_log,
                            post_url,
                            published_time,
                            updated_at
                        FROM user_meta
                        """
        ).fetchall()
    if include_notes:
        note_rows = conn.execute(
            "SELECT video_id, markdown, template_version, updated_at FROM video_notes"
        ).fetchall()

    with _open_text_maybe_gzip(out_path, "wt") as f:
        f.write(json.dumps(header, ensure_ascii=False) + "\n")
        meta_count = 0
        note_count = 0

        for r in meta_rows:
            obj = {"type": "user_meta", **dict(r)}
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")
            meta_count += 1

        for r in note_rows:
            obj = {"type": "video_note", **dict(r)}
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")
            note_count += 1

    console.print(Panel.fit(
        "\n".join(
            [
                f"[bold green]✓ Export complete[/bold green]",
                f"Output: [cyan]{out_path}[/cyan]",
                f"user_meta rows: [cyan]{meta_count:,}[/cyan]",
                f"video_notes rows: [cyan]{note_count:,}[/cyan]",
            ]
        ),
        title="Userdata Export",
    ))


@app.command("import-userdata", help="Import JSONL user-owned tables (user_meta + video_notes)")
def import_userdata(
    input_path: str = typer.Option(
        "exports/sx_userdata.jsonl.gz",
        "--in",
        "-i",
        help="Input path (.jsonl or .jsonl.gz) created by export-userdata",
    ),
    overwrite: bool = typer.Option(True, "--overwrite/--no-overwrite", help="Overwrite existing rows"),
    strict: bool = typer.Option(False, "--strict", help="Fail if a referenced video_id is missing"),
    max_rows: int = typer.Option(0, "--max-rows", help="Safety cap (0 = no limit)"),
):
    """Import user-owned data after a DB rebuild.

    This never imports the canonical `videos` table (that comes from CSV). It only restores
    user-owned tables.
    """

    in_path = Path(input_path).expanduser()
    if not in_path.exists():
        console.print(f"[red]Error:[/red] File not found: {in_path}")
        raise typer.Exit(code=1)

    s = load_settings()
    conn = connect(s.SX_DB_PATH)
    init_db(conn, enable_fts=s.SX_DB_ENABLE_FTS)

    meta_in = 0
    meta_upserted = 0
    meta_skipped_missing = 0
    meta_skipped_exists = 0

    notes_in = 0
    notes_upserted = 0
    notes_skipped_missing = 0
    notes_skipped_exists = 0

    def video_exists(video_id: str) -> bool:
        return bool(conn.execute("SELECT 1 FROM videos WHERE id=?", (video_id,)).fetchone())

    conn.execute("BEGIN")

    with _open_text_maybe_gzip(in_path, "rt") as f:
        for line_no, line in enumerate(f, 1):
            if max_rows and (meta_in + notes_in) >= max_rows:
                break
            line = line.strip()
            if not line:
                continue

            try:
                obj = json.loads(line)
            except Exception:
                console.print(f"[yellow]Skipping invalid JSON at line {line_no}[/yellow]")
                continue

            rtype = obj.get("type")
            if rtype in ("sx_userdata_export", "header"):
                continue

            if rtype == "user_meta":
                meta_in += 1
                vid = str(obj.get("video_id") or "").strip()
                if not vid:
                    continue
                if not video_exists(vid):
                    meta_skipped_missing += 1
                    if strict:
                        raise typer.Exit(code=2)
                    continue

                if overwrite:
                    conn.execute(
                        """
                                                INSERT INTO user_meta(
                                                    video_id,
                                                    rating,
                                                    status,
                                                    statuses,
                                                    tags,
                                                    notes,
                                                    product_link,
                                                    platform_targets,
                                                    workflow_log,
                                                    post_url,
                                                    published_time,
                                                    updated_at
                                                )
                                                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(video_id) DO UPDATE SET
                          rating=excluded.rating,
                          status=excluded.status,
                                                    statuses=excluded.statuses,
                          tags=excluded.tags,
                          notes=excluded.notes,
                                                    product_link=excluded.product_link,
                                                    platform_targets=excluded.platform_targets,
                                                    workflow_log=excluded.workflow_log,
                                                    post_url=excluded.post_url,
                                                    published_time=excluded.published_time,
                          updated_at=excluded.updated_at
                        """,
                        (
                            vid,
                            obj.get("rating"),
                            obj.get("status"),
                                                        obj.get("statuses"),
                            obj.get("tags"),
                            obj.get("notes"),
                                                        obj.get("product_link"),
                                                        obj.get("platform_targets"),
                                                        obj.get("workflow_log"),
                                                        obj.get("post_url"),
                                                        obj.get("published_time"),
                            obj.get("updated_at"),
                        ),
                    )
                    meta_upserted += 1
                else:
                    cur = conn.execute(
                        """
                                                INSERT OR IGNORE INTO user_meta(
                                                    video_id,
                                                    rating,
                                                    status,
                                                    statuses,
                                                    tags,
                                                    notes,
                                                    product_link,
                                                    platform_targets,
                                                    workflow_log,
                                                    post_url,
                                                    published_time,
                                                    updated_at
                                                )
                                                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            vid,
                            obj.get("rating"),
                            obj.get("status"),
                                                        obj.get("statuses"),
                            obj.get("tags"),
                            obj.get("notes"),
                                                        obj.get("product_link"),
                                                        obj.get("platform_targets"),
                                                        obj.get("workflow_log"),
                                                        obj.get("post_url"),
                                                        obj.get("published_time"),
                            obj.get("updated_at"),
                        ),
                    )
                    if cur.rowcount == 0:
                        meta_skipped_exists += 1
                    else:
                        meta_upserted += 1

            elif rtype == "video_note":
                notes_in += 1
                vid = str(obj.get("video_id") or "").strip()
                md = obj.get("markdown")
                if not vid or not md:
                    continue
                if not video_exists(vid):
                    notes_skipped_missing += 1
                    if strict:
                        raise typer.Exit(code=2)
                    continue

                if overwrite:
                    conn.execute(
                        """
                        INSERT INTO video_notes(video_id, markdown, template_version, updated_at)
                        VALUES(?, ?, ?, ?)
                        ON CONFLICT(video_id) DO UPDATE SET
                          markdown=excluded.markdown,
                          template_version=excluded.template_version,
                          updated_at=excluded.updated_at
                        """,
                        (
                            vid,
                            md,
                            obj.get("template_version"),
                            obj.get("updated_at"),
                        ),
                    )
                    notes_upserted += 1
                else:
                    cur = conn.execute(
                        """
                        INSERT OR IGNORE INTO video_notes(video_id, markdown, template_version, updated_at)
                        VALUES(?, ?, ?, ?)
                        """,
                        (
                            vid,
                            md,
                            obj.get("template_version"),
                            obj.get("updated_at"),
                        ),
                    )
                    if cur.rowcount == 0:
                        notes_skipped_exists += 1
                    else:
                        notes_upserted += 1

    conn.commit()

    console.print(Panel.fit(
        "\n".join(
            [
                f"[bold green]✓ Import complete[/bold green]",
                f"Input: [cyan]{in_path}[/cyan]",
                "",
                f"user_meta: {meta_upserted:,} applied (seen {meta_in:,}; missing video {meta_skipped_missing:,}; exists skipped {meta_skipped_exists:,})",
                f"video_notes: {notes_upserted:,} applied (seen {notes_in:,}; missing video {notes_skipped_missing:,}; exists skipped {notes_skipped_exists:,})",
            ]
        ),
        title="Userdata Import",
    ))


@app.command("media-index", help="Scan a folder and attach cover/video paths to items")
def media_index(
    root: Optional[str] = typer.Option(
        None,
        "--root",
        help="Filesystem root that contains your media data (defaults to SX_MEDIA_VAULT or VAULT_default)",
    ),
    data_dir: Optional[str] = typer.Option(
        None,
        "--data-dir",
        help="Media subfolder under root (defaults to SX_MEDIA_DATA_DIR or DATA_DIR; use '' for none)",
    ),
    apply: bool = typer.Option(False, "--apply", help="Write updates to the database"),
    overwrite: bool = typer.Option(
        False,
        "--overwrite",
        help="Overwrite existing cover_path/video_path values (default: only fill empty)",
    ),
    max_files: int = typer.Option(
        0,
        "--max-files",
        help="Safety limit for scanned files (0 = no limit)",
    ),
):
    """Populate `videos.cover_path` / `videos.video_path` by scanning for local media files.

    This enables:
    - thumbnails in the Obsidian library table view
    - opening video previews via the API streaming endpoint

    Expected convention: filenames contain the TikTok/Shorts ID (usually digits).
    Example: `7541402501124230417.mp4` or `7541402501124230417.jpg`.
    """

    s = load_settings()
    root_path = Path(root or s.SX_MEDIA_VAULT or s.VAULT_default or "").expanduser()
    if not root_path:
        console.print("[red]Error:[/red] No root configured. Set SX_MEDIA_VAULT (or VAULT_default) or pass --root.")
        raise typer.Exit(code=1)

    data_dir_val = data_dir if data_dir is not None else (s.SX_MEDIA_DATA_DIR or s.DATA_DIR)
    media_root = root_path if (data_dir_val in (None, "")) else (root_path / str(data_dir_val))

    if not media_root.exists() or not media_root.is_dir():
        console.print(f"[red]Error:[/red] Media folder not found: {media_root}")
        raise typer.Exit(code=1)

    def extract_id(stem: str) -> str | None:
        if stem.isdigit():
            return stem
        m = re.search(r"(\d{12,})", stem)
        return m.group(1) if m else None

    image_exts = {".jpg", ".jpeg", ".png", ".webp"}
    video_exts = {".mp4", ".mov", ".mkv", ".webm"}

    covers: dict[str, str] = {}
    videos: dict[str, str] = {}
    scanned = 0

    for p in media_root.rglob("*"):
        if max_files and scanned >= max_files:
            break
        if not p.is_file():
            continue
        scanned += 1

        ext = p.suffix.lower()
        if ext not in image_exts and ext not in video_exts:
            continue

        vid = extract_id(p.stem)
        if not vid:
            continue

        rel = p.relative_to(media_root).as_posix()
        if ext in image_exts and vid not in covers:
            covers[vid] = rel
        if ext in video_exts and vid not in videos:
            videos[vid] = rel

    console.print(Panel.fit(
        "\n".join(
            [
                f"[bold]Media root:[/bold] {media_root}",
                f"[bold]Scanned files:[/bold] {scanned:,}",
                f"[bold]Cover matches:[/bold] {len(covers):,}",
                f"[bold]Video matches:[/bold] {len(videos):,}",
                "",
                "[dim]Tip: run with --apply to write updates. Use --overwrite if you want to replace existing paths.[/dim]",
            ]
        ),
        title="[bold]Media Index[/bold]",
    ))

    if not apply:
        sample = next(iter(videos.items()), None) or next(iter(covers.items()), None)
        if sample:
            console.print(f"[dim]Sample mapping:[/dim] {sample[0]} → {sample[1]}")
        raise typer.Exit(code=0)

    conn = connect(s.SX_DB_PATH)
    init_db(conn, enable_fts=s.SX_DB_ENABLE_FTS)

    updated_cover = 0
    updated_video = 0

    if covers:
        if overwrite:
            cur = conn.executemany(
                "UPDATE videos SET cover_path=? WHERE id=?",
                [(path, vid) for vid, path in covers.items()],
            )
        else:
            cur = conn.executemany(
                "UPDATE videos SET cover_path=? WHERE id=? AND (cover_path IS NULL OR cover_path='')",
                [(path, vid) for vid, path in covers.items()],
            )
        updated_cover = cur.rowcount if cur.rowcount != -1 else 0

    if videos:
        if overwrite:
            cur = conn.executemany(
                "UPDATE videos SET video_path=? WHERE id=?",
                [(path, vid) for vid, path in videos.items()],
            )
        else:
            cur = conn.executemany(
                "UPDATE videos SET video_path=? WHERE id=? AND (video_path IS NULL OR video_path='')",
                [(path, vid) for vid, path in videos.items()],
            )
        updated_video = cur.rowcount if cur.rowcount != -1 else 0

    conn.commit()

    console.print(Panel.fit(
        f"[bold green]✓ Media paths updated[/bold green]\n\n"
        f"  cover_path updated: [cyan]{updated_cover:,}[/cyan]\n"
        f"  video_path updated: [cyan]{updated_video:,}[/cyan]",
        title="Results",
    ))


# ═══════════════════════════════════════════════════════════════════════════════
# INTERACTIVE MENU
# ═══════════════════════════════════════════════════════════════════════════════

def _interactive_menu() -> None:
    """User-friendly interactive menu with letter shortcuts."""
    console.print(BANNER)
    
    while True:
        console.print(MENU_OPTIONS)
        
        choice = Prompt.ask(
            "[bold]Choose an option[/bold]",
            default="s",
            show_default=False,
        ).strip().lower()
        
        if choice in ("x", "exit", "quit"):
            console.print("\n[dim]Goodbye! 👋[/dim]")
            return
        
        elif choice == "s":
            status()
        
        elif choice == "i":
            s = load_settings()
            csv = Prompt.ask(
                "CSV path",
                default=s.CSV_consolidated_1 or "",
            ).strip() or None
            
            if csv:
                import_data(consolidated=csv, rebuild_index=True)
            else:
                console.print("[yellow]No CSV path provided.[/yellow]")
        
        elif choice == "f":
            query = Prompt.ask("Search query", default="").strip()
            limit = IntPrompt.ask("Limit", default=25)
            find(query=query, limit=limit)
        
        elif choice == "r":
            console.print("[dim]Starting API server... Press CTRL+C to return to menu.[/dim]")
            try:
                run()
            except KeyboardInterrupt:
                console.print("\n[dim]Server stopped.[/dim]")
        
        elif choice in ("q", "quickstart"):
            setup()
        
        elif choice == "d":
            rebuild = Confirm.ask("Rebuild search index?", default=False)
            database(rebuild=rebuild)

        elif choice == "u":
            console.print("\n[bold]Userdata Export/Import[/bold]")
            sub = Prompt.ask(
                "Choose: [e]xport or [i]mport",
                default="e",
                show_default=False,
            ).strip().lower()
            if sub.startswith("e"):
                out = Prompt.ask("Output path", default="exports/sx_userdata.jsonl.gz").strip()
                export_userdata(out=out, include_meta=True, include_notes=True)
            elif sub.startswith("i"):
                inp = Prompt.ask("Input path", default="exports/sx_userdata.jsonl.gz").strip()
                overwrite = Confirm.ask("Overwrite existing rows?", default=True)
                import_userdata(input_path=inp, overwrite=overwrite, strict=False, max_rows=0)
            else:
                console.print("[yellow]Cancelled.[/yellow]")
        
        else:
            console.print(f"[yellow]Unknown option: {choice}[/yellow]")
        
        console.print()  # Spacing


def main():
    app()
