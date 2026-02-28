"""Build & Deploy screen — build plugin and install to vaults."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import questionary
from prompt_toolkit import prompt
from prompt_toolkit.key_binding import KeyBindings
from rich.panel import Panel

from ..components import BRAND_STYLE, nav_choices, render_header
from ..profiles import discover_profiles, discover_vaults
from ..router import Router, register_screen

# Project root (relative to this file)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
PLUGIN_DIR = PROJECT_ROOT / "obsidian-plugin"
PLUGIN_ID = "sx-obsidian-db"
KNOWN_VAULTS_PATH = PROJECT_ROOT / "_logs" / "known_vault_paths.json"

# Files to copy into the plugin dir inside each vault
PLUGIN_ARTIFACTS = ["main.js", "manifest.json", "styles.css"]


def _load_known_vault_memory() -> list[str]:
    if not KNOWN_VAULTS_PATH.exists():
        return []
    try:
        raw = json.loads(KNOWN_VAULTS_PATH.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return []

    if isinstance(raw, dict):
        raw = raw.get("paths", [])
    if not isinstance(raw, list):
        return []

    out: list[str] = []
    seen: set[str] = set()
    for p in raw:
        s = str(p or "").strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def _save_known_vault_memory(paths: list[str]) -> None:
    KNOWN_VAULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    unique: list[str] = []
    seen: set[str] = set()
    for p in paths:
        s = str(p or "").strip()
        if not s or s in seen:
            continue
        seen.add(s)
        unique.append(s)
    KNOWN_VAULTS_PATH.write_text(
        json.dumps({"paths": unique}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _remember_vault_paths(paths: list[Path]) -> None:
    existing = _load_known_vault_memory()
    merged = list(existing)
    seen = set(existing)
    for p in paths:
        s = str(p)
        if s not in seen:
            merged.append(s)
            seen.add(s)
    _save_known_vault_memory(merged)


def _forget_vault_paths(paths: list[str]) -> int:
    existing = _load_known_vault_memory()
    drop = {str(p).strip() for p in paths if str(p).strip()}
    kept = [p for p in existing if p not in drop]
    if kept == existing:
        return 0
    _save_known_vault_memory(kept)
    return len(existing) - len(kept)


def _delete_memory_at_cursor(memory_paths: list[str], cursor: int) -> tuple[list[str], int, str | None]:
    """Delete the currently highlighted memory entry and return updated state.

    Returns:
        (updated_paths, next_cursor, removed_path)
    """
    if not memory_paths:
        return memory_paths, 0, None
    if cursor < 0 or cursor >= len(memory_paths):
        return memory_paths, max(0, min(cursor, len(memory_paths) - 1)), None

    removed = memory_paths[cursor]
    updated = memory_paths[:cursor] + memory_paths[cursor + 1 :]
    next_cursor = min(cursor, max(0, len(updated) - 1))
    return updated, next_cursor, removed


def _capture_memory_list_action() -> str:
    """Capture one keyboard action for remembered-vault manager.

    Keys:
      - Up/Down: move cursor
      - Delete / Backspace / d: delete highlighted entry
      - Enter: done
      - Esc/Ctrl-C: cancel
    """
    kb = KeyBindings()

    @kb.add("up")
    def _up(event):
        event.app.exit(result="up")

    @kb.add("down")
    def _down(event):
        event.app.exit(result="down")

    @kb.add("delete")
    def _delete(event):
        event.app.exit(result="delete")

    @kb.add("backspace")
    def _backspace(event):
        event.app.exit(result="delete")

    @kb.add("d")
    def _delete_fallback(event):
        event.app.exit(result="delete")

    @kb.add("enter")
    def _done(event):
        event.app.exit(result="done")

    @kb.add("escape")
    def _cancel(event):
        event.app.exit(result="cancel")

    @kb.add("c-c")
    def _cancel_ctrl_c(event):
        event.app.exit(result="cancel")

    result = prompt(
        "Action [↑/↓ move, Del/Backspace/d delete, Enter done, Esc cancel]: ",
        key_bindings=kb,
        default="",
    )
    if isinstance(result, str) and result.strip():
        lowered = result.strip().lower()
        if lowered in {"done", "enter"}:
            return "done"
        if lowered in {"cancel", "esc", "escape", "q", "quit"}:
            return "cancel"
        if lowered in {"d", "del", "delete", "backspace", "rm", "remove"}:
            return "delete"
        if lowered in {"up", "k"}:
            return "up"
        if lowered in {"down", "j"}:
            return "down"
    return "done"


def _render_remembered_vaults_panel(memory_paths: list[str], cursor: int) -> str:
    lines: list[str] = []
    for idx, p in enumerate(memory_paths):
        marker = "❯" if idx == cursor else " "
        has_obs = "✓ .obsidian" if (Path(p) / ".obsidian").is_dir() else "no .obsidian"
        lines.append(f"{marker} {p}  [{has_obs}]")

    if not lines:
        lines.append("(empty)")

    lines.extend(
        [
            "",
            "[dim]Use ↑/↓ to move, Delete (or Backspace/d) to remove selected path.[/]",
            "[dim]Press Enter when finished.[/]",
        ]
    )
    return "\n".join(lines)


def _default_checked_vault_paths(
    all_paths: dict[str, str],
    profiles,
    active_profile_indices: list[int] | None,
) -> set[str]:
    """Return vault paths that should be pre-checked in the picker.

    Priority:
      1) profile vaults selected in current UI state (`active_profile_indices`)
      2) all existing profile vault roots discovered from .env
      3) any known vault that already has `.obsidian`
    """
    checked: set[str] = set()

    indices = set(active_profile_indices or [])
    if indices:
        for p in profiles:
            root = str(p.vault_root)
            if p.index in indices and root in all_paths:
                checked.add(root)

    if not checked:
        for p in profiles:
            root = str(p.vault_root)
            if p.vault_root.is_dir() and root in all_paths:
                checked.add(root)

    if not checked:
        for path_str, label in all_paths.items():
            if "✓ .obsidian" in label:
                checked.add(path_str)

    return checked


def _build_plugin(router: Router) -> bool:
    """Run npm build in obsidian-plugin/ directory.

    Returns:
        True on success.
    """
    if not PLUGIN_DIR.exists():
        router.console.print(
            f"[red]✗ Plugin directory not found: {PLUGIN_DIR}[/]"
        )
        return False

    # Check node_modules
    if not (PLUGIN_DIR / "node_modules").exists():
        with router.console.status("[cyan]Installing plugin dependencies...[/]"):
            result = subprocess.run(
                ["npm", "install"],
                cwd=str(PLUGIN_DIR),
                capture_output=True,
                text=True,
            )
        if result.returncode != 0:
            router.console.print("[red]✗ npm install failed[/]")
            return False
        router.console.print("[green]✓ Dependencies installed[/]")

    with router.console.status("[cyan]Building plugin...[/]"):
        result = subprocess.run(
            ["npm", "run", "build"],
            cwd=str(PLUGIN_DIR),
            capture_output=True,
            text=True,
            timeout=120,
        )

    if result.returncode == 0:
        router.console.print("[green]✓ Plugin built successfully[/]")
        return True
    else:
        router.console.print("[red]✗ Build failed — check obsidian-plugin/ for errors[/]")
        return False


def _deploy_to_vault(router: Router, vault_path: Path) -> bool:
    """Deploy built plugin to a vault.

    If .obsidian/ doesn't exist, copies template from active vault.

    Returns:
        True on success.
    """
    obsidian_dir = vault_path / ".obsidian"

    # ── Handle missing .obsidian ───────────────────────────────────
    if not obsidian_dir.exists():
        template_obsidian: Path | None = None

        # Prefer profile-defined vaults first, then generic VAULT_* entries.
        candidate_roots: list[Path] = []
        seen: set[str] = set()
        for p in discover_profiles():
            root = p.vault_root
            key = str(root)
            if key not in seen:
                seen.add(key)
                candidate_roots.append(root)
        for v in discover_vaults():
            root = Path(v.path)
            key = str(root)
            if key not in seen:
                seen.add(key)
                candidate_roots.append(root)

        for root in candidate_roots:
            if root == vault_path:
                continue
            cand = root / ".obsidian"
            if cand.exists():
                template_obsidian = cand
                break

        if template_obsidian is not None:
            router.console.print(
                f"  [yellow]⚠ No .obsidian at {vault_path.name}[/]\n"
                f"  [dim]  Creating from template...[/]"
            )
            try:
                shutil.copytree(
                    str(template_obsidian),
                    str(obsidian_dir),
                    dirs_exist_ok=True,
                )
                router.console.print(
                    f"  [green]✓[/] Template .obsidian created"
                )
            except Exception:
                router.console.print(f"  [red]✗ Failed to create .obsidian[/]")
                return False
        else:
            router.console.print(
                f"  [red]✗ No .obsidian at {vault_path} and no template available from configured VAULT_* roots[/]"
            )
            return False

    # ── Copy plugin artifacts ──────────────────────────────────────
    plugin_dest = obsidian_dir / "plugins" / PLUGIN_ID
    plugin_dest.mkdir(parents=True, exist_ok=True)

    for artifact in PLUGIN_ARTIFACTS:
        src = PLUGIN_DIR / artifact
        if src.exists():
            shutil.copy2(str(src), str(plugin_dest / artifact))
        else:
            router.console.print(
                f"  [yellow]⚠ {artifact} not found in build output[/]"
            )

    router.console.print(
        f"  [green]✓[/] Deployed to {vault_path.name}"
    )
    return True


# ══════════════════════════════════════════════════════════════════════
# Interactive Directory Browser (inspired by DocuMorph CLI)
# ══════════════════════════════════════════════════════════════════════

def _browse_directory(start: Path | None = None) -> Path | None:
    """Interactive directory browser — navigate filesystem with arrow keys.

    Shows current path, parent, jump shortcuts, and subdirectories.
    Returns selected Path or None if cancelled.
    """
    current = start or Path.home()
    if not current.is_dir():
        current = Path.home()

    while True:
        # ── Build choices ──────────────────────────────────────────
        choices: list = [
            questionary.Choice(
                f"✅ [SELECT THIS]: {current}",
                value="__select__",
            ),
            questionary.Separator(""),
        ]

        # Parent directory
        if current.parent != current:
            choices.append(
                questionary.Choice("📂 .. (Parent Directory)", value="__parent__")
            )

        # Jump shortcuts
        choices.append(questionary.Separator("── Shortcuts ──"))
        shortcuts = [
            ("/mnt", "⏩ Jump to /mnt (drives)"),
            (str(Path.home()), "🏠 Jump to Home (~)"),
            ("/mnt/t", "⏩ Jump to /mnt/t"),
        ]
        for path_str, label in shortcuts:
            if Path(path_str).is_dir() and str(current) != path_str:
                choices.append(questionary.Choice(label, value=path_str))

        # Subdirectories
        choices.append(questionary.Separator("── Directories ──"))

        safe_dirs: list[Path] = []
        try:
            for entry in sorted(current.iterdir()):
                try:
                    if entry.is_dir() and not entry.name.startswith("."):
                        safe_dirs.append(entry)
                except (PermissionError, OSError):
                    continue
        except (PermissionError, OSError):
            choices.append(
                questionary.Choice("[Permission denied]", value="__parent__")
            )

        for d in safe_dirs[:30]:  # Cap at 30 to keep menu manageable
            choices.append(questionary.Choice(f"  📁 {d.name}/", value=str(d)))

        if len(safe_dirs) > 30:
            choices.append(
                questionary.Choice(
                    f"  ... and {len(safe_dirs) - 30} more",
                    value="__noop__",
                )
            )

        # Cancel
        choices.append(questionary.Separator(""))
        choices.append(questionary.Choice("❌ Cancel", value="__cancel__"))

        # ── Prompt ─────────────────────────────────────────────────
        answer = questionary.select(
            f"Browsing: {current}",
            choices=choices,
            style=BRAND_STYLE,
        ).ask()

        if answer is None or answer == "__cancel__":
            return None
        elif answer == "__select__":
            return current
        elif answer == "__parent__":
            current = current.parent
        elif answer == "__noop__":
            continue
        else:
            target = Path(answer)
            if target.is_dir():
                current = target


def _browse_directories_multi(router: Router, start: Path | None = None) -> list[Path] | str | None:
    selected: list[Path] = []
    cursor = start

    while True:
        found = _browse_directory(cursor)
        if found is None:
            if selected:
                return selected
            return None

        if found not in selected:
            selected.append(found)
        cursor = found

        action = questionary.select(
            "Directory selection:",
            choices=[
                questionary.Choice("Browse and add another directory", value="more"),
                questionary.Choice("Done (use selected directories)", value="done"),
                questionary.Choice("Clear selection", value="clear"),
                questionary.Separator(""),
                *nav_choices(include_separator=False),
            ],
            style=BRAND_STYLE,
        ).ask()

        if action in ("back", "home"):
            return str(action)
        if action == "clear":
            selected = []
            continue
        if action == "done":
            return selected
        if action is None:
            return selected or None


def _prompt_manual_directories(router: Router) -> list[Path] | str | None:
    selected: list[Path] = []

    while True:
        custom = questionary.text(
            "Enter vault path (leave empty to finish):",
            style=BRAND_STYLE,
        ).ask()

        if custom in (None, ""):
            return selected or None

        p = Path(str(custom).strip())
        if not p.is_dir():
            router.console.print(f"[yellow]⚠ Path does not exist: {p}[/]")
            create = questionary.confirm(
                "Create this directory?",
                default=False,
                style=BRAND_STYLE,
            ).ask()
            if create:
                p.mkdir(parents=True, exist_ok=True)
            else:
                continue

        if p not in selected:
            selected.append(p)

        action = questionary.select(
            "Directory selection:",
            choices=[
                questionary.Choice("Add another path", value="more"),
                questionary.Choice("Done (use selected directories)", value="done"),
                questionary.Choice("Clear selection", value="clear"),
                questionary.Separator(""),
                *nav_choices(include_separator=False),
            ],
            style=BRAND_STYLE,
        ).ask()

        if action in ("back", "home"):
            return str(action)
        if action == "clear":
            selected = []
            continue
        if action == "done":
            return selected
        if action is None:
            return selected or None


def _manage_known_vaults(router: Router, memory_paths: list[str]) -> None:
    if not memory_paths:
        router.console.print("[yellow]No remembered vault paths yet.[/]")
        return

    # Primary UX: in-list interactive manager with Delete key handling.
    try:
        working = list(memory_paths)
        cursor = 0
        total_removed = 0

        while True:
            router.console.print(
                Panel(
                    _render_remembered_vaults_panel(working, cursor),
                    title="Remembered vault paths",
                    border_style="cyan",
                )
            )

            if not working:
                router.console.print("[yellow]All remembered paths removed.[/]")
                break

            action = _capture_memory_list_action()
            if action == "up":
                cursor = (cursor - 1) % len(working)
                continue
            if action == "down":
                cursor = (cursor + 1) % len(working)
                continue
            if action == "cancel":
                break
            if action == "done":
                break

            if action == "delete":
                target = working[cursor]
                confirm = questionary.confirm(
                    f"Forget remembered path?\n{target}",
                    default=False,
                    style=BRAND_STYLE,
                ).ask()
                if not confirm:
                    continue

                updated, next_cursor, removed_path = _delete_memory_at_cursor(working, cursor)
                if removed_path:
                    removed_count = _forget_vault_paths([removed_path])
                    total_removed += removed_count
                working = updated
                cursor = next_cursor

        if total_removed:
            router.console.print(f"[green]✓ Removed {total_removed} remembered path(s).[/]")
        return
    except Exception:
        # Fallback UX for terminals that cannot provide the keybinding experience.
        choices = [
            questionary.Choice(
                f"{p}  [{'✓ .obsidian' if (Path(p) / '.obsidian').is_dir() else 'no .obsidian'}]",
                value=p,
            )
            for p in memory_paths
        ]
        selected = questionary.checkbox(
            "Select remembered paths to forget (space=toggle, enter=remove):",
            choices=choices,
            style=BRAND_STYLE,
        ).ask()

        if not selected:
            return
        removed = _forget_vault_paths([str(x) for x in selected])
        router.console.print(f"[green]✓ Removed {removed} remembered path(s).[/]")


def _collect_vault_paths(router: Router) -> list[Path] | str | None:
    """Prompt user for vault paths — select, browse, or type.

    Uses a select → action flow so the user always has a 'Back' option.
    Returns:
        - list[Path] when vaults are selected
        - "back"/"home" when user explicitly navigates
        - None when selection is cancelled/empty
    """
    while True:
        known_vaults = discover_vaults()
        remembered = _load_known_vault_memory()
        profiles = discover_profiles()

        # Merge known vault paths + vault roots from profiles + remembered memory
        all_paths: dict[str, str] = {}  # path → label

        for v in known_vaults:
            status = "✓ .obsidian" if v.has_obsidian else "no .obsidian"
            all_paths[v.path] = f"{v.path}  [{status}]"

        for p in remembered:
            if p in all_paths:
                continue
            has_obs = (Path(p) / ".obsidian").is_dir()
            status = "✓ .obsidian" if has_obs else "no .obsidian"
            all_paths[p] = f"{p}  [{status}] [remembered]"

        for p in profiles:
            root = str(p.vault_root)
            if root not in all_paths and p.vault_root.is_dir():
                has_obs = (p.vault_root / ".obsidian").is_dir()
                status = "✓ .obsidian" if has_obs else "no .obsidian"
                all_paths[root] = f"{root}  [{status}] ({p.label})"

        # ── First: ask what they want to do ────────────────────────────
        method_choices: list = []

        if all_paths:
            method_choices.append(
                questionary.Choice("Select from known vaults", value="pick")
            )
        method_choices.append(
            questionary.Choice("Browse directories", value="browse")
        )
        method_choices.append(
            questionary.Choice("Enter path manually", value="custom")
        )
        method_choices.append(
            questionary.Choice("Forget remembered vault(s)", value="forget")
        )
        method_choices.append(questionary.Separator(""))
        method_choices.extend(nav_choices(include_separator=False))

        method = questionary.select(
            "How to choose vault(s)?",
            choices=method_choices,
            style=BRAND_STYLE,
        ).ask()

        if method in ("back", "home", None):
            return method

        if method == "forget":
            _manage_known_vaults(router, remembered)
            continue

        if method == "browse":
            # Start browser from a sensible location
            start = Path("/mnt/t") if Path("/mnt/t").is_dir() else Path.home()
            result = _browse_directories_multi(router, start)
            if isinstance(result, str):
                return result
            if result:
                _remember_vault_paths(result)
                return result
            return None

        if method == "custom":
            result = _prompt_manual_directories(router)
            if isinstance(result, str):
                return result
            if result:
                _remember_vault_paths(result)
                return result
            return None

        # ── method == "pick": show checkbox of known vaults ─────────────
        active_profile_indices = router.state.data.get("active_profile_indices")
        default_checked = _default_checked_vault_paths(all_paths, profiles, active_profile_indices)

        vault_choices: list = []
        for path_str, label in all_paths.items():
            vault_choices.append(
                questionary.Choice(label, value=path_str, checked=(path_str in default_checked))
            )

        selected = questionary.checkbox(
            "Select target vault(s) (space to toggle, enter to confirm):",
            choices=vault_choices,
            style=BRAND_STYLE,
        ).ask()

        if not selected:
            return None

        chosen = [Path(s) for s in selected]
        _remember_vault_paths(chosen)
        return chosen


@register_screen("build_deploy")
def show_build_deploy(router: Router) -> str | None:
    """Build the Obsidian plugin and deploy to selected vaults."""
    render_header(router.console, router.settings)

    router.console.print(
        Panel(
            "Build the Obsidian plugin from source and\n"
            "install it to selected vault paths.",
            title="Build & Deploy",
            border_style="cyan",
        )
    )

    # ── Step 1: Build ──────────────────────────────────────────────
    if not _build_plugin(router):
        choice = questionary.select(
            "Actions:",
            choices=nav_choices(),
            style=BRAND_STYLE,
        ).ask()
        return choice

    # ── Step 2: Select vaults ──────────────────────────────────────
    vault_paths = _collect_vault_paths(router)
    if isinstance(vault_paths, str):
        return vault_paths
    if not vault_paths:
        router.console.print("[yellow]No vault selected; plugin was built but not installed.[/]")
        choice = questionary.select(
            "Actions:",
            choices=[
                questionary.Choice("Try selecting vault(s) again", value="build_deploy"),
                *nav_choices(),
            ],
            style=BRAND_STYLE,
        ).ask()
        return choice

    # ── Step 3: Deploy ─────────────────────────────────────────────
    router.console.print("\n[bold]Deploying plugin...[/]\n")

    success = 0
    for vp in vault_paths:
        if _deploy_to_vault(router, vp):
            success += 1

    router.console.print(
        Panel(
            f"✓ Deployed to {success}/{len(vault_paths)} vault(s)",
            border_style="green" if success == len(vault_paths) else "yellow",
        )
    )

    choice = questionary.select(
        "Next:",
        choices=nav_choices(),
        style=BRAND_STYLE,
    ).ask()
    return choice
