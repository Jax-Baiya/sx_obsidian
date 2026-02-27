"""API Server screen — launch/stop FastAPI with local/cloud DB selection."""
from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
import time
import json
from pathlib import Path
from urllib.request import urlopen

import questionary
from rich.panel import Panel
from rich.table import Table

from ..components import BRAND_STYLE, nav_choices, render_header
from ..db_targets import discover_servers, get_server_by_name
from ..router import Router, register_screen


# Track the server process globally within the TUI session
_server_process: subprocess.Popen | None = None
_server_db: str | None = None  # "local" or "cloud"
_server_log_handle = None

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
API_CONTROL_LOG = PROJECT_ROOT / "_logs" / "sx_db_api_tui.log"


def _build_api_server_cmd(host: str, port: str) -> list[str]:
    """Build API server command using the currently running interpreter."""
    return [sys.executable, "-m", "sx_db", "serve", "--host", host, "--port", str(port)]


def _api_healthy(host: str, port: str, timeout_sec: float = 0.5) -> bool:
    try:
        with urlopen(f"http://{host}:{port}/health", timeout=timeout_sec) as resp:
            return int(getattr(resp, "status", 0) or 0) == 200
    except Exception:
        return False


def _fetch_health_payload(host: str, port: str, timeout_sec: float = 1.0) -> dict | None:
    try:
        with urlopen(f"http://{host}:{port}/health", timeout=timeout_sec) as resp:
            status = int(getattr(resp, "status", 0) or 0)
            if status != 200:
                return None
            raw = resp.read()
            data = json.loads(raw.decode("utf-8", errors="replace"))
            if isinstance(data, dict):
                return data
    except Exception:
        return None
    return None


def _wait_for_api_health(host: str, port: str, timeout_sec: float = 5.0) -> bool:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if _api_healthy(host, port):
            return True
        time.sleep(0.2)
    return False


def _tail_text(path: Path, max_lines: int = 20) -> str:
    if not path.exists():
        return ""
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        return "\n".join(lines[-max_lines:])
    except Exception:
        return ""


def _close_server_log_handle() -> None:
    global _server_log_handle
    try:
        if _server_log_handle is not None:
            _server_log_handle.close()
    except Exception:
        pass
    finally:
        _server_log_handle = None


def _is_server_running() -> bool:
    """Check if the server process is still alive."""
    global _server_process
    if _server_process is None:
        return False
    poll = _server_process.poll()
    if poll is not None:
        _server_process = None
        _close_server_log_handle()
        return False
    return True


def _pids_listening_on_port(port: int) -> list[int]:
    pids: set[int] = set()

    try:
        result = subprocess.run(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
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

    return sorted(pids)


def _stop_external_server_on_port(router: Router, host: str, port: str) -> None:
    try:
        port_i = int(str(port))
    except Exception:
        router.console.print(f"[red]Invalid port: {port}[/]")
        return

    pids = _pids_listening_on_port(port_i)
    if not pids:
        router.console.print(f"[yellow]No listener found on {host}:{port_i}.[/]")
        return

    for pid in pids:
        try:
            subprocess.run(["kill", "-TERM", str(pid)], timeout=2, check=False, capture_output=True, text=True)
        except Exception:
            pass

    time.sleep(0.2)
    survivors = _pids_listening_on_port(port_i)
    for pid in survivors:
        try:
            subprocess.run(["kill", "-KILL", str(pid)], timeout=2, check=False, capture_output=True, text=True)
        except Exception:
            pass

    remaining = _pids_listening_on_port(port_i)
    if remaining:
        router.console.print(
            f"[yellow]Sent stop signals, but listener(s) still present on {host}:{port_i}: {', '.join(str(p) for p in remaining)}[/]"
        )
    else:
        router.console.print(f"[green]✓ Stopped listener(s) on {host}:{port_i}[/]")


def _view_health_payload(router: Router, host: str, port: str) -> None:
    payload = _fetch_health_payload(host, port)
    if payload is None:
        router.console.print(f"[red]Unable to fetch /health from http://{host}:{port}[/]")
        return

    backend = payload.get("backend") if isinstance(payload.get("backend"), dict) else {}
    info = Table.grid(padding=(0, 2))
    info.add_column(style="bold")
    info.add_column()
    info.add_row("ok", str(bool(payload.get("ok"))))
    info.add_row("source_id", str(payload.get("source_id") or ""))
    info.add_row("profile_index", str(payload.get("profile_index") or "—"))
    info.add_row("db_path", str(payload.get("db_path") or "—"))
    info.add_row("api_version", str(payload.get("api_version") or "—"))
    info.add_row("env_hint", str(payload.get("env_hint") or "—"))
    if isinstance(backend, dict):
        info.add_row("backend", str(backend.get("backend") or ""))
        info.add_row("schema", str(backend.get("schema") or ""))
        info.add_row("search_path", str(backend.get("search_path") or ""))

    router.console.print(Panel(info, title="/health summary", border_style="cyan"))

    detail_choice = questionary.select(
        "Health payload:",
        choices=[
            questionary.Choice("Show raw JSON", value="raw"),
            questionary.Choice("Back", value="back"),
        ],
        style=BRAND_STYLE,
    ).ask()

    if detail_choice == "raw":
        router.console.print(
            Panel(json.dumps(payload, indent=2, ensure_ascii=False), title="/health raw JSON", border_style="blue")
        )


@register_screen("api_control")
def show_api_control(router: Router) -> str | None:
    """API server management — start/stop FastAPI with DB selection."""
    render_header(router.console, router.settings)

    host = os.getenv("SX_API_HOST", "127.0.0.1")
    port = os.getenv("SX_API_PORT", "8123")
    managed_running = _is_server_running()
    external_running = (not managed_running) and _api_healthy(host, port)
    running = managed_running or external_running

    # Show server info
    servers = discover_servers()
    active_name = router.state.active_db_server

    if managed_running:
        status_text = "[green]Running (managed)[/]"
        db_text = f"[cyan]{_server_db or 'N/A'}[/]"
    elif external_running:
        status_text = "[yellow]Running (external)[/]"
        db_text = "[yellow]external/unknown[/]"
    else:
        status_text = "[dim]Stopped[/]"
        db_text = f"[dim]{active_name}[/]"

    # Info table
    info = Table.grid(padding=(0, 2))
    info.add_column(style="bold")
    info.add_column()
    info.add_row("Endpoint", f"http://{host}:{port}")
    info.add_row("Status", status_text)
    info.add_row("Database", db_text)

    # Show available servers.
    # When running, highlight the active runtime target.
    # When stopped, show configured default target from .env discovery.
    for s in servers:
        if running:
            is_runtime = (_server_db == s.name)
            icon = "[green]●[/]" if is_runtime else "[dim]○[/]"
            suffix = " [dim](active runtime)[/]" if is_runtime else ""
        else:
            icon = "[cyan]●[/]" if s.is_active else "[dim]○[/]"
            suffix = " [dim](configured default)[/]" if s.is_active else ""
        info.add_row(f"  {icon} {s.short_label}{suffix}", f"{s.host}:{s.port}/{s.db_name}")

    router.console.print(Panel(info, title="API Server", border_style="cyan"))

    # Build actions
    actions: list = []
    if managed_running:
        actions.append(questionary.Choice("Stop Server", value="stop"))
    elif external_running:
        actions.append(questionary.Choice("Use existing server", value="use_existing"))
        actions.append(questionary.Choice(f"Stop listener on {host}:{port}", value="stop_external"))
    else:
        actions.append(questionary.Choice("Start Server (Local DB)", value="start_local"))
        actions.append(questionary.Choice("Start Server (Cloud DB)", value="start_cloud"))

    if running:
        actions.append(questionary.Choice("View health payload", value="view_health"))

    actions.extend(nav_choices())

    choice = questionary.select(
        "Actions:",
        choices=actions,
        style=BRAND_STYLE,
    ).ask()

    if choice == "start_local":
        _start_server(router, host, port, "local")
        return "api_control"
    elif choice == "start_cloud":
        _start_server(router, host, port, "cloud")
        return "api_control"
    elif choice == "stop":
        _stop_server(router)
        return "api_control"
    elif choice == "use_existing":
        router.console.print(f"[green]✓ Using existing server at http://{host}:{port}[/]")
        return "api_control"
    elif choice == "stop_external":
        _stop_external_server_on_port(router, host, port)
        return "api_control"
    elif choice == "view_health":
        _view_health_payload(router, host, port)
        return "api_control"
    else:
        return choice


def _start_server(router: Router, host: str, port: str, db_name: str) -> None:
    """Start the FastAPI server as a background subprocess targeting a specific DB."""
    global _server_process, _server_db, _server_log_handle

    if _is_server_running():
        router.console.print("[yellow]⚠ API server is already running.[/]")
        return

    if _api_healthy(host, port):
        router.console.print(
            f"[yellow]⚠ An API server is already reachable at http://{host}:{port} (not managed by this TUI).[/]"
        )
        return

    server = get_server_by_name(db_name)
    if not server:
        router.console.print(f"\n[red]✗ Server '{db_name}' not found in .env[/]\n")
        return

    project_root = str(PROJECT_ROOT)

    # Build env with the correct DB profile
    env = os.environ.copy()
    env["DB_PROFILE"] = server.alias_for(1)
    env["SX_PIPELINE_DB_PROFILE"] = server.alias_for(1)
    env["SX_PIPELINE_DB_MODE"] = "LOCAL" if db_name == "local" else "SESSION"

    try:
        API_CONTROL_LOG.parent.mkdir(parents=True, exist_ok=True)
        _close_server_log_handle()
        _server_log_handle = open(API_CONTROL_LOG, "a", encoding="utf-8")
        _server_log_handle.write(
            f"\n--- start {time.strftime('%Y-%m-%d %H:%M:%S')} db={db_name} host={host} port={port} ---\n"
        )
        _server_log_handle.flush()

        _server_process = subprocess.Popen(
            _build_api_server_cmd(host, port),
            cwd=project_root,
            env=env,
            stdout=_server_log_handle,
            stderr=_server_log_handle,
        )

        if not _wait_for_api_health(host, port, timeout_sec=5.0):
            exit_code = _server_process.poll()
            if exit_code is not None:
                _server_process = None
                _server_db = None
                tail = _tail_text(API_CONTROL_LOG, max_lines=20)
                router.console.print(
                    f"\n[red]✗ Server failed to start (exit={exit_code})[/]\n"
                    f"  Log: {API_CONTROL_LOG}\n"
                    f"  Last lines:\n{tail}\n"
                )
                _close_server_log_handle()
                return

        _server_db = db_name
        router.state.active_db_server = db_name

        router.console.print(
            f"\n[green]✓ Server started (PID {_server_process.pid})[/]\n"
            f"  Listening on http://{host}:{port}\n"
            f"  Database:  {server.label}\n"
            f"  Log file:  {API_CONTROL_LOG}\n"
        )
    except Exception as e:
        router.console.print(f"\n[red]✗ Failed to start server: {e}[/]\n")
        _close_server_log_handle()


def _stop_server(router: Router) -> None:
    """Stop the background server process."""
    global _server_process, _server_db

    if _server_process is None:
        router.console.print("[dim]No server process to stop.[/]")
        return

    try:
        _server_process.send_signal(signal.SIGTERM)
        _server_process.wait(timeout=5)
        router.console.print("[green]✓ Server stopped[/]")
    except subprocess.TimeoutExpired:
        _server_process.kill()
        router.console.print("[yellow]⚠ Server force-killed[/]")
    except Exception as e:
        router.console.print(f"[red]✗ Error stopping server: {e}[/]")
    finally:
        _server_process = None
        _server_db = None
        _close_server_log_handle()
