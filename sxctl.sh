#!/usr/bin/env bash
set -euo pipefail

# sxctl.sh — friendly launcher for sx_obsidian (API + Obsidian plugin)
# Run from the sx_obsidian repo root.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"
LAST_VAULT_PATH_FILE="$ROOT_DIR/_logs/last_successful_vault_path"

say() { printf "%s\n" "$*"; }
die() { say "$*" >&2; exit 1; }

help() {
  cat <<'EOF'
Usage:
  ./sxctl.sh menu
  ./sxctl.sh api serve
  ./sxctl.sh api serve-bg
  ./sxctl.sh api stop
  ./sxctl.sh api server-status
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

read_last_vault_path() {
  if [ -f "$LAST_VAULT_PATH_FILE" ]; then
    head -n 1 "$LAST_VAULT_PATH_FILE" 2>/dev/null || true
  else
    printf "%s" ""
  fi
}

remember_last_vault_path() {
  local p="$1"
  [ -n "$p" ] || return 0
  mkdir -p "$(dirname "$LAST_VAULT_PATH_FILE")" 2>/dev/null || true
  printf "%s\n" "$p" > "$LAST_VAULT_PATH_FILE" 2>/dev/null || true
}

ensure_vault_path() {
  is_valid_vault_path() {
    local p="$1"
    [ -n "$p" ] || return 1
    [ -d "$p" ] || return 1
    return 0
  }

  if [ -n "${OBSIDIAN_VAULT_PATH:-}" ]; then
    if is_valid_vault_path "$OBSIDIAN_VAULT_PATH"; then
      remember_last_vault_path "$OBSIDIAN_VAULT_PATH"
      return 0
    fi
    say ""
    say "OBSIDIAN_VAULT_PATH is set but invalid: $OBSIDIAN_VAULT_PATH"
    say "Please provide an existing vault root directory."
    unset OBSIDIAN_VAULT_PATH
  fi

  local remembered settings_guess guess
  remembered="$(read_last_vault_path)"
  settings_guess="$(guess_vault_path)"
  guess=""

  if [ -n "$remembered" ] && is_valid_vault_path "$remembered"; then
    guess="$remembered"
  elif [ -n "$settings_guess" ] && is_valid_vault_path "$settings_guess"; then
    guess="$settings_guess"
  fi

  say ""
  say "Plugin install needs OBSIDIAN_VAULT_PATH (your vault root)."
  if [ -n "$guess" ]; then
    if [ -n "$remembered" ] && [ "$guess" = "$remembered" ]; then
      say "Using remembered successful path: $guess"
    else
      say "Detected default from settings: $guess"
    fi
  else
    say "No valid default vault path detected from settings."
  fi

  while true; do
    local vault
    read -r -p "Enter OBSIDIAN_VAULT_PATH${guess:+ [$guess]}: " vault
    vault="${vault:-$guess}"

    if [ -z "$vault" ]; then
      die "Missing OBSIDIAN_VAULT_PATH. Aborting plugin install."
    fi

    if is_valid_vault_path "$vault"; then
      export OBSIDIAN_VAULT_PATH="$vault"
      remember_last_vault_path "$vault"
      return 0
    fi

    say "Path does not exist or is not accessible on this system: $vault"
    say "Tip: on Linux/WSL, use the mounted path (example: /mnt/c/... or a native Linux path)."
    guess=""
  done
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
      serve-bg|bg|background)
        mkdir -p "./_logs"
        pidfile="./_logs/sx_db_api.pid"
        out="./_logs/sx_db_api.nohup.out"

        if [ -f "$pidfile" ]; then
          pid="$(cat "$pidfile" 2>/dev/null || true)"
          if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            say "API already running (pid=$pid)."
            say "Logs: ./_logs/sx_db_api.log (rotating)"
            exit 0
          fi
          rm -f "$pidfile" || true
        fi

        nohup ./.venv/bin/python -m sx_db run >"$out" 2>&1 &
        pid="$!"
        echo "$pid" >"$pidfile"
        say "API started in background (pid=$pid)."
        say "Logs: ./_logs/sx_db_api.log (rotating)"
        say "(stdout/stderr fallback: $out)"
        ;;
      stop)
        pidfile="./_logs/sx_db_api.pid"
        if [ ! -f "$pidfile" ]; then
          say "No pidfile found ($pidfile). Is the API running?"
          exit 0
        fi
        pid="$(cat "$pidfile" 2>/dev/null || true)"
        if [ -z "$pid" ]; then
          rm -f "$pidfile" || true
          say "No pid in pidfile. Removed $pidfile."
          exit 0
        fi
        if kill -0 "$pid" 2>/dev/null; then
          say "Stopping API (pid=$pid)…"
          kill "$pid" 2>/dev/null || true
        fi
        rm -f "$pidfile" || true
        say "Stopped (or already not running)."
        ;;
      server-status)
        pidfile="./_logs/sx_db_api.pid"
        if [ ! -f "$pidfile" ]; then
          say "API not running (no pidfile)."
          exit 0
        fi
        pid="$(cat "$pidfile" 2>/dev/null || true)"
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
          say "API running (pid=$pid)."
          say "Logs: ./_logs/sx_db_api.log (rotating)"
        else
          say "API not running (stale pidfile)."
        fi
        ;;
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
