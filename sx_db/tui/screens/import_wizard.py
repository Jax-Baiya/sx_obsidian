"""Import Data screen — import CSV data to PostgreSQL schemas (local/cloud)."""
from __future__ import annotations

import os
import subprocess
import sys

import questionary
from rich.panel import Panel
from rich.table import Table

from ..components import BRAND_STYLE, nav_choices, render_header
from ..db_targets import DatabaseServer, discover_servers, get_active_server, get_server_by_name
from ..profiles import SourceProfile, discover_profiles
from ..router import Router, register_screen


def _ensure_schema(router: Router, profile: SourceProfile, server: DatabaseServer) -> bool:
    """Ensure the PostgreSQL schema exists on the given server.

    Returns:
        True if schema exists or was created, False on error.
    """
    dsn = server.dsn()
    if not dsn:
        router.console.print(
            f"  [yellow]⚠ No DSN for {server.label}, cannot verify schema {profile.schema_name}[/]"
        )
        return False

    try:
        conn = None
        cur = None

        # Prefer psycopg (v3), fallback to psycopg2 for environments still on v2.
        try:
            import psycopg  # type: ignore[import-untyped]

            conn = psycopg.connect(dsn)
            conn.autocommit = True
            cur = conn.cursor()
        except ImportError:
            import psycopg2  # type: ignore[import-untyped]

            conn = psycopg2.connect(dsn)
            conn.autocommit = True
            cur = conn.cursor()

        cur.execute(
            "SELECT schema_name FROM information_schema.schemata WHERE schema_name = %s",
            (profile.schema_name,),
        )
        exists = cur.fetchone() is not None

        if not exists:
            cur.execute(f'CREATE SCHEMA "{profile.schema_name}"')
            router.console.print(
                f"  [green]✓[/] Created schema [cyan]{profile.schema_name}[/] on {server.short_label}"
            )
        else:
            router.console.print(
                f"  [dim]✓ Schema {profile.schema_name} exists on {server.short_label}[/]"
            )

        cur.close()
        conn.close()
        return True

    except ImportError:
        router.console.print(
            "  [yellow]⚠ psycopg/psycopg2 not installed — schema check skipped[/]"
        )
        return True  # Don't block import
    except Exception as e:
        router.console.print(f"  [red]✗ Schema error ({server.short_label}): {e}[/]")
        return False


def _find_csvs(profile: SourceProfile) -> list[str]:
    """Find CSV files in the profile's assets xlsx_files directory."""
    xlsx_dir = profile.xlsx_dir
    if not xlsx_dir.exists():
        return []
    return [f.name for f in xlsx_dir.glob("*.csv")]


def _build_import_cmd(source_id: str) -> list[str]:
    """Build import command using the current Python interpreter and stable CLI flags."""
    return [sys.executable, "-m", "sx_db", "import-csv", "--source", source_id]


def _best_error_snippet(result: subprocess.CompletedProcess[str], limit: int = 280) -> str:
    """Return the most useful stderr/stdout snippet for a failed subprocess."""
    text = (result.stderr or "").strip() or (result.stdout or "").strip()
    if not text:
        return "command failed with no error output"
    return text[:limit]


@register_screen("import_wizard")
def show_import_wizard(router: Router) -> str | None:
    """Multi-profile CSV import to PostgreSQL schemas with DB target selection."""
    render_header(router.console, router.settings)

    router.console.print(
        Panel(
            "Import CSV data from SchedulerX assets directories\n"
            "into PostgreSQL schemas on local or cloud databases.",
            title="Import Data",
            border_style="cyan",
        )
    )

    # ── Step 1: Discover & select profiles ─────────────────────────
    profiles = discover_profiles()
    active = [p for p in profiles if p.active]

    if not active:
        router.console.print(
            "[yellow]No active source profiles found.[/]\n"
            "Go to Manage Sources to configure profiles."
        )
        choice = questionary.select(
            "Actions:",
            choices=nav_choices(),
            style=BRAND_STYLE,
        ).ask()
        return choice

    # Use profiles from state if set by Manage Sources, else show picker
    preselected = router.state.data.get("active_profile_indices")

    selected_indices: list[int] | None
    if preselected:
        selected_indices = preselected
    else:
        selected_indices = questionary.checkbox(
            "Select source profiles to import:",
            choices=[
                questionary.Choice(
                    f"{p.label} ({p.profile_id})",
                    value=p.index,
                    checked=True,
                )
                for p in active
            ],
            style=BRAND_STYLE,
        ).ask()

    if not selected_indices:
        router.console.print("[dim]No profiles selected.[/]")
        return "back"

    selected = [p for p in active if p.index in selected_indices]

    # ── Step 2: Select database target ─────────────────────────────
    servers = discover_servers()
    active_server = get_active_server()
    active_label = active_server.label if active_server else "Unknown"

    db_target = questionary.select(
        f"Import to which database? (active: {active_label})",
        choices=[
            questionary.Choice(
                f"Active server only ({active_label})", value="active"
            ),
            questionary.Choice("Both servers (Local + Cloud)", value="both"),
            questionary.Choice("Other server (inactive)", value="other"),
            questionary.Separator(""),
            *nav_choices(include_separator=False),
        ],
        style=BRAND_STYLE,
    ).ask()

    if db_target in ("back", "home", None):
        return db_target

    # Resolve target server(s)
    target_servers: list[DatabaseServer] = []
    if db_target == "active":
        if active_server:
            target_servers = [active_server]
    elif db_target == "both":
        target_servers = servers
    elif db_target == "other":
        inactive = [s for s in servers if not s.is_active]
        if inactive:
            target_servers = inactive
        else:
            router.console.print("[yellow]No inactive server found.[/]")
            return "import_wizard"

    if not target_servers:
        router.console.print("[red]No database targets available.[/]")
        return "back"

    # ── Step 3: Verify CSVs ────────────────────────────────────────
    router.console.print("\n[bold]Verifying CSV files...[/]\n")

    import_plan: list[tuple[SourceProfile, list[str]]] = []
    for p in selected:
        csvs = _find_csvs(p)
        if csvs:
            router.console.print(
                f"  [green]✓[/] {p.label}: {len(csvs)} CSV file(s) found"
            )
            import_plan.append((p, csvs))
        else:
            router.console.print(
                f"  [yellow]⚠[/] {p.label}: No CSVs in {p.xlsx_dir}"
            )

    if not import_plan:
        router.console.print("\n[yellow]No CSV files found to import.[/]")
        choice = questionary.select(
            "Actions:",
            choices=nav_choices(),
            style=BRAND_STYLE,
        ).ask()
        return choice

    # ── Step 4: Ensure schemas on each target server ───────────────
    router.console.print("\n[bold]Checking PostgreSQL schemas...[/]\n")
    for srv in target_servers:
        router.console.print(f"  [cyan]{srv.label}:[/]")
        for p, _ in import_plan:
            _ensure_schema(router, p, srv)

    # ── Step 5: Confirm & import ───────────────────────────────────
    summary_table = Table(
        title="Import Plan", show_header=True, header_style="bold cyan"
    )
    summary_table.add_column("Profile")
    summary_table.add_column("Schema")
    summary_table.add_column("CSV Files")
    summary_table.add_column("Target DB(s)")

    target_names = ", ".join(s.short_label for s in target_servers)
    for p, csvs in import_plan:
        summary_table.add_row(p.label, p.schema_name, ", ".join(csvs), target_names)

    router.console.print(summary_table)

    proceed = questionary.confirm(
        "Proceed with import?",
        default=True,
        style=BRAND_STYLE,
    ).ask()

    if not proceed:
        return "back"

    # ── Run import for each server ─────────────────────────────────
    project_root = str(
        __import__("pathlib").Path(__file__).resolve().parent.parent.parent.parent
    )

    router.console.print()
    success_count = 0
    failure_count = 0
    for srv in target_servers:
        router.console.print(f"\n[bold cyan]Importing to {srv.label}...[/]\n")

        for p, csvs in import_plan:
            with router.console.status(
                f"[cyan]Importing {p.label} → {p.schema_name} ({srv.short_label})...[/]"
            ):
                try:
                    env = os.environ.copy()
                    env["DB_PROFILE"] = srv.alias_for(p.index)
                    env["SX_PIPELINE_DB_PROFILE"] = srv.alias_for(p.index)

                    cmd = _build_import_cmd(p.profile_id)
                    result = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        cwd=project_root,
                        env=env,
                        timeout=300,
                    )
                    if result.returncode == 0:
                        success_count += 1
                        router.console.print(
                            f"  [green]✓[/] {p.label} → {srv.short_label}"
                        )
                    else:
                        failure_count += 1
                        router.console.print(
                            f"  [red]✗[/] {p.label} → {srv.short_label}:\n"
                            f"    {_best_error_snippet(result)}"
                        )
                except subprocess.TimeoutExpired:
                    failure_count += 1
                    router.console.print(
                        f"  [red]✗[/] {p.label} → {srv.short_label}: timed out (5 min)"
                    )
                except Exception as e:
                    failure_count += 1
                    router.console.print(
                        f"  [red]✗[/] {p.label} → {srv.short_label}: {e}"
                    )

    # ── Step 6: Summary ────────────────────────────────────────────
    total_jobs = len(import_plan) * len(target_servers)
    border = "green" if failure_count == 0 else "yellow"
    headline = "✓ Import complete" if failure_count == 0 else "⚠ Import finished with issues"
    router.console.print(
        Panel(
            f"{headline}\n"
            f"  Targets: {target_names}\n"
            f"  Jobs: {total_jobs}  Success: {success_count}  Failed: {failure_count}",
            border_style=border,
        )
    )

    choice = questionary.select(
        "Next:",
        choices=[
            questionary.Choice("Import More", value="import_wizard"),
            *nav_choices(),
        ],
        style=BRAND_STYLE,
    ).ask()

    return choice
