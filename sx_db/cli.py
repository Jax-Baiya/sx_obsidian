from __future__ import annotations

import json
import re
import gzip
import os
import subprocess
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

        def add_typer(self, *args, **kwargs):
            return None

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

from .db import (
    connect,
    ensure_source,
    get_default_source_id,
    init_db,
    list_sources,
    rebuild_fts,
    set_default_source,
)
from .importer import import_all
from .markdown import TEMPLATE_VERSION, render_note
from .repositories import PostgresRepository
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
║           [white]sx_db[/white] — SQLite Library for sx_obsidian            ║
╚═══════════════════════════════════════════════════════════════╝[/bold cyan]
"""


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _tail_text(path: Path, max_lines: int = 20) -> str:
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        return "\n".join(lines[-max_lines:])
    except Exception:
        return ""


def _doctor_shell_aliases() -> dict:
    home = Path.home()
    targets = [home / ".bash_aliases", home / ".bashrc"]

    result: dict = {
        "targets": [],
        "sxdb_defined_in": None,
        "sxdb_mode": None,
        "managed_block": False,
        "syntax": {},
    }

    for p in targets:
        info = {"path": str(p), "exists": p.exists()}
        text = ""
        if p.exists():
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                text = ""
        has_fn = "sxdb()" in text
        has_alias = bool(re.search(r"^[ \t]*alias[ \t]+sxdb=", text, flags=re.M))
        has_managed = "# >>> sx_db CLI (managed by install_alias.sh) >>>" in text
        info.update({
            "has_sxdb_function": has_fn,
            "has_sxdb_alias": has_alias,
            "has_managed_block": has_managed,
        })
        result["targets"].append(info)

        if result["sxdb_defined_in"] is None and (has_fn or has_alias):
            result["sxdb_defined_in"] = str(p)
            result["sxdb_mode"] = "function" if has_fn else "alias"
            result["managed_block"] = bool(has_managed)

        if p.exists():
            try:
                proc = subprocess.run(
                    ["bash", "-n", str(p)],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=4,
                )
                ok = proc.returncode == 0
                err = (proc.stderr or "").strip()
            except Exception as e:
                ok = False
                err = str(e)
            result["syntax"][str(p)] = {"ok": ok, "error": err}

    return result


def _doctor_port_listeners(port: int) -> dict:
    out = {"port": port, "listening": False, "pids": [], "details": []}

    # Prefer lsof if available.
    try:
        lsof = subprocess.run(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"],
            check=False,
            capture_output=True,
            text=True,
            timeout=4,
        )
        if lsof.returncode == 0 and lsof.stdout.strip():
            lines = [ln for ln in lsof.stdout.splitlines() if ln.strip()]
            out["details"] = lines[:8]
            for ln in lines[1:]:
                parts = ln.split()
                if len(parts) > 1 and parts[1].isdigit():
                    out["pids"].append(int(parts[1]))
            out["listening"] = True
            out["pids"] = sorted(set(out["pids"]))
            return out
    except Exception:
        pass

    # Fallback to ss.
    try:
        ss = subprocess.run(
            ["ss", "-ltnp"],
            check=False,
            capture_output=True,
            text=True,
            timeout=4,
        )
        if ss.returncode == 0 and ss.stdout:
            hits = []
            pids: set[int] = set()
            for ln in ss.stdout.splitlines():
                if f":{port} " not in ln and not ln.rstrip().endswith(f":{port}"):
                    continue
                hits.append(ln)
                for m in re.finditer(r"pid=(\d+)", ln):
                    pids.add(int(m.group(1)))
            if hits:
                out["listening"] = True
                out["details"] = hits[:8]
                out["pids"] = sorted(pids)
    except Exception:
        pass

    return out


def _doctor_latest_logs() -> dict:
    logs_dir = _project_root() / "_logs"
    payload = {"logs_dir": str(logs_dir), "exists": logs_dir.exists(), "latest": {}}
    if not logs_dir.exists():
        return payload

    patterns = {
        "prisma_pipeline": "prisma_pipeline_*.log",
        "prisma_studio": "prisma_studio_*.log",
        "api_tui": "sx_db_api_tui.log",
    }
    for key, pat in patterns.items():
        candidates = sorted(logs_dir.glob(pat), key=lambda p: p.stat().st_mtime, reverse=True)
        if not candidates:
            payload["latest"][key] = None
            continue
        latest = candidates[0]
        payload["latest"][key] = {
            "path": str(latest),
            "mtime": datetime.fromtimestamp(latest.stat().st_mtime).isoformat(timespec="seconds"),
            "tail": _tail_text(latest, max_lines=12),
        }

    return payload


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


def _normalize_source_id(raw: object, fallback: str = "default") -> str:
    s = str(raw or "").strip()
    if not s:
        s = str(fallback or "default").strip()
    s = re.sub(r"[^a-zA-Z0-9._-]", "", s)
    return s or "default"


def _parse_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        key = k.strip()
        val = v.strip()
        if not key:
            continue
        out[key] = val
    return out


def _extract_profile_index_from_source_id(source_id: str) -> int | None:
    m = re.search(r"(?:^|[_-])(?:p)?(\d{1,2})$", str(source_id or "").strip().lower())
    if not m:
        return None
    n = int(m.group(1))
    return n if n >= 1 else None


def _source_id_for_profile_index(env_map: dict[str, str], idx: int) -> str:
    explicit = str(env_map.get(f"SRC_PROFILE_{idx}_ID") or "").strip()
    if explicit:
        return _normalize_source_id(explicit)
    return _normalize_source_id(f"assets_{idx}")


def _wsl_to_windows_root(path_value: str | None) -> str | None:
    p = str(path_value or "").strip()
    if not p:
        return None
    m = re.match(r"^/mnt/([a-zA-Z])/(.*)$", p)
    if not m:
        return None
    drive = m.group(1).upper()
    tail = m.group(2).replace("/", "\\")
    return f"{drive}:\\{tail}" if tail else f"{drive}:\\"


def _resolver_for_source(s, source_id: str) -> PathResolver:
    env_map: dict[str, str] = dict(os.environ)
    sx_env = getattr(s, "SX_SCHEDULERX_ENV", None)
    # Only read the local .env when no explicit scheduler env is configured,
    # to avoid the project .env contaminating isolated profiles/tests.
    if not sx_env:
        env_map.update(_parse_env_file(Path(".env")))
    else:
        env_map.update(_parse_env_file(Path(sx_env)))

    sid = _normalize_source_id(source_id, fallback=_normalize_source_id(getattr(s, "SX_DEFAULT_SOURCE_ID", "default")))
    idx = _extract_profile_index_from_source_id(sid)
    if idx is None:
        for k in env_map.keys():
            m = re.match(r"^(SRC_PATH|SRC_PROFILE|VAULT)_(\d+)$", k)
            if not m:
                continue
            i = int(m.group(2))
            if _source_id_for_profile_index(env_map, i) == sid:
                idx = i
                break

    default_linux = getattr(s, "SX_MEDIA_VAULT", None) or getattr(s, "VAULT_default", None)
    default_windows = getattr(s, "VAULT_WINDOWS_default", None)
    linux_root = default_linux
    windows_root = default_windows
    group_link_prefix: str | None = None

    if idx is not None:
        src_root = (
            env_map.get(f"SRC_PATH_{idx}")
            or env_map.get(f"SRC_PROFILE_{idx}")
            or ""
        ).strip()
        vault_root = (env_map.get(f"VAULT_{idx}") or src_root).strip()
        linux_root = src_root or vault_root or default_linux
        windows_root = (
            env_map.get(f"SRC_PATH_WINDOWS_{idx}")
            or env_map.get(f"SRC_PROFILE_WINDOWS_{idx}")
            or env_map.get(f"VAULT_WINDOWS_{idx}")
            or env_map.get(f"VAULT_WIN_{idx}")
            or _wsl_to_windows_root(linux_root)
            or default_windows
        )

        explicit_group = (
            env_map.get(f"PATHLINKER_GROUP_{idx}")
            or env_map.get(f"GROUP_LINK_{idx}")
            or ""
        ).strip().strip("/")
        if explicit_group:
            group_link_prefix = explicit_group
        elif src_root and vault_root and src_root != vault_root:
            group_link_prefix = sid

    return PathResolver(
        {
            "path_style": getattr(s, "PATH_STYLE", "linux"),
            "vault": linux_root,
            "vault_windows": windows_root,
            "data_dir": getattr(s, "SX_MEDIA_DATA_DIR", None) or getattr(s, "DATA_DIR", "data"),
            "group_link_prefix": group_link_prefix,
        }
    )


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
def status(
    source: Optional[str] = typer.Option(
        None,
        "--source",
        help="Source ID scope for counts (default: DB default source)",
    ),
):
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

        sid = _normalize_source_id(source, fallback=get_default_source_id(conn, _normalize_source_id(s.SX_DEFAULT_SOURCE_ID)))
        ensure_source(conn, sid, label=sid)
        conn.commit()
        
        total = conn.execute("SELECT COUNT(*) FROM videos WHERE source_id=?", (sid,)).fetchone()[0]
        bookmarked = conn.execute("SELECT COUNT(*) FROM videos WHERE source_id=? AND bookmarked=1", (sid,)).fetchone()[0]
        authors_count = conn.execute(
            "SELECT COUNT(DISTINCT author_unique_id) FROM videos WHERE source_id=? AND author_unique_id IS NOT NULL AND author_unique_id != ''",
            (sid,),
        ).fetchone()[0]
        
        has_fts = bool(conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='videos_fts'"
        ).fetchone())
        fts_rows = conn.execute("SELECT COUNT(*) FROM videos_fts WHERE source_id=?", (sid,)).fetchone()[0] if has_fts else 0
        
        t = Table(title="[bold]Database Stats[/bold]", show_header=False)
        t.add_column("Metric", style="bold")
        t.add_column("Value", style="cyan", justify="right")
        t.add_row("Source", sid)
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
    source: Optional[str] = typer.Option(None, "--source", help="Source ID to import into"),
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
    source_id = _normalize_source_id(source, fallback=_normalize_source_id(s.SX_DEFAULT_SOURCE_ID))
    backend_mode = str(getattr(s, "SX_DB_BACKEND_MODE", "SQLITE") or "SQLITE").strip().upper()
    
    if not consolidated:
        console.print("[red]Error:[/red] No consolidated CSV provided.")
        console.print("[dim]Set CSV_consolidated_1 in .env or use --csv path/to/file.csv[/dim]")
        raise typer.Exit(code=1)
    
    console.print(f"[dim]Importing from:[/dim] {consolidated}")
    console.print(f"[dim]Source:[/dim] {source_id}")
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        progress.add_task("Connecting to database...", total=None)
        if backend_mode == "POSTGRES_PRIMARY":
            repo = PostgresRepository(s)
            repo.init_schema(source_id)
            conn = repo.connection_for_source(source_id)
            stats = import_all(conn, consolidated, authors, bookmarks, source_id=source_id)
            conn.commit()
        else:
            conn = connect(s.SX_DB_PATH)
            init_db(conn, enable_fts=s.SX_DB_ENABLE_FTS)
            ensure_source(conn, source_id, label=source_id)
            conn.commit()
            
            progress.add_task("Importing CSV data...", total=None)
            stats = import_all(conn, consolidated, authors, bookmarks, source_id=source_id)
            
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


@app.command("pg-bootstrap", help="Bootstrap PostgreSQL schema mapping for a source profile")
def pg_bootstrap(
    source: str = typer.Option("default", "--source", help="Source ID to bootstrap"),
):
    s = load_settings()
    backend_mode = str(getattr(s, "SX_DB_BACKEND_MODE", "SQLITE") or "SQLITE").strip().upper()
    if backend_mode != "POSTGRES_PRIMARY":
        console.print("[yellow]SX_DB_BACKEND_MODE is not POSTGRES_PRIMARY; nothing to bootstrap.[/yellow]")
        raise typer.Exit(code=0)

    sid = _normalize_source_id(source, fallback=_normalize_source_id(s.SX_DEFAULT_SOURCE_ID))
    repo = PostgresRepository(s)
    out = repo.init_schema(sid)
    console.print(
        Panel.fit(
            f"[bold green]✓ PostgreSQL schema initialized[/bold green]\n\n"
            f"  source_id: [cyan]{out.get('source_id')}[/cyan]\n"
            f"  schema:    [cyan]{out.get('schema')}[/cyan]",
            title="PostgreSQL Bootstrap",
        )
    )


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
    source: Optional[str] = typer.Option(None, "--source", help="Source ID scope"),
):
    """Search the library by caption, author, or ID."""
    s = load_settings()
    conn = connect(s.SX_DB_PATH)
    init_db(conn, enable_fts=s.SX_DB_ENABLE_FTS)
    source_id = _normalize_source_id(source, fallback=get_default_source_id(conn, _normalize_source_id(s.SX_DEFAULT_SOURCE_ID)))
    ensure_source(conn, source_id, label=source_id)
    conn.commit()
    
    results = search_fn(conn, query, limit=limit, offset=offset, source_id=source_id)
    
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


@app.command("refresh-notes", help="Re-render and cache markdown notes for a source using the latest template")
def refresh_notes(
    source: Optional[str] = typer.Option(None, "--source", help="Source ID to refresh (default: DB default source)"),
    limit: int = typer.Option(0, "--limit", help="Optional cap on number of notes to refresh (0 = all)"),
):
    s = load_settings()

    backend_mode = str(getattr(s, "SX_DB_BACKEND_MODE", "SQLITE") or "SQLITE").strip().upper()
    conn = None
    if backend_mode == "POSTGRES_PRIMARY":
        repo = PostgresRepository(s)
        sid = _normalize_source_id(source, fallback=_normalize_source_id(getattr(s, "SX_DEFAULT_SOURCE_ID", "default")))
        repo.init_schema(sid)
        conn = repo.connection_for_source(sid)
        source_id = sid
    else:
        conn = connect(s.SX_DB_PATH)
        init_db(conn, enable_fts=s.SX_DB_ENABLE_FTS)
        source_id = _normalize_source_id(source, fallback=get_default_source_id(conn, _normalize_source_id(s.SX_DEFAULT_SOURCE_ID)))
        ensure_source(conn, source_id, label=source_id)
        conn.commit()

    resolver = _resolver_for_source(s, source_id)
    now = datetime.utcnow().isoformat(timespec="seconds") + "Z"

    limit_clause = ""
    params: list[object] = [source_id]
    if int(limit or 0) > 0:
        limit_clause = " LIMIT ?"
        params.append(int(limit))

    rows = conn.execute(
        f"""
        SELECT
          v.*, 
          m.rating, m.status, m.statuses, m.tags, m.notes,
          m.product_link, m.author_links, m.platform_targets, m.workflow_log, m.post_url, m.published_time
        FROM videos v
        LEFT JOIN user_meta m ON m.video_id = v.id AND m.source_id = v.source_id
        WHERE v.source_id=?
        ORDER BY v.updated_at DESC
        {limit_clause}
        """,
        tuple(params),
    ).fetchall()

    refreshed = 0
    for row in rows:
        video = dict(row)
        md = render_note(video, resolver=resolver)
        conn.execute(
            """
            INSERT INTO video_notes(video_id, source_id, markdown, template_version, updated_at)
            VALUES(?, ?, ?, ?, ?)
            ON CONFLICT(source_id, video_id) DO UPDATE SET
              source_id=excluded.source_id,
              markdown=excluded.markdown,
              template_version=excluded.template_version,
              updated_at=excluded.updated_at
            """,
            (str(video.get("id") or ""), source_id, md, TEMPLATE_VERSION, now),
        )
        refreshed += 1

    conn.commit()
    console.print(
        Panel.fit(
            "\n".join(
                [
                    "[bold green]✓ Notes refreshed[/bold green]",
                    f"source_id: [cyan]{source_id}[/cyan]",
                    f"template_version: [cyan]{TEMPLATE_VERSION}[/cyan]",
                    f"rows refreshed: [cyan]{refreshed:,}[/cyan]",
                ]
            ),
            title="Refresh Notes",
        )
    )


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
    source: Optional[str] = typer.Option(None, "--source", help="Export only this source (default: all sources)"),
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

    source_id = _normalize_source_id(source, fallback="") if source else ""

    exported_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    header = {
        "type": "sx_userdata_export",
        "version": 2,
        "exported_at": exported_at,
        "db_path": str(s.SX_DB_PATH),
        "source_id": source_id or None,
        "includes": {"user_meta": bool(include_meta), "video_notes": bool(include_notes)},
    }

    meta_rows = []
    note_rows = []
    if include_meta:
        meta_rows = conn.execute(
                        """
                        SELECT
                            source_id,
                            video_id,
                            rating,
                            status,
                            statuses,
                            tags,
                            notes,
                            product_link,
                            author_links,
                            platform_targets,
                            workflow_log,
                            post_url,
                            published_time,
                            updated_at
                        FROM user_meta
                        WHERE (?='' OR source_id=?)
                        """
                        ,
                        (source_id, source_id),
        ).fetchall()
    if include_notes:
        note_rows = conn.execute(
            "SELECT source_id, video_id, markdown, template_version, updated_at FROM video_notes WHERE (?='' OR source_id=?)",
            (source_id, source_id),
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
    source: Optional[str] = typer.Option(None, "--source", help="Override source_id for all imported rows"),
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

    source_override = _normalize_source_id(source, fallback="") if source else ""
    default_source = _normalize_source_id(s.SX_DEFAULT_SOURCE_ID)

    meta_in = 0
    meta_upserted = 0
    meta_skipped_missing = 0
    meta_skipped_exists = 0

    notes_in = 0
    notes_upserted = 0
    notes_skipped_missing = 0
    notes_skipped_exists = 0
    def video_exists(source_id: str, video_id: str) -> bool:
        return bool(conn.execute("SELECT 1 FROM videos WHERE source_id=? AND id=?", (source_id, video_id)).fetchone())

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
                source_id = _normalize_source_id(
                    source_override or obj.get("source_id") or default_source,
                    fallback=default_source,
                )
                if not vid:
                    continue
                ensure_source(conn, source_id, label=source_id)
                if not video_exists(source_id, vid):
                    meta_skipped_missing += 1
                    if strict:
                        raise typer.Exit(code=2)
                    continue

                if overwrite:
                    conn.execute(
                        """
                                                INSERT INTO user_meta(
                                                    source_id,
                                                    video_id,
                                                    rating,
                                                    status,
                                                    statuses,
                                                    tags,
                                                    notes,
                                                    product_link,
                                                    author_links,
                                                    platform_targets,
                                                    workflow_log,
                                                    post_url,
                                                    published_time,
                                                    updated_at
                                                )
                                                                                                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                                ON CONFLICT(source_id, video_id) DO UPDATE SET
                                                    source_id=excluded.source_id,
                          rating=excluded.rating,
                          status=excluded.status,
                                                    statuses=excluded.statuses,
                          tags=excluded.tags,
                          notes=excluded.notes,
                                                    product_link=excluded.product_link,
                                                    author_links=excluded.author_links,
                                                    platform_targets=excluded.platform_targets,
                                                    workflow_log=excluded.workflow_log,
                                                    post_url=excluded.post_url,
                                                    published_time=excluded.published_time,
                          updated_at=excluded.updated_at
                        """,
                        (
                            source_id,
                            vid,
                            obj.get("rating"),
                            obj.get("status"),
                                                        obj.get("statuses"),
                            obj.get("tags"),
                            obj.get("notes"),
                                                        obj.get("product_link"),
                                                    obj.get("author_links"),
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
                                                    source_id,
                                                    video_id,
                                                    rating,
                                                    status,
                                                    statuses,
                                                    tags,
                                                    notes,
                                                    product_link,
                                                    author_links,
                                                    platform_targets,
                                                    workflow_log,
                                                    post_url,
                                                    published_time,
                                                    updated_at
                                                )
                                                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            source_id,
                            vid,
                            obj.get("rating"),
                            obj.get("status"),
                                                        obj.get("statuses"),
                            obj.get("tags"),
                            obj.get("notes"),
                                                        obj.get("product_link"),
                                                        obj.get("author_links"),
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
                source_id = _normalize_source_id(
                    source_override or obj.get("source_id") or default_source,
                    fallback=default_source,
                )
                if not vid or not md:
                    continue
                ensure_source(conn, source_id, label=source_id)
                if not video_exists(source_id, vid):
                    notes_skipped_missing += 1
                    if strict:
                        raise typer.Exit(code=2)
                    continue

                if overwrite:
                    conn.execute(
                        """
                                                INSERT INTO video_notes(source_id, video_id, markdown, template_version, updated_at)
                                                VALUES(?, ?, ?, ?, ?)
                                                ON CONFLICT(source_id, video_id) DO UPDATE SET
                                                    source_id=excluded.source_id,
                          markdown=excluded.markdown,
                          template_version=excluded.template_version,
                          updated_at=excluded.updated_at
                        """,
                        (
                                                        source_id,
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
                        INSERT OR IGNORE INTO video_notes(source_id, video_id, markdown, template_version, updated_at)
                        VALUES(?, ?, ?, ?, ?)
                        """,
                        (
                            source_id,
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


@app.command("doctor", help="Run local diagnostics (alias health, studio ports, recent logs)")
def doctor(
    json_out: bool = typer.Option(False, "--json", help="Output diagnostics as JSON"),
):
    """Check local CLI/runtime health and print actionable diagnostics."""
    shell = _doctor_shell_aliases()
    ports = {
        "5555": _doctor_port_listeners(5555),
        "5556": _doctor_port_listeners(5556),
    }
    logs = _doctor_latest_logs()

    payload = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "shell": shell,
        "ports": ports,
        "logs": logs,
    }

    if json_out:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    # Shell summary
    mode = shell.get("sxdb_mode") or "missing"
    where = shell.get("sxdb_defined_in") or "(not found)"
    managed = "yes" if shell.get("managed_block") else "no"
    console.print(
        Panel.fit(
            "\n".join(
                [
                    f"[bold]sxdb definition:[/bold] {mode}",
                    f"[bold]defined in:[/bold] {where}",
                    f"[bold]managed block:[/bold] {managed}",
                ]
            ),
            title="Doctor · Shell",
            border_style="cyan",
        )
    )

    # Syntax status table
    t = Table(title="Shell syntax checks", show_header=True, header_style="bold cyan")
    t.add_column("File")
    t.add_column("Status", width=10)
    t.add_column("Detail")
    for p, info in (shell.get("syntax") or {}).items():
        ok = bool((info or {}).get("ok"))
        detail = str((info or {}).get("error") or "")
        t.add_row(p, "✓ ok" if ok else "✗ fail", detail[:140])
    console.print(t)

    # Ports table
    pt = Table(title="Prisma Studio listeners", show_header=True, header_style="bold cyan")
    pt.add_column("Port", width=6)
    pt.add_column("Listening", width=10)
    pt.add_column("PIDs")
    for k in ("5555", "5556"):
        info = ports.get(k) or {}
        pids = ", ".join(str(x) for x in (info.get("pids") or []))
        pt.add_row(k, "yes" if info.get("listening") else "no", pids or "-")
    console.print(pt)

    # Logs summary
    latest = (logs.get("latest") or {})
    for key in ("prisma_pipeline", "prisma_studio", "api_tui"):
        info = latest.get(key)
        if not info:
            console.print(Panel.fit(f"No recent log found for {key}.", title=f"Doctor · {key}", border_style="yellow"))
            continue
        console.print(
            Panel.fit(
                "\n".join(
                    [
                        f"[bold]path:[/bold] {info.get('path')}",
                        f"[bold]mtime:[/bold] {info.get('mtime')}",
                        "",
                        "[bold]tail:[/bold]",
                        str(info.get("tail") or "").strip()[:900],
                    ]
                ),
                title=f"Doctor · {key}",
                border_style="green",
            )
        )


sources_app = typer.Typer(help="Manage source registry")
app.add_typer(sources_app, name="sources")


@sources_app.command("list", help="List registered sources")
def sources_list():
    s = load_settings()
    conn = connect(s.SX_DB_PATH)
    init_db(conn, enable_fts=s.SX_DB_ENABLE_FTS)
    ensure_source(conn, _normalize_source_id(s.SX_DEFAULT_SOURCE_ID), label=_normalize_source_id(s.SX_DEFAULT_SOURCE_ID))
    if not conn.execute("SELECT 1 FROM sources WHERE is_default=1 LIMIT 1").fetchone():
        set_default_source(conn, _normalize_source_id(s.SX_DEFAULT_SOURCE_ID))
    conn.commit()

    rows = list_sources(conn)
    t = Table(title="[bold]Sources[/bold]")
    t.add_column("Default", width=7)
    t.add_column("Enabled", width=7)
    t.add_column("ID", style="cyan")
    t.add_column("Label")
    t.add_column("Kind")
    t.add_column("Description")
    for r in rows:
        t.add_row(
            "✓" if int(r.get("is_default") or 0) else "",
            "✓" if int(r.get("enabled") or 0) else "",
            str(r.get("id") or ""),
            str(r.get("label") or ""),
            str(r.get("kind") or ""),
            str(r.get("description") or ""),
        )
    console.print(t)


@sources_app.command("add", help="Create or upsert a source")
def sources_add(
    source_id: str = typer.Argument(..., help="Source ID"),
    label: Optional[str] = typer.Option(None, "--label", help="Display label"),
    kind: Optional[str] = typer.Option(None, "--kind", help="Source kind"),
    description: Optional[str] = typer.Option(None, "--description", help="Description"),
    default: bool = typer.Option(False, "--default", help="Set as default source"),
):
    s = load_settings()
    if label is not None and not isinstance(label, str):
        label = None
    if kind is not None and not isinstance(kind, str):
        kind = None
    if description is not None and not isinstance(description, str):
        description = None
    if not isinstance(default, bool):
        default = False

    sid = _normalize_source_id(source_id)
    conn = connect(s.SX_DB_PATH)
    init_db(conn, enable_fts=s.SX_DB_ENABLE_FTS)
    ensure_source(conn, sid, label=(label or sid), kind=kind, description=description, enabled=True)
    if default:
        set_default_source(conn, sid)
    conn.commit()
    console.print(f"[green]✓[/green] Source upserted: [cyan]{sid}[/cyan]")


@sources_app.command("set-default", help="Set default source")
def sources_set_default(source_id: str = typer.Argument(..., help="Source ID")):
    s = load_settings()
    sid = _normalize_source_id(source_id)
    conn = connect(s.SX_DB_PATH)
    init_db(conn, enable_fts=s.SX_DB_ENABLE_FTS)
    ensure_source(conn, sid, label=sid, enabled=True)
    set_default_source(conn, sid)
    conn.commit()
    console.print(f"[green]✓[/green] Default source set to [cyan]{sid}[/cyan]")


@sources_app.command("remove", help="Remove a source (must not be default and must be empty)")
def sources_remove(source_id: str = typer.Argument(..., help="Source ID")):
    s = load_settings()
    sid = _normalize_source_id(source_id)
    conn = connect(s.SX_DB_PATH)
    init_db(conn, enable_fts=s.SX_DB_ENABLE_FTS)

    row = conn.execute("SELECT is_default FROM sources WHERE id=?", (sid,)).fetchone()
    if not row:
        console.print(f"[yellow]Source not found:[/yellow] {sid}")
        raise typer.Exit(code=1)
    if int(row[0] or 0) == 1:
        console.print("[red]Cannot remove default source[/red]")
        raise typer.Exit(code=1)

    n = conn.execute("SELECT COUNT(*) FROM videos WHERE source_id=?", (sid,)).fetchone()[0]
    if int(n or 0) > 0:
        console.print(f"[red]Cannot remove source with data[/red] (videos={n})")
        raise typer.Exit(code=1)

    conn.execute("DELETE FROM sources WHERE id=?", (sid,))
    conn.commit()
    console.print(f"[green]✓[/green] Source removed: [cyan]{sid}[/cyan]")


# ═══════════════════════════════════════════════════════════════════════════════
# INTERACTIVE MENU
# ═══════════════════════════════════════════════════════════════════════════════

def _interactive_menu() -> None:
    """Launch the chisel-inspired TUI with screen-based navigation."""
    from .tui.navigator import Navigator
    from .tui.router import Router
    from .tui.state import UIState
    # Import screens to register them
    from .tui import screens  # noqa: F401
    
    settings = load_settings()
    state = UIState()
    nav = Navigator()
    router = Router(
        console=console,
        settings=settings,
        state=state,
        nav=nav,
    )
    
    try:
        router.run()
    except KeyboardInterrupt:
        console.print("\n[dim]👋 Interrupted. Goodbye![/]")


def main():
    app()
