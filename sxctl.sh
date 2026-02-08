#!/usr/bin/env bash
set -euo pipefail

# sxctl.sh — friendly launcher for sx_obsidian (API + Obsidian plugin)
# Run from the sx_obsidian repo root.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

say() { printf "%s\n" "$*"; }
die() { say "$*" >&2; exit 1; }

help() {
  cat <<'EOF'
Usage:
  ./sxctl.sh menu
  ./sxctl.sh api serve
  ./sxctl.sh api init
  ./sxctl.sh api import
  ./sxctl.sh plugin update
  ./sxctl.sh plugin install
  ./sxctl.sh plugin build

Notes:
- The Obsidian plugin only needs to be (re)built + installed when the plugin code changes.
  If nothing changed, just keep it enabled in Obsidian.
- For plugin install you must set:
    export OBSIDIAN_VAULT_PATH=/path/to/your/vault
EOF
}

ensure_venv() {
  if [ ! -x "./.venv/bin/python" ]; then
    die "Missing .venv. Run: ./scripts/bootstrap.sh (or make bootstrap)"
  fi
}

guess_vault_path() {
  # Best-effort: use configured VAULT_default from sx_db settings (if venv exists).
  if [ -x "./.venv/bin/python" ]; then
    ./.venv/bin/python -c 'from sx_db.settings import load_settings; print(load_settings().VAULT_default or "")' 2>/dev/null || true
  else
    printf "%s" ""
  fi
}

ensure_vault_path() {
  if [ -n "${OBSIDIAN_VAULT_PATH:-}" ]; then
    return 0
  fi

  local guess
  guess="$(guess_vault_path)"

  say ""
  say "Plugin install needs OBSIDIAN_VAULT_PATH (your vault root)."
  if [ -n "$guess" ]; then
    say "Detected default from settings: $guess"
  fi

  local vault
  read -r -p "Enter OBSIDIAN_VAULT_PATH${guess:+ [$guess]}: " vault
  vault="${vault:-$guess}"

  if [ -z "$vault" ]; then
    die "Missing OBSIDIAN_VAULT_PATH. Aborting plugin install."
  fi

  # Only sets for this script process (and commands it spawns).
  export OBSIDIAN_VAULT_PATH="$vault"
}

cmd="${1:-menu}"
shift || true

case "$cmd" in
  -h|--help|help)
    help
    ;;

  menu)
    while true; do
      say "sx_obsidian launcher"
      say ""
      say "1) Start API server"
      say "2) API: init DB"
      say "3) API: import CSV"
      say "4) Plugin: build + install"
      say "5) Plugin: install (no build)"
      say ""
      read -r -p "Choose [1-5] (Enter/q to quit): " choice

      case "${choice:-}" in
        ""|q|Q)
          say "Cancelled."
          break
          ;;
        1)
          ensure_venv
          make api-serve
          ;;
        2)
          ensure_venv
          make api-init
          ;;
        3)
          ensure_venv
          make api-import
          ;;
        4)
          ensure_vault_path
          make plugin-build plugin-install
          ;;
        5)
          ensure_vault_path
          make plugin-install
          ;;
        *)
          say "Unknown choice: ${choice}."
          ;;
      esac

      say ""
      read -r -p "Press Enter to return to menu..." _
      say ""
    done
    ;;

  api)
    sub="${1:-serve}"
    shift || true
    ensure_venv
    case "$sub" in
      serve|run|server) make api-serve ;;
      init) make api-init ;;
      import) make api-import ;;
      status|stats)
        ./.venv/bin/python -m sx_db status
        ;;
      menu)
        ./.venv/bin/python -m sx_db --menu
        ;;
      *)
        die "Unknown api subcommand: $sub"
        ;;
    esac
    ;;

  plugin)
    sub="${1:-update}"
    shift || true
    case "$sub" in
      update) ensure_vault_path; make plugin-build plugin-install ;;
      build) make plugin-build ;;
      install) ensure_vault_path; make plugin-install ;;
      *) die "Unknown plugin subcommand: $sub" ;;
    esac
    ;;

  *)
    die "Unknown command: $cmd (run ./sxctl.sh --help)"
    ;;
esac
