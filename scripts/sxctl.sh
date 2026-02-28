#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# shellcheck disable=SC1091
source "$ROOT_DIR/scripts/profile_adapter.sh"

SXCTL_DIR="$ROOT_DIR/.sxctl"
SXCTL_CONTEXT_FILE="$SXCTL_DIR/context.env"
SXCTL_CONTEXT_JSON="$SXCTL_DIR/context.json"
SXCTL_HISTORY_FILE="$SXCTL_DIR/history.json"
LAST_VAULT_PATH_FILE="$ROOT_DIR/_logs/last_successful_vault_path"

SXCTL_DEBUG="${SXCTL_DEBUG:-0}"
SXCTL_VERBOSE="${SXCTL_VERBOSE:-0}"
SXCTL_NONINTERACTIVE="${SXCTL_NONINTERACTIVE:-0}"
DEFAULT_DB_BACKEND="${SXCTL_DEFAULT_DB_BACKEND:-postgres_primary}"

# Backward-compatible noninteractive aliases
if [ -z "${SXCTL_PROFILE_INDEX:-}" ] && [ -n "${PROFILE_INDEX:-}" ]; then
  SXCTL_PROFILE_INDEX="$PROFILE_INDEX"
fi
if [ -z "${SXCTL_VAULT_ROOT:-}" ] && [ -n "${VAULT_ROOT:-}" ]; then
  SXCTL_VAULT_ROOT="$VAULT_ROOT"
fi
if [ -z "${SXCTL_DB_BACKEND:-}" ] && [ -n "${DB_BACKEND:-}" ]; then
  SXCTL_DB_BACKEND="$DB_BACKEND"
fi
if [ -z "${SXCTL_SCHEMA_NAME:-}" ] && [ -n "${SCHEMA_NAME:-}" ]; then
  SXCTL_SCHEMA_NAME="$SCHEMA_NAME"
fi

# ── ANSI colors ──────────────────────────────────────────────
if [ -t 1 ] || [ -t 2 ]; then
  C_RST='\033[0m'
  C_BOLD='\033[1m'
  C_ITAL='\033[3m'
  C_DIM='\033[2m'
  C_CYAN='\033[36m'
  C_MAG='\033[35m'
  C_GRN='\033[32m'
  C_YEL='\033[33m'
  C_RED='\033[31m'
  C_WHT='\033[97m'
else
  C_RST='' C_BOLD='' C_ITAL='' C_DIM='' C_CYAN='' C_MAG=''
  C_GRN='' C_YEL='' C_RED='' C_WHT=''
fi

UI_HR='='
UI_BOX_V='|'

say()   { printf "%b\n" "$*"; }
warn()  { printf "%b\n" "${C_YEL}! $*${C_RST}" >&2; }
err()   { printf "%b\n" "${C_RED}✗ $*${C_RST}" >&2; }
ok()    { printf "%b\n" "${C_GRN}✓ $*${C_RST}"; }
debug() {
  if [ "$SXCTL_DEBUG" = "1" ] || [ "$SXCTL_VERBOSE" = "1" ]; then
    printf "%b\n" "${C_DIM}[debug] $*${C_RST}" >&2
  fi
}

die() {
  err "$*"
  exit 1
}

# stderr helpers (for use inside command substitution)
say_err() { printf "%b\n" "$*" >&2; }

# ── Box-drawing helpers ──────────────────────────────────────
_hr() {
  local ch="${1:-$UI_HR}" len="${2:-48}"
  printf '%*s' "$len" '' | tr ' ' "$ch"
}

banner() {
  local title="$1" subtitle="${2:-}"
  local w=62
  local bar; bar="$(_hr "$UI_HR" $w)"
  say_err ""
  say_err "${C_CYAN}${bar}${C_RST}"
  local pad=$(( (w - ${#title}) / 2 ))
  printf '%b' "${C_CYAN}${UI_BOX_V}${C_RST} " >&2
  printf '%*s' "$pad" '' >&2
  printf '%b' "${C_BOLD}${C_MAG}${title}${C_RST}" >&2
  printf '%*s' $(( w - pad - ${#title} - 1 )) '' >&2
  printf '%b\n' "${C_CYAN}${UI_BOX_V}${C_RST}" >&2
  if [ -n "$subtitle" ]; then
    local spad=$(( (w - ${#subtitle}) / 2 ))
    printf '%b' "${C_CYAN}${UI_BOX_V}${C_RST} " >&2
    printf '%*s' "$spad" '' >&2
    printf '%b' "${C_DIM}${C_WHT}${subtitle}${C_RST}" >&2
    printf '%*s' $(( w - spad - ${#subtitle} - 1 )) '' >&2
    printf '%b\n' "${C_CYAN}${UI_BOX_V}${C_RST}" >&2
  fi
  say_err "${C_CYAN}${bar}${C_RST}"
}

is_noninteractive() {
  if [ "$SXCTL_NONINTERACTIVE" = "1" ]; then
    return 0
  fi
  if [ ! -t 0 ]; then
    return 0
  fi
  return 1
}

ensure_dirs() {
  mkdir -p "$SXCTL_DIR" "$ROOT_DIR/_logs"
}

history_prune_file() {
  ensure_dirs
  if ! has_cmd python3; then
    return 0
  fi
  python3 - "$SXCTL_HISTORY_FILE" <<'PY' 2>/dev/null || true
import json, os, re, sys

f = sys.argv[1]
arr = []
if os.path.exists(f):
    try:
        data = json.load(open(f, "r", encoding="utf-8"))
        if isinstance(data, list):
            arr = [str(x).strip() for x in data if isinstance(x, str)]
    except Exception:
        arr = []

tmp_re = re.compile(r"^/(tmp|var/tmp)/tmp(\.|$)")

def normalize(p: str) -> str:
    p = p.strip()
    if p.endswith("/.obsidian"):
        p = os.path.dirname(p)
    return p

seen = set()
out = []
for raw in arr:
    p = normalize(raw)
    if not p:
        continue
    if tmp_re.match(p):
        continue
    if not os.path.isdir(p):
        continue
    if not os.path.isdir(os.path.join(p, ".obsidian")):
        continue
    if p in seen:
        continue
    seen.add(p)
    out.append(p)

out = out[:20]
with open(f, "w", encoding="utf-8") as fh:
    json.dump(out, fh, ensure_ascii=False, indent=2)
PY
}

history_add_path() {
  local p="$1"
  [ -n "$p" ] || return 0
  if [[ "$p" =~ ^/(tmp|var/tmp)/tmp(\.|$) ]]; then
    return 0
  fi
  if [ "$(basename "$p")" = ".obsidian" ]; then
    p="$(dirname "$p")"
  fi
  if [ ! -d "$p/.obsidian" ]; then
    return 0
  fi

  ensure_dirs
  history_prune_file
  if has_cmd python3; then
    python3 - "$SXCTL_HISTORY_FILE" "$p" <<'PY' 2>/dev/null || true
import json, os, sys
f, p = sys.argv[1], sys.argv[2]
arr = []
if os.path.exists(f):
    try:
        d = json.load(open(f, 'r', encoding='utf-8'))
        if isinstance(d, list):
            arr = [str(x) for x in d if isinstance(x, str)]
    except Exception:
        arr = []
arr = [p] + [x for x in arr if x != p]
arr = arr[:20]
with open(f, 'w', encoding='utf-8') as fh:
    json.dump(arr, fh, ensure_ascii=False, indent=2)
PY
  fi
}

history_list_paths() {
  history_prune_file
  if [ ! -f "$SXCTL_HISTORY_FILE" ]; then
    return 0
  fi
  if has_cmd python3; then
    python3 - "$SXCTL_HISTORY_FILE" <<'PY' 2>/dev/null || true
import json, sys
f = sys.argv[1]
try:
    arr = json.load(open(f, 'r', encoding='utf-8'))
except Exception:
    arr = []
if isinstance(arr, list):
    for x in arr:
        if isinstance(x, str) and x.strip():
            print(x)
PY
  fi
}

context_save_json() {
  ensure_dirs
  if ! has_cmd python3; then
    return 0
  fi
  python3 - "$SXCTL_CONTEXT_JSON" \
    "${SXCTL_PROFILE_INDEX:-}" \
    "${SXCTL_SOURCE_ID:-}" \
    "${SXCTL_SOURCE_PATH:-}" \
    "${SXCTL_DB_BACKEND:-}" \
    "${SXCTL_DB_PATH:-}" \
    "${SXCTL_PIPELINE_DB_PROFILE:-}" \
    "${SXCTL_PIPELINE_DB_URL:-}" \
    "${SXCTL_PIPELINE_DB_MODE:-}" \
    "${SXCTL_VAULT_ROOT:-}" \
    "${SXCTL_SCHEMA_NAME:-}" \
    "${SXCTL_SEARCH_PATH:-}" \
    "${SX_SCHEDULERX_ENV:-}" <<'PY' 2>/dev/null || true
import json, sys
f = sys.argv[1]
vals = sys.argv[2:]
keys = [
    "SXCTL_PROFILE_INDEX", "SXCTL_SOURCE_ID", "SXCTL_SOURCE_PATH", "SXCTL_DB_BACKEND",
    "SXCTL_DB_PATH", "SXCTL_PIPELINE_DB_PROFILE", "SXCTL_PIPELINE_DB_URL", "SXCTL_PIPELINE_DB_MODE",
    "SXCTL_VAULT_ROOT", "SXCTL_SCHEMA_NAME", "SXCTL_SEARCH_PATH", "SX_SCHEDULERX_ENV",
]
out = {k: vals[i] if i < len(vals) else "" for i, k in enumerate(keys)}
with open(f, "w", encoding="utf-8") as fh:
    json.dump(out, fh, ensure_ascii=False, indent=2)
PY
}

parse_search_path_from_url() {
  local u="${1:-}"
  [ -n "$u" ] || return 0
  printf '%s' "$u" \
    | sed -n 's/.*search_path%3D\([^&]*\).*/\1/p' \
    | sed 's/%2[Cc]/,/g; s/%20/ /g; s/%2[Dd]/-/g; s/%5[Ff]/_/g'
}

remember_last_vault_path() {
  local p="$1"
  [ -n "$p" ] || return 0
  ensure_dirs
  printf "%s\n" "$p" >"$LAST_VAULT_PATH_FILE" 2>/dev/null || true
}

read_last_vault_path() {
  if [ -f "$LAST_VAULT_PATH_FILE" ]; then
    head -n 1 "$LAST_VAULT_PATH_FILE" 2>/dev/null || true
  else
    printf ""
  fi
}

has_cmd() {
  command -v "$1" >/dev/null 2>&1
}

vault_validation_error() {
  local p="${1:-}"
  if [ -z "$p" ]; then
    printf "vault path is empty"
    return 0
  fi
  if [ ! -e "$p" ]; then
    printf "path does not exist"
    return 0
  fi
  if [ ! -d "$p" ]; then
    printf "path is not a directory"
    return 0
  fi
  if [ ! -d "$p/.obsidian" ]; then
    printf "missing .obsidian directory (expected vault root)"
    return 0
  fi
  printf ""
}

validate_vault_root() {
  local p="${1:-}"
  local reason
  reason="$(vault_validation_error "$p")"
  [ -z "$reason" ]
}

pick_with_arrows() {
  local prompt="$1"
  shift
  local options=("$@")

  [ "${#options[@]}" -gt 0 ] || return 1

  local selected=0 key max
  local printed_lines=0
  max=$(( ${#options[@]} - 1 ))

  tput civis >/dev/null 2>&1 || true
  trap 'tput cnorm >/dev/null 2>&1 || true' RETURN

  while true; do
    if [ "$printed_lines" -gt 0 ]; then
      printf '\033[%sA' "$printed_lines" >&2
    fi
    printed_lines=$(( ${#options[@]} + 2 ))

    printf "\r\033[2K%b\n" "${C_BOLD}${C_CYAN}  ${prompt}${C_RST}" >&2
    printf "\r\033[2K%b\n" "${C_DIM}  $(_hr '-' 56)${C_RST}" >&2

    local i
    for i in "${!options[@]}"; do
      if [ "$i" -eq "$selected" ]; then
        printf "\r\033[2K  %b>> %s%b\n" "${C_GRN}${C_BOLD}" "${options[$i]}" "${C_RST}" >&2
      else
        printf "\r\033[2K    %s\n" "${options[$i]}" >&2
      fi
    done

    IFS= read -rsn1 key </dev/tty || return 1
    if [[ "$key" == $'\x1b' ]]; then
      read -rsn2 key </dev/tty || true
      case "$key" in
        "[A") selected=$(( selected > 0 ? selected - 1 : max )) ;;
        "[B") selected=$(( selected < max ? selected + 1 : 0 )) ;;
      esac
      continue
    fi

    case "$key" in
      ''|$'\n'|$'\r')
        printf "%s" "${options[$selected]}"
        return 0
        ;;
      q|Q)
        return 1
        ;;
      [0-9])
        if [ "$key" -ge 1 ] && [ "$key" -le "${#options[@]}" ]; then
          printf "%s" "${options[$((key - 1))]}"
          return 0
        fi
        ;;
    esac

  done
}

pick_with_ui() {
  local prompt="$1"
  shift
  local options=("$@")

  if [ "${#options[@]}" -eq 0 ]; then
    return 1
  fi

  if ! is_noninteractive; then
    pick_with_arrows "$prompt" "${options[@]}"
    return $?
  fi

  # ── Numeric fallback: ALL display goes to stderr, only result to stdout ──
  local i
  say_err ""
  say_err "${C_BOLD}${C_CYAN}  $prompt${C_RST}"
  say_err "${C_DIM}  $(_hr "$UI_HR" 44)${C_RST}"
  for i in "${!options[@]}"; do
    say_err "  ${C_WHT}[$((i + 1))]${C_RST} ${options[$i]}"
  done
  say_err ""
  local ans
  read -r -p "  Choose [1-${#options[@]}]: " ans </dev/tty
  if [[ ! "$ans" =~ ^[0-9]+$ ]]; then
    return 1
  fi
  if [ "$ans" -lt 1 ] || [ "$ans" -gt "${#options[@]}" ]; then
    return 1
  fi
  printf "%s" "${options[$((ans - 1))]}"
}

extract_profile_idx() {
  local row="$1"
  # Extract the numeric index from [N] at the start of the string.
  # Use grep to isolate the line containing [N], then sed to extract N.
  local idx
  idx="$(printf '%s' "$row" | grep -oE '^\[[0-9]+\]' | head -1 | tr -d '[]')"
  if [ -z "$idx" ]; then
    return 1
  fi
  printf '%s' "$idx"
}

context_exists() {
  [ -f "$SXCTL_CONTEXT_FILE" ]
}

context_clear_runtime() {
  unset SXCTL_PROFILE_INDEX SXCTL_SOURCE_ID SXCTL_SOURCE_PATH SXCTL_DB_BACKEND SXCTL_DB_PATH || true
  unset SXCTL_PIPELINE_DB_PROFILE SXCTL_PIPELINE_DB_URL SXCTL_PIPELINE_DB_MODE SXCTL_VAULT_ROOT || true
  unset SXCTL_SCHEMA_NAME SXCTL_SEARCH_PATH || true
}

context_load() {
  context_clear_runtime
  if ! context_exists; then
    return 1
  fi

  set -a
  # shellcheck disable=SC1090
  source "$SXCTL_CONTEXT_FILE"
  set +a

  export SX_PROFILE_INDEX="${SXCTL_PROFILE_INDEX:-${SX_PROFILE_INDEX:-1}}"
  export SX_DEFAULT_SOURCE_ID="${SXCTL_SOURCE_ID:-${SX_DEFAULT_SOURCE_ID:-default}}"
  export OBSIDIAN_VAULT_PATH="${SXCTL_VAULT_ROOT:-${OBSIDIAN_VAULT_PATH:-}}"
  local backend="${SXCTL_DB_BACKEND:-$DEFAULT_DB_BACKEND}"
  SXCTL_DB_BACKEND="$backend"

  if [ "$backend" = "postgres_primary" ]; then
    export SX_DB_BACKEND_MODE="POSTGRES_PRIMARY"
    export SX_PIPELINE_DB_PROFILE="${SXCTL_PIPELINE_DB_PROFILE:-${SX_PIPELINE_DB_PROFILE:-}}"
    export SX_PIPELINE_DATABASE_URL="${SXCTL_PIPELINE_DB_URL:-${SX_PIPELINE_DATABASE_URL:-}}"
    export SX_PIPELINE_DB_MODE="${SXCTL_PIPELINE_DB_MODE:-LOCAL}"
    export SX_POSTGRES_DSN="${SXCTL_PIPELINE_DB_URL:-${SX_POSTGRES_DSN:-}}"
    export SXCTL_SCHEMA_NAME="${SXCTL_SCHEMA_NAME:-${SXCTL_SCHEMA_NAME:-}}"
    export SXCTL_SEARCH_PATH="${SXCTL_SEARCH_PATH:-${SXCTL_SEARCH_PATH:-}}"
  elif [ "$backend" = "postgres" ]; then
    export SX_DB_BACKEND_MODE="POSTGRES_MIRROR"
    export SX_PIPELINE_DB_PROFILE="${SXCTL_PIPELINE_DB_PROFILE:-${SX_PIPELINE_DB_PROFILE:-}}"
    export SX_PIPELINE_DATABASE_URL="${SXCTL_PIPELINE_DB_URL:-${SX_PIPELINE_DATABASE_URL:-}}"
    export SX_PIPELINE_DB_MODE="${SXCTL_PIPELINE_DB_MODE:-LOCAL}"
    export SXCTL_SCHEMA_NAME="${SXCTL_SCHEMA_NAME:-${SXCTL_SCHEMA_NAME:-}}"
    export SXCTL_SEARCH_PATH="${SXCTL_SEARCH_PATH:-${SXCTL_SEARCH_PATH:-}}"
  else
    export SX_DB_BACKEND_MODE="SQLITE"
    export SX_PIPELINE_DB_MODE="SQL"
    export SX_DB_PATH="${SXCTL_DB_PATH:-${SX_DB_PATH:-}}"
    unset SX_PIPELINE_DB_PROFILE SX_PIPELINE_DATABASE_URL || true
    unset SXCTL_SCHEMA_NAME SXCTL_SEARCH_PATH || true
  fi

  return 0
}

context_save() {
  ensure_dirs
  cat >"$SXCTL_CONTEXT_FILE" <<EOF
SXCTL_PROFILE_INDEX=${SXCTL_PROFILE_INDEX:-1}
SXCTL_SOURCE_ID=${SXCTL_SOURCE_ID:-assets_1}
SXCTL_SOURCE_PATH=${SXCTL_SOURCE_PATH:-}
SXCTL_DB_BACKEND=${SXCTL_DB_BACKEND:-$DEFAULT_DB_BACKEND}
SXCTL_DB_PATH=${SXCTL_DB_PATH:-}
SXCTL_PIPELINE_DB_PROFILE=${SXCTL_PIPELINE_DB_PROFILE:-}
SXCTL_PIPELINE_DB_URL=${SXCTL_PIPELINE_DB_URL:-}
SXCTL_PIPELINE_DB_MODE=${SXCTL_PIPELINE_DB_MODE:-LOCAL}
SXCTL_VAULT_ROOT=${SXCTL_VAULT_ROOT:-}
SXCTL_SCHEMA_NAME=${SXCTL_SCHEMA_NAME:-}
SXCTL_SEARCH_PATH=${SXCTL_SEARCH_PATH:-}
SX_SCHEDULERX_ENV=${SX_SCHEDULERX_ENV:-../SchedulerX/backend/pipeline/.env}
EOF
  context_save_json
  ok "Saved context: $SXCTL_CONTEXT_FILE"
}

profile_rows() {
  sx_profile_apply
  local idx label path sid aliases
  while IFS='|' read -r idx label path sid aliases; do
    printf "[%s] %s | source_id=%s | path=%s\n" "$idx" "$label" "$sid" "$path"
  done < <(sx_profile_list)
}

select_profile() {
  local selected_idx="${SXCTL_PROFILE_INDEX:-${SX_PROFILE_INDEX:-}}"

  if is_noninteractive; then
    [ -n "$selected_idx" ] || die "SXCTL_NONINTERACTIVE=1 requires SXCTL_PROFILE_INDEX"
    export SX_PROFILE_INDEX="$selected_idx"
    sx_profile_apply
    return 0
  fi

  local options=()
  local row
  while IFS= read -r row; do
    options+=("$row")
  done < <(profile_rows)
  options+=("Back to main menu")

  local picked
  picked="$(pick_with_ui "Select source profile" "${options[@]}")" || return 1
  if [ "$picked" = "Back to main menu" ]; then
    return 1
  fi
  selected_idx="$(extract_profile_idx "$picked")"
  [ -n "$selected_idx" ] || die "Could not parse profile index from selection"

  export SX_PROFILE_INDEX="$selected_idx"
  sx_profile_apply
}

browse_directories() {
  local current="${1:-${HOME:-/}}"
  [ -d "$current" ] || current="${HOME:-/}"

  while true; do
    local options=()
    options+=("Select current: $current")
    options+=("Go parent directory")
    options+=("Go home (~)")
    options+=("Go root (/)")
    [ -d "/mnt" ] && options+=("Go /mnt")
    [ -d "/mnt/t" ] && options+=("Go /mnt/t")
    options+=("Enter path manually")
    options+=("Back")

    local d
    while IFS= read -r d; do
      [ -n "$d" ] || continue
      options+=("Dir: $d")
    done < <(find "$current" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | sort | head -40)

    local picked
    picked="$(pick_with_ui "Browse filesystem" "${options[@]}")" || return 1
    case "$picked" in
      "Select current: "*) printf '%s' "${picked#Select current: }"; return 0 ;;
      "Go parent directory") current="$(dirname "$current")" ;;
      "Go home (~)") current="${HOME:-/}" ;;
      "Go root (/)") current="/" ;;
      "Go /mnt") current="/mnt" ;;
      "Go /mnt/t") current="/mnt/t" ;;
      "Enter path manually")
        local p
        read -r -p "  Path: " p
        if [ -n "$p" ] && [ -d "$p" ]; then
          current="$p"
        else
          warn "Directory not found: ${p:-<empty>}"
        fi
        ;;
      "Back") return 1 ;;
      "Dir: "*)
        local next="${picked#Dir: }"
        if [ -d "$next" ]; then
          current="$next"
        else
          warn "Directory no longer exists: $next"
        fi
        ;;
    esac
  done
}

normalize_vault_root_candidate() {
  local p="${1:-}"
  [ -n "$p" ] || return 1
  [ -d "$p" ] || return 1

  if [ "$(basename "$p")" = ".obsidian" ]; then
    dirname "$p"
    return 0
  fi

  if [ -d "$p/.obsidian" ]; then
    printf '%s' "$p"
    return 0
  fi

  local cur="$p"
  while [ "$cur" != "/" ] && [ -n "$cur" ]; do
    cur="$(dirname "$cur")"
    [ -n "$cur" ] || break
    if [ -d "$cur/.obsidian" ]; then
      printf '%s' "$cur"
      return 0
    fi
  done

  return 1
}

ensure_obsidian_dir() {
  local root="$1"
  [ -d "$root" ] || return 1
  if [ -d "$root/.obsidian" ]; then
    return 0
  fi

  local tpl_default="/mnt/t/AlexNova/.obsidian"
  local action
  action="$(pick_with_ui "No .obsidian found in $root" \
    "🛠️  Create empty .obsidian" \
    "📋 Copy template from $tpl_default" \
    "↩️  Choose another path" \
    "🏠 Back to main menu")" || return 1

  case "$action" in
    "🛠️  Create empty .obsidian")
      mkdir -p "$root/.obsidian" || return 1
      ;;
    "📋 Copy template from $tpl_default")
      if [ -d "$tpl_default" ]; then
        mkdir -p "$root/.obsidian" || return 1
        cp -a "$tpl_default/." "$root/.obsidian/" || return 1
      else
        warn "Template vault not found: $tpl_default"
        return 1
      fi
      ;;
    "🏠 Back to main menu") return 2 ;;
    *) return 1 ;;
  esac

  [ -d "$root/.obsidian" ]
}

pick_vault_root() {
  local initial_guess="${1:-}"
  local guess=""
  local remembered=""
  remembered="$(read_last_vault_path)"

  if [ -n "$initial_guess" ]; then
    guess="$initial_guess"
  elif [ -n "${SXCTL_VAULT_ROOT:-}" ]; then
    guess="$SXCTL_VAULT_ROOT"
  elif [ -n "${SX_PA_SOURCE_PATH:-}" ]; then
    guess="$SX_PA_SOURCE_PATH"
  elif [ -n "${OBSIDIAN_VAULT_PATH:-}" ]; then
    guess="$OBSIDIAN_VAULT_PATH"
  elif [ -n "${SX_PA_VAULT_PATH:-}" ]; then
    guess="$SX_PA_VAULT_PATH"
  elif [ -n "$remembered" ]; then
    guess="$remembered"
  fi

  if is_noninteractive; then
    [ -n "$guess" ] || die "SXCTL_NONINTERACTIVE=1 requires SXCTL_VAULT_ROOT (or OBSIDIAN_VAULT_PATH)"

    local normalized_guess
    normalized_guess="$(normalize_vault_root_candidate "$guess" || true)"
    if [ -n "$normalized_guess" ]; then
      guess="$normalized_guess"
    fi

    local reason
    reason="$(vault_validation_error "$guess")"
    [ -z "$reason" ] || die "Invalid vault root '$guess': $reason"
    SXCTL_VAULT_ROOT="$guess"
    OBSIDIAN_VAULT_PATH="$guess"
    remember_last_vault_path "$guess"
    history_add_path "$guess"
    return 0
  fi

  local attempts=0
  while [ "$attempts" -lt 12 ]; do
    attempts=$((attempts + 1))

    local hist=()
    local p
    while IFS= read -r p; do
      [ -n "$p" ] || continue
      hist+=("$p")
    done < <(history_list_paths)

    local opts=()
    if [ "${#hist[@]}" -eq 0 ]; then
      opts+=("History: (none)")
    else
      for p in "${hist[@]}"; do
        opts+=("History: $p")
      done
    fi
    opts+=("Browse filesystem")
    opts+=("Use source profile path: ${SX_PA_SOURCE_PATH:-$guess}")
    opts+=("Use current path: ${guess}")
    opts+=("Enter manually")
    opts+=("Back")

    local action
    action="$(pick_with_ui "Select Obsidian vault root" "${opts[@]}")" || return 1

    local input=""
    case "$action" in
      "History: (none)")
        continue
        ;;
      "History: "*)
        input="${action#History: }"
        ;;
      "Browse filesystem")
        input="$(browse_directories "${guess:-${HOME:-/}}")" || continue
        ;;
      "Enter manually")
        read -r -p "  Vault root${guess:+ [$guess]}: " input
        input="${input:-$guess}"
        ;;
      "Use source profile path: "*)
        input="${SX_PA_SOURCE_PATH:-$guess}"
        ;;
      "Use current path: "*)
        input="$guess"
        ;;
      "Back")
        return 1
        ;;
    esac

    if [ -z "$input" ]; then
      warn "Vault root cannot be empty"
      continue
    fi
    if [ ! -d "$input" ]; then
      warn "Directory not found: $input"
      continue
    fi

    local normalized
    normalized="$(normalize_vault_root_candidate "$input" || true)"
    if [ -n "$normalized" ] && [ "$normalized" != "$input" ]; then
      input="$normalized"
      ok "Detected vault root: $input"
    fi

    if [ ! -d "$input/.obsidian" ]; then
      if ! ensure_obsidian_dir "$input"; then
        rc=$?
        if [ "$rc" -eq 2 ]; then
          return 1
        fi
        warn "Vault root must contain .obsidian/"
        continue
      fi
    fi

    local reason
    reason="$(vault_validation_error "$input")"
    if [ -n "$reason" ]; then
      err "Invalid vault root '$input': $reason"
      continue
    fi

    SXCTL_VAULT_ROOT="$input"
    OBSIDIAN_VAULT_PATH="$input"
    remember_last_vault_path "$input"
    history_add_path "$input"
    return 0
  done

  return 1
}

choose_vault_root_for_profile() {
  local profile_path="${SX_PA_SOURCE_PATH:-}"

  if is_noninteractive; then
    if [ -n "${SXCTL_VAULT_ROOT:-}" ]; then
      pick_vault_root "${SXCTL_VAULT_ROOT}"
      return 0
    fi
    pick_vault_root "$profile_path"
    return 0
  fi

  local choice
  choice="$(pick_with_ui "Vault root override" \
    "No, use source profile path (${profile_path})" \
    "Yes, choose a different path" \
    "Back to main menu")" || return 1

  if [ "$choice" = "Back to main menu" ]; then
    return 1
  fi

  if [ "$choice" = "No, use source profile path (${profile_path})" ]; then
    local normalized_profile
    normalized_profile="$(normalize_vault_root_candidate "$profile_path" || true)"
    SXCTL_VAULT_ROOT="${normalized_profile:-$profile_path}"
    OBSIDIAN_VAULT_PATH="$profile_path"
    if [ ! -d "$SXCTL_VAULT_ROOT/.obsidian" ]; then
      local next
      next="$(pick_with_ui "Selected path has no .obsidian" \
        "Create .obsidian here" \
        "Choose a different path" \
        "Back to main menu")" || return 1
      if [ "$next" = "Back to main menu" ]; then
        return 1
      fi
      if [ "$next" = "Create .obsidian here" ]; then
        if ! ensure_obsidian_dir "$SXCTL_VAULT_ROOT"; then
          return 1
        fi
      else
        pick_vault_root "$SXCTL_VAULT_ROOT" || return 1
        return 0
      fi
    fi
    remember_last_vault_path "$SXCTL_VAULT_ROOT"
    history_add_path "$SXCTL_VAULT_ROOT"
    return 0
  fi

  pick_vault_root "$SXCTL_VAULT_ROOT" || return 1
}

alias_to_mode() {
  local alias="${1:-}"
  case "$alias" in
    SUPABASE_SESSION_*) printf "SESSION" ;;
    SUPABASE_TRANS_*|SUPABASE_TRANSACTION_*) printf "TRANSACTION" ;;
    *) printf "LOCAL" ;;
  esac
}

select_db_backend() {
  local backend="${SXCTL_DB_BACKEND:-}"

  if is_noninteractive; then
    backend="${backend:-${SXCTL_DB_BACKEND:-$DEFAULT_DB_BACKEND}}"
  else
    if [ -z "$backend" ]; then
      local picked
      picked="$(pick_with_ui "Select DB backend" "PostgreSQL Primary (recommended)" "PostgreSQL Mirror" "SQLite Legacy (explicit)")" || die "DB backend selection cancelled"
      if [ "$picked" = "PostgreSQL Primary (recommended)" ]; then
        backend="postgres_primary"
      elif [ "$picked" = "PostgreSQL Mirror" ]; then
        backend="postgres"
      else
        backend="sqlite"
      fi
    fi
  fi

  case "$backend" in
    sqlite|SQLITE)
      SXCTL_DB_BACKEND="sqlite"
      SXCTL_DB_PATH="$SX_PA_DB_PATH"
      SXCTL_PIPELINE_DB_PROFILE=""
      SXCTL_PIPELINE_DB_URL=""
      SXCTL_PIPELINE_DB_MODE="SQL"
      SXCTL_SCHEMA_NAME=""
      SXCTL_SEARCH_PATH=""
      ;;
    postgres_primary|POSTGRES_PRIMARY)
      SXCTL_DB_BACKEND="postgres_primary"
      local aliases=()
      [ -n "${SX_PA_PIPELINE_DB_LOCAL_PROFILE:-}" ] && aliases+=("${SX_PA_PIPELINE_DB_LOCAL_PROFILE}")
      [ -n "${SX_PA_PIPELINE_DB_SESSION_PROFILE:-}" ] && aliases+=("${SX_PA_PIPELINE_DB_SESSION_PROFILE}")
      [ -n "${SX_PA_PIPELINE_DB_TRANS_PROFILE:-}" ] && aliases+=("${SX_PA_PIPELINE_DB_TRANS_PROFILE}")

      local selected_alias="${SXCTL_DB_PROFILE:-${SXCTL_PIPELINE_DB_PROFILE:-}}"
      if is_noninteractive; then
        [ -n "$selected_alias" ] || selected_alias="${SX_PA_PIPELINE_DB_LOCAL_PROFILE:-}"
      else
        if [ -z "$selected_alias" ]; then
          [ "${#aliases[@]}" -gt 0 ] || die "No DB aliases found for this profile"
          selected_alias="$(pick_with_ui "Select PostgreSQL DB profile" "${aliases[@]}")" || die "DB profile selection cancelled"
        fi
      fi

      [ -n "$selected_alias" ] || die "PostgreSQL backend requires SXCTL_DB_PROFILE (or profile alias mapping)"
      SXCTL_PIPELINE_DB_PROFILE="$selected_alias"
      SXCTL_PIPELINE_DB_URL="$(sx_pa_db_url_from_alias "$selected_alias")"
      SXCTL_PIPELINE_DB_MODE="$(alias_to_mode "$selected_alias")"
      SXCTL_DB_PATH="$SX_PA_DB_PATH"

      [ -n "$SXCTL_PIPELINE_DB_URL" ] || die "No DATABASE URL could be derived for DB profile '$selected_alias'"

      local schema_prefix source_norm
      schema_prefix="${SX_POSTGRES_SCHEMA_PREFIX:-sx}"
      source_norm="$(printf '%s' "${SXCTL_SOURCE_ID:-default}" | sed 's/[^A-Za-z0-9._-]//g; s/[.-]/_/g')"
      SXCTL_SCHEMA_NAME="${schema_prefix}_${source_norm}"
      SXCTL_SEARCH_PATH="${SXCTL_SCHEMA_NAME},public"
      ;;
    postgres|POSTGRES)
      SXCTL_DB_BACKEND="postgres"
      local aliases=()
      [ -n "${SX_PA_PIPELINE_DB_LOCAL_PROFILE:-}" ] && aliases+=("${SX_PA_PIPELINE_DB_LOCAL_PROFILE}")
      [ -n "${SX_PA_PIPELINE_DB_SESSION_PROFILE:-}" ] && aliases+=("${SX_PA_PIPELINE_DB_SESSION_PROFILE}")
      [ -n "${SX_PA_PIPELINE_DB_TRANS_PROFILE:-}" ] && aliases+=("${SX_PA_PIPELINE_DB_TRANS_PROFILE}")

      local selected_alias="${SXCTL_DB_PROFILE:-${SXCTL_PIPELINE_DB_PROFILE:-}}"

      if is_noninteractive; then
        [ -n "$selected_alias" ] || selected_alias="${SX_PA_PIPELINE_DB_LOCAL_PROFILE:-}"
      else
        if [ -z "$selected_alias" ]; then
          [ "${#aliases[@]}" -gt 0 ] || die "No pipeline DB aliases found for this profile"
          selected_alias="$(pick_with_ui "Select PostgreSQL DB profile" "${aliases[@]}")" || die "DB profile selection cancelled"
        fi
      fi

      [ -n "$selected_alias" ] || die "PostgreSQL backend requires SXCTL_DB_PROFILE (or profile alias mapping)"
      SXCTL_PIPELINE_DB_PROFILE="$selected_alias"
      SXCTL_PIPELINE_DB_URL="$(sx_pa_db_url_from_alias "$selected_alias")"
      SXCTL_PIPELINE_DB_MODE="$(alias_to_mode "$selected_alias")"
      SXCTL_DB_PATH="$SX_PA_DB_PATH"

      if [ -z "$SXCTL_PIPELINE_DB_URL" ]; then
        die "No DATABASE URL could be derived for DB profile '$selected_alias'"
      fi

      local parsed_sp parsed_schema
      parsed_sp="$(parse_search_path_from_url "$SXCTL_PIPELINE_DB_URL")"
      if [ -n "${SXCTL_SCHEMA_NAME:-}" ]; then
        SXCTL_SEARCH_PATH="${SXCTL_SCHEMA_NAME},public"
      elif [ -n "$parsed_sp" ]; then
        SXCTL_SEARCH_PATH="$parsed_sp"
        parsed_schema="$(printf '%s' "$parsed_sp" | cut -d',' -f1 | xargs)"
        SXCTL_SCHEMA_NAME="$parsed_schema"
      else
        SXCTL_SCHEMA_NAME="${SXCTL_SCHEMA_NAME:-public}"
        SXCTL_SEARCH_PATH="${SXCTL_SCHEMA_NAME},public"
      fi
      ;;
    *) die "Unknown DB backend: $backend (use postgres_primary|postgres|sqlite)" ;;
  esac
}

configure_context() {
  select_profile || return 1
  sx_profile_apply

  SXCTL_PROFILE_INDEX="$SX_PROFILE_INDEX"
  SXCTL_SOURCE_ID="$SX_PA_SOURCE_ID"
  SXCTL_SOURCE_PATH="$SX_PA_SOURCE_PATH"

  choose_vault_root_for_profile || return 1
  select_db_backend
  context_save
}

ensure_context() {
  if context_exists; then
    context_load
    return 0
  fi
  warn "No saved context found. Launching context setup."
  configure_context
  context_load
}

print_context_summary() {
  context_load || return 0
  local backend="${SXCTL_DB_BACKEND:-$DEFAULT_DB_BACKEND}"
  say "  ${C_BOLD}${C_CYAN}Active Context${C_RST}"
  say "  ${C_DIM}$(_hr "-" 56)${C_RST}"
  say "  ${C_DIM}Profile${C_RST}      ${C_BOLD}${C_WHT}${SXCTL_PROFILE_INDEX:-unset}${C_RST}"
  say "  ${C_DIM}Source ID${C_RST}    ${C_BOLD}${C_WHT}${SXCTL_SOURCE_ID:-unset}${C_RST}"
  say "  ${C_DIM}Data Path${C_RST}    ${C_WHT}${SXCTL_SOURCE_PATH:-unset}${C_RST}"
  say "  ${C_DIM}DB Backend${C_RST}   ${C_BOLD}${C_WHT}${backend}${C_RST}"
  if [ "$backend" = "postgres" ] || [ "$backend" = "postgres_primary" ]; then
    say "  ${C_DIM}Schema${C_RST}       ${C_WHT}${SXCTL_SCHEMA_NAME:-unset}${C_RST}"
    say "  ${C_DIM}Search Path${C_RST}  ${C_WHT}${SXCTL_SEARCH_PATH:-unset}${C_RST}"
  else
    say "  ${C_DIM}DB Path${C_RST}      ${C_WHT}${SXCTL_DB_PATH:-unset}${C_RST}"
    say "  ${C_DIM}Mode${C_RST}         ${C_ITAL}${C_YEL}legacy sqlite${C_RST}"
  fi
}

run_make_action() {
  local label="$1"
  local target="$2"
  ensure_context
  sx_profile_apply
  sx_profile_print_context "$label"
  make -f "$ROOT_DIR/scripts/Makefile" "$target"
}

run_context_python() {
  local label="$1"
  shift
  ensure_context
  context_load
  sx_profile_apply
  sx_profile_print_context "$label"
  ./.venv/bin/python "$@"
}

ensure_psycopg_for_postgres_primary() {
  if [ "${SXCTL_DB_BACKEND:-$DEFAULT_DB_BACKEND}" != "postgres_primary" ]; then
    return 0
  fi

  if ./.venv/bin/python -c "import psycopg" >/dev/null 2>&1; then
    return 0
  fi

  warn "PostgreSQL primary mode requires psycopg (Python package)."
  warn "Attempting to install psycopg[binary] into .venv..."
  if ./.venv/bin/python -m pip install "psycopg[binary]" >/dev/null 2>&1; then
    ok "Installed psycopg[binary]"
    return 0
  fi

  die "psycopg installation failed. Run: ./.venv/bin/python -m pip install 'psycopg[binary]'"
}

action_init_db() {
  ensure_psycopg_for_postgres_primary
  if [ "${SXCTL_DB_BACKEND:-$DEFAULT_DB_BACKEND}" = "postgres_primary" ]; then
    run_context_python "api pg-bootstrap" -m sx_db pg-bootstrap --source "${SXCTL_SOURCE_ID:-${SX_DEFAULT_SOURCE_ID:-default}}"
  else
    run_context_python "api init" -m sx_db init
  fi
}

action_import_csv() {
  ensure_psycopg_for_postgres_primary
  local idx="${SXCTL_PROFILE_INDEX:-${SX_PROFILE_INDEX:-1}}"

  # Prefer explicit per-profile CSV env vars, then SchedulerX assets_N fallback.
  local c_key="CSV_consolidated_${idx}"
  local a_key="CSV_authors_${idx}"
  local b_key="CSV_bookmarks_${idx}"

  local csv_c="${!c_key:-}"
  local csv_a="${!a_key:-}"
  local csv_b="${!b_key:-}"

  local fallback_base="$ROOT_DIR/../SchedulerX/assets_${idx}/xlsx_files"
  [ -n "$csv_c" ] || csv_c="$fallback_base/consolidated.csv"
  [ -n "$csv_a" ] || csv_a="$fallback_base/authors.csv"
  [ -n "$csv_b" ] || csv_b="$fallback_base/bookmarks.csv"

  if [ ! -f "$csv_c" ]; then
    die "Consolidated CSV not found for profile ${idx}: $csv_c"
  fi

  local args=(
    -m sx_db import-csv
    --source "${SXCTL_SOURCE_ID:-${SX_DEFAULT_SOURCE_ID:-default}}"
    --csv "$csv_c"
  )
  [ -f "$csv_a" ] && args+=(--authors "$csv_a")
  [ -f "$csv_b" ] && args+=(--bookmarks "$csv_b")

  run_context_python "api import" "${args[@]}"
}

action_start_api() {
  ensure_psycopg_for_postgres_primary
  run_context_python "api serve" -m sx_db serve
}

check_sqlite_path() {
  local p="${SXCTL_DB_PATH:-}"
  [ -n "$p" ] || return 1
  local parent
  parent="$(dirname "$p")"
  [ -d "$parent" ] || return 1
  [ -w "$parent" ] || return 1
  return 0
}

diagnostics() {
  ensure_context
  sx_profile_apply

  banner "Diagnostics" "sx_obsidian health check"
  say ""
  print_context_summary
  say ""

  local reason
  reason="$(vault_validation_error "${SXCTL_VAULT_ROOT:-}")"
  if [ -z "$reason" ]; then
    ok "Vault root is valid"
  else
    err "Vault root invalid: $reason"
  fi

  if [ "${SXCTL_DB_BACKEND:-$DEFAULT_DB_BACKEND}" = "postgres" ] || [ "${SXCTL_DB_BACKEND:-$DEFAULT_DB_BACKEND}" = "postgres_primary" ]; then
    if [ -n "${SXCTL_PIPELINE_DB_URL:-}" ]; then
      ok "PostgreSQL URL present (${SX_PA_PIPELINE_DB_URL_REDACTED:-redacted})"
    else
      err "PostgreSQL URL missing"
    fi
  else
    if check_sqlite_path; then
      ok "SQLite path is writable: ${SXCTL_DB_PATH:-unset}"
    else
      err "SQLite path is not writable/creatable: ${SXCTL_DB_PATH:-unset}"
    fi
  fi

  local pidfile="./_logs/sx_db_api.pid"
  if [ -f "$pidfile" ]; then
    local pid
    pid="$(cat "$pidfile" 2>/dev/null || true)"
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      ok "API process running (pid=$pid)"
    else
      warn "API pidfile exists but process is not running"
    fi
  else
    warn "API not running (no pidfile)"
  fi
}

port_in_use() {
  local port="${1:-8123}"
  if has_cmd ss; then
    ss -ltn "( sport = :$port )" 2>/dev/null | grep -q ":$port " && return 0
  fi
  if has_cmd lsof; then
    lsof -nP -iTCP:"$port" -sTCP:LISTEN 2>/dev/null | grep -q LISTEN && return 0
  fi
  return 1
}

verify_run() {
  ensure_venv
  ensure_context

  banner "Verify" "CLI/backend smoke checks"

  local py="./.venv/bin/python"
  local tmpv
  tmpv="$(mktemp -d)"
  mkdir -p "$tmpv/.obsidian"

  local old_nonint="${SXCTL_NONINTERACTIVE:-0}"
  export SXCTL_NONINTERACTIVE=1

  say "[1/8] Shell syntax checks"
  bash -n "$ROOT_DIR/scripts/sxctl.sh" "$ROOT_DIR/scripts/profile_adapter.sh"

  say "[2/8] Targeted Python tests"
  "$py" -m pytest -q \
    tests/test_cli_sources.py \
    tests/test_sources_api.py \
    tests/test_postgres_schema_utils.py

  say "[3/8] Context init (postgres_primary)"
  SXCTL_PROFILE_INDEX=2 SXCTL_VAULT_ROOT="$tmpv" SXCTL_DB_BACKEND=postgres_primary SXCTL_DB_PROFILE=LOCAL_2 "$ROOT_DIR/scripts/sxctl.sh" context init

  say "[4/8] PG init/import"
  SXCTL_NONINTERACTIVE=1 "$ROOT_DIR/scripts/sxctl.sh" api init
  SXCTL_NONINTERACTIVE=1 "$ROOT_DIR/scripts/sxctl.sh" api import

  say "[5/8] Context init (sqlite)"
  SXCTL_PROFILE_INDEX=1 SXCTL_VAULT_ROOT="$tmpv" SXCTL_DB_BACKEND=sqlite "$ROOT_DIR/scripts/sxctl.sh" context init

  say "[6/8] SQLite init/import"
  SXCTL_NONINTERACTIVE=1 "$ROOT_DIR/scripts/sxctl.sh" api init
  SXCTL_NONINTERACTIVE=1 "$ROOT_DIR/scripts/sxctl.sh" api import

  say "[7/8] API lifecycle"
  SXCTL_NONINTERACTIVE=1 "$ROOT_DIR/scripts/sxctl.sh" api serve-bg
  SXCTL_NONINTERACTIVE=1 "$ROOT_DIR/scripts/sxctl.sh" api server-status
  SXCTL_NONINTERACTIVE=1 "$ROOT_DIR/scripts/sxctl.sh" api stop

  say "[8/8] Diagnostics"
  SXCTL_NONINTERACTIVE=1 "$ROOT_DIR/scripts/sxctl.sh" diagnostics

  export SXCTL_NONINTERACTIVE="$old_nonint"
  rm -rf "$tmpv"

  ok "verify completed successfully"
}

ensure_venv() {
  if [ ! -x "./.venv/bin/python" ]; then
    warn "Missing .venv; bootstrapping via ./scripts/deploy.sh..."
    ./scripts/deploy.sh
  fi
  if [ ! -x "./.venv/bin/python" ]; then
    die "Missing .venv after bootstrap. Run: ./scripts/bootstrap.sh (or make -f scripts/Makefile bootstrap)"
  fi
}

menu_loop() {
  ensure_context

  local menu_options=(
    "API      Start server"
    "DB       Init backend"
    "CSV      Import CSV"
    "BUILD    Build + Install Plugin"
    "INSTALL  Install Plugin (no build)"
    "CTX      Change Context"
    "DIAG     Diagnostics"
    "QUIT     Quit"
  )

  while true; do
    clear 2>/dev/null || true
    banner "sx_obsidian" "Media Library Control Plane"
    say ""
    print_context_summary
    say ""
    say "${C_DIM}$(_hr "-" 56)${C_RST}"

    local picked=""
    local choice=""
    if is_noninteractive; then
      read -r -p "  Choose [1-8]: " choice
    else
      picked="$(pick_with_ui "Main menu" "${menu_options[@]}")" || choice="8"
      case "$picked" in
        "API"*) choice="1" ;;
        "DB"*) choice="2" ;;
        "CSV"*) choice="3" ;;
        "BUILD"*) choice="4" ;;
        "INSTALL"*) choice="5" ;;
        "CTX"*) choice="6" ;;
        "DIAG"*) choice="7" ;;
        "QUIT"*) choice="8" ;;
        *)
          warn "Unknown menu selection: ${picked:-<empty>}"
          choice=""
          ;;
      esac
    fi

    case "$choice" in
      1)
        ensure_venv
        action_start_api
        ;;
      2)
        ensure_venv
        action_init_db
        ;;
      3)
        ensure_venv
        action_import_csv
        ;;
      4)
        run_make_action "plugin build+install" "plugin-build"
        run_make_action "plugin install" "plugin-install"
        ;;
      5)
        run_make_action "plugin install" "plugin-install"
        ;;
      6)
        if ! configure_context; then
          warn "Context change cancelled; returning to main menu"
          continue
        fi
        ensure_context
        ;;
      7)
        diagnostics
        ;;
      8|q|Q|"")
        say "${C_CYAN}Goodbye.${C_RST}"
        break
        ;;
      *)
        warn "Unknown choice: $choice"
        ;;
    esac

    say ""
    read -r -p "  Press Enter to continue..." _ || true
  done
}

help() {
  cat <<'EOF'
Usage:
  ./scripts/sxctl.sh
  ./scripts/sxctl.sh menu
  ./scripts/sxctl.sh verify
  ./scripts/sxctl.sh context init
  ./scripts/sxctl.sh context show
  ./scripts/sxctl.sh diagnostics
  ./scripts/sxctl.sh api <serve|serve-bg|stop|server-status|init|import|status|menu>
  ./scripts/sxctl.sh plugin <update|build|install>

Notes:
- Context is persisted in ./.sxctl/context.env and reused across actions.
- In noninteractive mode, set:
    SXCTL_NONINTERACTIVE=1
    SXCTL_PROFILE_INDEX=2
    SXCTL_VAULT_ROOT=/path/to/vault
    SXCTL_DB_BACKEND=postgres_primary|postgres|sqlite
    SXCTL_DB_PROFILE=LOCAL_2   # required for postgres if not inferable
  Aliases also accepted:
    PROFILE_INDEX, VAULT_ROOT, DB_BACKEND, SCHEMA_NAME
- Default backend is PostgreSQL primary. SQLite is retained as explicit legacy mode.
- API server and DB backend are separate concerns.
EOF
}

cmd="${1:-menu}"
shift || true

ensure_dirs
history_prune_file

case "$cmd" in
  -h|--help|help)
    help
    ;;

  menu)
    menu_loop
    ;;

  context)
    sub="${1:-show}"
    shift || true
    case "$sub" in
      init|set|change)
        if ! configure_context; then
          die "Context setup cancelled"
        fi
        ;;
      show)
        ensure_context
        print_context_summary
        ;;
      clear)
        rm -f "$SXCTL_CONTEXT_FILE"
        ok "Cleared context file"
        ;;
      *)
        die "Unknown context subcommand: $sub"
        ;;
    esac
    ;;

  diagnostics)
    diagnostics
    ;;

  verify)
    verify_run
    ;;

  api)
    sub="${1:-serve}"
    shift || true
    ensure_venv
    ensure_context
    sx_profile_apply

    case "$sub" in
      serve | run | server)
        action_start_api
        ;;
      serve-bg | bg | background)
        sx_profile_print_context "api serve-bg"
        mkdir -p "./_logs"
        pidfile="./_logs/sx_db_api.pid"
        out="./_logs/sx_db_api.nohup.out"

        if port_in_use "${SX_API_PORT:-8123}"; then
          die "API port ${SX_API_PORT:-8123} already in use; stop existing server first (./scripts/sxctl.sh api stop)."
        fi

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
        ok "API started in background (pid=$pid)."
        ;;
      stop)
        pidfile="./_logs/sx_db_api.pid"
        if [ ! -f "$pidfile" ]; then
          say "No pidfile found ($pidfile). Is the API running?"
          exit 0
        fi
        pid="$(cat "$pidfile" 2>/dev/null || true)"
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
          say "Stopping API (pid=$pid)…"
          kill "$pid" 2>/dev/null || true
        fi
        rm -f "$pidfile" || true
        ok "Stopped (or already not running)."
        ;;
      server-status)
        pidfile="./_logs/sx_db_api.pid"
        if [ ! -f "$pidfile" ]; then
          say "API not running (no pidfile)."
          exit 0
        fi
        pid="$(cat "$pidfile" 2>/dev/null || true)"
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
          ok "API running (pid=$pid)."
        else
          warn "API not running (stale pidfile)."
        fi
        ;;
      init)
        action_init_db
        ;;
      import)
        action_import_csv
        ;;
      status | stats)
        sx_profile_print_context "api status"
        ./.venv/bin/python -m sx_db status
        ;;
      menu)
        sx_profile_print_context "api menu"
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
    ensure_context
    sx_profile_apply

    local_reason="$(vault_validation_error "${OBSIDIAN_VAULT_PATH:-}")"
    [ -z "$local_reason" ] || die "Vault root invalid before plugin action: $local_reason"

    case "$sub" in
      update)
        sx_profile_print_context "plugin update"
        make -f "$ROOT_DIR/scripts/Makefile" plugin-build plugin-install
        ;;
      build)
        sx_profile_print_context "plugin build"
        make -f "$ROOT_DIR/scripts/Makefile" plugin-build
        ;;
      install)
        sx_profile_print_context "plugin install"
        make -f "$ROOT_DIR/scripts/Makefile" plugin-install
        ;;
      *)
        die "Unknown plugin subcommand: $sub"
        ;;
    esac
    ;;

  *)
    die "Unknown command: $cmd (run ./scripts/sxctl.sh --help)"
    ;;
esac
