"""Database management screen — Prisma local/cloud schema operations."""
from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from urllib.request import urlopen

import questionary
from rich.panel import Panel
from rich.table import Table

from ..components import BRAND_STYLE, nav_choices, render_header
from ..db_targets import DatabaseServer, discover_servers
from ..profiles import SourceProfile, discover_profiles
from ..router import Router, register_screen
from .database_management_menu import (
    database_management_advanced_choices,
    database_management_choices,
    db_action_handlers,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
PRISMA_DIR = PROJECT_ROOT / "prisma"
PRISMA_SCHEMA_LOCAL = PRISMA_DIR / "schema.local.prisma"
PRISMA_SCHEMA_CLOUD = PRISMA_DIR / "schema.cloud.prisma"
LOG_DIR = PROJECT_ROOT / "_logs"


def _choose_profile(router: Router) -> SourceProfile | str | None:
    profiles = [p for p in discover_profiles() if p.active]
    if not profiles:
        router.console.print("[yellow]No active profiles found.[/]")
        return None

    preselected = router.state.data.get("active_profile_indices") or []
    selected_idx = preselected[0] if preselected else profiles[0].index

    choices = []
    for p in profiles:
        title = f"{p.label} ({p.profile_id}) · schema={p.schema_name}"
        choices.append(questionary.Choice(title, value=p.index, checked=(p.index == selected_idx)))

    choices.extend(nav_choices())

    chosen = questionary.select(
        "Select source profile (schema target):",
        choices=choices,
        style=BRAND_STYLE,
        use_shortcuts=True,
    ).ask()

    if chosen is None:
        return None
    if chosen in ("back", "home"):
        return str(chosen)

    match = next((p for p in profiles if p.index == int(chosen)), None)
    if match:
        router.state.remember(last_source=match.profile_id)
    return match


def _server_for_name(name: str) -> DatabaseServer | None:
    for s in discover_servers():
        if s.name == name:
            return s
    return None


def _prisma_env_for(profile: SourceProfile) -> dict[str, str]:
    env = os.environ.copy()

    local = _server_for_name("local")
    cloud = _server_for_name("cloud")

    if local:
        env["LOCAL_DATABASE_URL"] = local.prisma_dsn(schema=profile.schema_name)
    if cloud:
        env["CLOUD_DATABASE_URL"] = cloud.prisma_dsn(schema=profile.schema_name)

    return env


def _schema_for_target(target: str) -> Path:
    return PRISMA_SCHEMA_LOCAL if target == "local" else PRISMA_SCHEMA_CLOUD


def _target_label(target: str) -> str:
    return "Local" if target == "local" else "Cloud"


def _studio_port_for_target(target: str) -> int:
    return 5555 if target == "local" else 5556


def _log_path(prefix: str, target: str, schema_name: str) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_schema = re.sub(r"[^a-zA-Z0-9_.-]", "_", schema_name)
    return LOG_DIR / f"{prefix}_{target}_{safe_schema}_{stamp}.log"


def _tail_text(path: Path, max_lines: int = 40) -> str:
    if not path.exists():
        return ""
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        return "\n".join(lines[-max_lines:])
    except Exception:
        return ""


def _wait_for_studio(port: int, timeout_sec: float = 8.0) -> bool:
    deadline = datetime.now().timestamp() + timeout_sec
    while datetime.now().timestamp() < deadline:
        try:
            with urlopen(f"http://127.0.0.1:{port}", timeout=0.8) as resp:
                if int(getattr(resp, "status", 0) or 0) in (200, 301, 302, 307, 308):
                    return True
        except Exception:
            pass
    return False


def _run_prisma(router: Router, target: str, args: list[str], profile: SourceProfile) -> bool:
    if not PRISMA_DIR.exists():
        router.console.print(f"[red]Prisma folder not found:[/] {PRISMA_DIR}")
        return False

    schema_path = _schema_for_target(target)
    if not schema_path.exists():
        router.console.print(f"[red]Schema file not found:[/] {schema_path}")
        return False

    if shutil.which("npx") is None:
        router.console.print("[red]`npx` not found. Install Node.js/npm first.[/]")
        return False

    if args[:2] == ["db", "pull"] and schema_path.exists():
        try:
            backup_dir = PRISMA_DIR / "backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_name = f"{schema_path.name}.{target}.{profile.schema_name}.{stamp}.bak"
            shutil.copy2(schema_path, backup_dir / backup_name)
            router.console.print(
                f"[dim]Backed up {schema_path.name} to prisma/backups/{backup_name}[/]"
            )
        except Exception as e:
            router.console.print(f"[yellow]Warning: could not create schema backup: {e}[/]")

    cmd = ["npx", "--yes", "prisma", *args, "--schema", str(schema_path)]
    env = _prisma_env_for(profile)

    try:
        with router.console.status(
            f"[cyan]Running Prisma ({_target_label(target)} · {profile.schema_name})...[/]"
        ):
            result = subprocess.run(
                cmd,
                cwd=str(PROJECT_ROOT),
                env=env,
                capture_output=True,
                text=True,
                timeout=300,
            )
    except subprocess.TimeoutExpired:
        router.console.print("[red]Prisma command timed out after 5 minutes.[/]")
        return False
    except Exception as e:
        router.console.print(f"[red]Failed to run Prisma:[/] {e}")
        return False

    if result.returncode == 0:
        router.console.print(
            f"[green]✓ Prisma {_target_label(target)} command succeeded[/] "
            f"([dim]{' '.join(args)}[/])"
        )
        if result.stdout.strip():
            router.console.print(Panel(result.stdout.strip()[:2000], title="Prisma Output", border_style="green"))
        return True

    err = (result.stderr or "").strip() or (result.stdout or "").strip() or "Unknown error"
    router.console.print(
        Panel(
            err[:3000],
            title=f"Prisma {_target_label(target)} failed",
            border_style="red",
        )
    )
    return False


def _launch_prisma_studio(
    router: Router,
    target: str,
    profile: SourceProfile,
    log_path: Path | None = None,
    quiet: bool = False,
) -> bool:
    if not PRISMA_DIR.exists():
        router.console.print(f"[red]Prisma folder not found:[/] {PRISMA_DIR}")
        return False

    schema_path = _schema_for_target(target)
    if not schema_path.exists():
        router.console.print(f"[red]Schema file not found:[/] {schema_path}")
        return False

    if shutil.which("npx") is None:
        router.console.print("[red]`npx` not found. Install Node.js/npm first.[/]")
        return False

    env = _prisma_env_for(profile)
    port = _studio_port_for_target(target)

    # Ensure stale listeners don't block a fresh Studio launch.
    _stop_prisma_studio(router, target=target, quiet=True)

    cmd = [
        "npx",
        "--yes",
        "prisma",
        "studio",
        "--schema",
        str(schema_path),
        "--port",
        str(port),
        "--browser",
        "none",
    ]

    try:
        if log_path is None:
            log_path = _log_path("prisma_studio", target, profile.schema_name)
        with open(log_path, "a", encoding="utf-8") as lf:
            lf.write(
                f"\n--- prisma studio start {datetime.now().isoformat()} target={target} schema={profile.schema_name} port={port} ---\n"
            )
            lf.flush()
            proc = subprocess.Popen(
                cmd,
                cwd=str(PROJECT_ROOT),
                env=env,
                stdout=lf,
                stderr=lf,
                start_new_session=True,
            )
    except Exception as e:
        if not quiet:
            router.console.print(f"[red]Failed to launch Prisma Studio:[/] {e}")
        return False

    healthy = _wait_for_studio(port, timeout_sec=8.0)
    if not healthy:
        tail = _tail_text(log_path, max_lines=30)
        if not quiet:
            router.console.print(
                Panel(
                    "\n".join(
                        [
                            f"[red]Prisma Studio did not become reachable on port {port}[/red]",
                            f"Process PID: {proc.pid}",
                            f"Log: [cyan]{log_path}[/cyan]",
                            "",
                            "Recent log tail:",
                            tail or "(no logs yet)",
                        ]
                    ),
                    title="Prisma Studio",
                    border_style="red",
                )
            )
        return False

    if not quiet:
        router.console.print(
            Panel(
                "\n".join(
                    [
                        f"[bold green]✓ Prisma Studio launched ({_target_label(target)})[/bold green]",
                        f"Schema: [cyan]{profile.schema_name}[/cyan]",
                        f"URL: [cyan]http://127.0.0.1:{port}[/cyan]",
                        f"Log: [cyan]{log_path}[/cyan]",
                        "[dim]Tip: open this URL in your browser; the process runs in the background.[/]",
                    ]
                ),
                title="Prisma Studio",
                border_style="green",
            )
        )
    return True


def _pids_listening_on_port(port: int) -> set[int]:
    pids: set[int] = set()

    # Try lsof first (cleanest output for PIDs).
    try:
        result = subprocess.run(
            ["lsof", "-nP", "-iTCP:" + str(port), "-sTCP:LISTEN", "-t"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            for line in result.stdout.splitlines():
                line = line.strip()
                if line.isdigit():
                    pids.add(int(line))
    except Exception:
        pass

    # Fallback to `ss` parsing when lsof isn't available.
    if not pids:
        try:
            result = subprocess.run(
                ["ss", "-ltnp"],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
            if result.returncode == 0 and result.stdout:
                for line in result.stdout.splitlines():
                    if f":{port} " not in line and not line.rstrip().endswith(f":{port}"):
                        continue
                    for m in re.finditer(r"pid=(\d+)", line):
                        pids.add(int(m.group(1)))
        except Exception:
            pass

    return pids


def _stop_prisma_studio(router: Router, target: str | None = None, quiet: bool = False) -> bool:
    targets = [target] if target in ("local", "cloud") else ["local", "cloud"]
    ports = [_studio_port_for_target(t) for t in targets]

    killed: dict[int, list[int]] = {}
    for port in ports:
        pids = _pids_listening_on_port(port)
        if not pids:
            continue
        for pid in pids:
            try:
                alive = subprocess.run(
                    ["kill", "-0", str(pid)],
                    timeout=2,
                    check=False,
                    capture_output=True,
                    text=True,
                )
                if alive.returncode == 0:
                    subprocess.run(
                        ["kill", "-TERM", str(pid)],
                        timeout=2,
                        check=False,
                        capture_output=True,
                        text=True,
                    )
            except Exception:
                pass
        killed[port] = sorted(pids)

    if not killed:
        if not quiet:
            router.console.print(
                Panel(
                    "No Prisma Studio listeners found on managed ports (5555/5556).",
                    title="Stop Prisma Studio",
                    border_style="yellow",
                )
            )
        return True

    # Best-effort hard kill for any survivors.
    survivors: dict[int, list[int]] = {}
    for port, pids in killed.items():
        remaining = []
        for pid in pids:
            try:
                check = subprocess.run(
                    ["kill", "-0", str(pid)],
                    timeout=2,
                    check=False,
                    capture_output=True,
                    text=True,
                )
                if check.returncode == 0:
                    subprocess.run(
                        ["kill", "-KILL", str(pid)],
                        timeout=2,
                        check=False,
                        capture_output=True,
                        text=True,
                    )
                    check2 = subprocess.run(
                        ["kill", "-0", str(pid)],
                        timeout=2,
                        check=False,
                        capture_output=True,
                        text=True,
                    )
                    if check2.returncode == 0:
                        remaining.append(pid)
            except Exception:
                continue
        if remaining:
            survivors[port] = remaining

    lines = ["[bold green]✓ Stop signal sent to Prisma Studio process(es)[/bold green]"]
    for port, pids in killed.items():
        lines.append(f"Port {port}: terminated PID(s) {', '.join(str(p) for p in pids)}")
    if survivors:
        lines.append("[yellow]Some PID(s) may still be alive after SIGKILL:[/yellow]")
        for port, pids in survivors.items():
            lines.append(f"Port {port}: {', '.join(str(p) for p in pids)}")

    if not quiet:
        router.console.print(Panel("\n".join(lines), title="Stop Prisma Studio", border_style="green"))
    return not bool(survivors)


def _start_studio_pipeline_background(router: Router, target: str, profile: SourceProfile) -> bool:
    """Run validate -> db pull -> generate -> studio in one background process.

    Logs every step to `_logs/prisma_pipeline_*.log` for diagnostics.
    """
    schema_path = _schema_for_target(target)
    if not schema_path.exists():
        router.console.print(f"[red]Schema file not found:[/] {schema_path}")
        return False
    if shutil.which("npx") is None:
        router.console.print("[red]`npx` not found. Install Node.js/npm first.[/]")
        return False

    env = _prisma_env_for(profile)
    _stop_prisma_studio(router, target=target, quiet=True)

    # Keep schema backup parity with interactive db pull.
    try:
        backup_dir = PRISMA_DIR / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"{schema_path.name}.{target}.{profile.schema_name}.{stamp}.bak"
        shutil.copy2(schema_path, backup_dir / backup_name)
    except Exception:
        pass

    port = _studio_port_for_target(target)
    log_path = _log_path("prisma_pipeline", target, profile.schema_name)

    q_schema = shlex.quote(str(schema_path))
    script = " ; ".join(
        [
            "set -e",
            f"echo '=== Prisma pipeline start: target={target} schema={profile.schema_name} at $(date -Iseconds) ==='",
            f"npx --yes prisma validate --schema {q_schema}",
            f"npx --yes prisma db pull --schema {q_schema}",
            f"npx --yes prisma generate --schema {q_schema}",
            f"echo '=== Starting Prisma Studio on {port} ==='",
            f"exec npx --yes prisma studio --schema {q_schema} --port {port} --browser none",
        ]
    )

    try:
        with open(log_path, "a", encoding="utf-8") as lf:
            proc = subprocess.Popen(
                ["/bin/bash", "-lc", script],
                cwd=str(PROJECT_ROOT),
                env=env,
                stdout=lf,
                stderr=lf,
                start_new_session=True,
            )
    except Exception as e:
        router.console.print(f"[red]Failed to start Prisma pipeline:[/] {e}")
        return False

    router.console.print(
        Panel(
            "\n".join(
                [
                    f"[bold green]✓ Prisma Studio pipeline started ({_target_label(target)})[/bold green]",
                    f"Profile schema: [cyan]{profile.schema_name}[/cyan]",
                    f"Pipeline: validate → db pull → generate → studio",
                    f"Studio URL: [cyan]http://127.0.0.1:{port}[/cyan]",
                    f"PID: [cyan]{proc.pid}[/cyan]",
                    f"Log: [cyan]{log_path}[/cyan]",
                    "[dim]If Studio is not up yet, wait a few seconds and check the log tail.[/]",
                ]
            ),
            title="Run Prisma Studio",
            border_style="green",
        )
    )

    # Quick readiness hint so users don't hit browser errors immediately.
    if not _wait_for_studio(port, timeout_sec=20.0):
        tail = _tail_text(log_path, max_lines=25)
        router.console.print(
            Panel(
                "\n".join(
                    [
                        f"[yellow]Studio is still starting on port {port}.[/yellow]",
                        f"Log: [cyan]{log_path}[/cyan]",
                        "Recent log tail:",
                        tail or "(no logs yet)",
                    ]
                ),
                title="Prisma Studio status",
                border_style="yellow",
            )
        )
    return True


def _show_recent_prisma_logs(router: Router, target: str, profile: SourceProfile) -> None:
    pattern = f"prisma_*_{target}_{re.sub(r'[^a-zA-Z0-9_.-]', '_', profile.schema_name)}_*.log"
    logs = sorted(LOG_DIR.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    if not logs:
        router.console.print(
            Panel(
                "No recent Prisma logs found for this target/schema yet.",
                title="Prisma logs",
                border_style="yellow",
            )
        )
        return

    latest = logs[0]
    tail = _tail_text(latest, max_lines=50)
    router.console.print(
        Panel(
            "\n".join(
                [
                    f"Latest log: [cyan]{latest}[/cyan]",
                    "",
                    tail or "(log is empty)",
                ]
            ),
            title=f"Prisma logs · {_target_label(target)} · {profile.schema_name}",
            border_style="cyan",
        )
    )


def _render_db_info(router: Router, profile: SourceProfile) -> None:
    servers = discover_servers()
    local = next((s for s in servers if s.name == "local"), None)
    cloud = next((s for s in servers if s.name == "cloud"), None)

    info = Table.grid(padding=(0, 2))
    info.add_column(style="bold")
    info.add_column()
    info.add_row("Profile", f"{profile.label} ({profile.profile_id})")
    info.add_row("Schema", profile.schema_name)
    info.add_row("Prisma local schema", str(PRISMA_SCHEMA_LOCAL))
    info.add_row("Prisma cloud schema", str(PRISMA_SCHEMA_CLOUD))
    info.add_row("Local DB URL", local.prisma_dsn(schema=profile.schema_name) if local else "[dim]not configured[/]")
    info.add_row("Cloud DB URL", cloud.prisma_dsn(schema=profile.schema_name) if cloud else "[dim]not configured[/]")
    router.console.print(Panel(info, title="Database management", border_style="cyan"))


def _refresh_notes_cache(router: Router, profile: SourceProfile) -> bool:
    cmd = [
        sys.executable,
        "-m",
        "sx_db",
        "refresh-notes",
        "--source",
        profile.profile_id,
    ]
    try:
        with router.console.status(f"[cyan]Refreshing notes cache for {profile.profile_id}...[/]"):
            result = subprocess.run(
                cmd,
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
                timeout=300,
                check=False,
            )
    except Exception as e:
        router.console.print(f"[red]Failed to refresh notes cache:[/] {e}")
        return False

    if result.returncode != 0:
        err = (result.stderr or "").strip() or (result.stdout or "").strip() or "Unknown error"
        router.console.print(Panel(err[:3000], title="Refresh Notes failed", border_style="red"))
        return False

    out = (result.stdout or "").strip()
    if out:
        router.console.print(Panel(out[:3000], title="Refresh Notes", border_style="green"))
    else:
        router.console.print("[green]✓ Notes cache refreshed.[/]")
    return True


def _run_db_action(router: Router, profile: SourceProfile, action: str) -> str | None:
    handlers = db_action_handlers()
    target_args = handlers.get(str(action))
    if target_args is None:
        return "database_management"

    target, prisma_args = target_args
    if prisma_args == ["run_studio"]:
        _start_studio_pipeline_background(router, target, profile)
    elif prisma_args == ["logs"]:
        _show_recent_prisma_logs(router, target, profile)
    elif prisma_args == ["studio"]:
        _launch_prisma_studio(router, target, profile)
    elif prisma_args == ["stop_studio"]:
        _stop_prisma_studio(router, None if target == "all" else target)
    elif prisma_args == ["refresh_notes"]:
        _refresh_notes_cache(router, profile)
    else:
        _run_prisma(router, target, prisma_args, profile)
    return "database_management"


@register_screen("database_management")
def show_database_management(router: Router) -> str | None:
    render_header(router.console, router.settings)

    profile_choice = _choose_profile(router)
    if profile_choice in ("back", "home"):
        return str(profile_choice)
    profile = profile_choice
    if profile is None:
        return "back"

    _render_db_info(router, profile)

    choices = database_management_choices()

    action = questionary.select(
        "Choose a database action:",
        choices=choices,
        style=BRAND_STYLE,
        use_shortcuts=True,
    ).ask()

    if action in (None, "back", "home"):
        return action

    if action == "database_management_advanced":
        router.state.data["db_mgmt_profile_index"] = profile.index
        return "database_management_advanced"

    return _run_db_action(router, profile, str(action))


@register_screen("database_management_advanced")
def show_database_management_advanced(router: Router) -> str | None:
    render_header(router.console, router.settings)

    profile_choice = _choose_profile(router)
    if profile_choice in ("back", "home"):
        return str(profile_choice)
    profile = profile_choice
    if profile is None:
        return "back"

    _render_db_info(router, profile)

    choices = database_management_advanced_choices()

    action = questionary.select(
        "Advanced database action:",
        choices=choices,
        style=BRAND_STYLE,
        use_shortcuts=True,
    ).ask()

    if action in (None, "back", "home"):
        return action

    _run_db_action(router, profile, str(action))
    return "database_management_advanced"
