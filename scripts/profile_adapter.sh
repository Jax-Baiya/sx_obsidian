#!/usr/bin/env bash
set -euo pipefail

# Profile adapter for sx_obsidian launch flows.
#
# Goals:
# - Resolve SchedulerX-style source profiles (SRC_PROFILE_N / SRC_PATH_N)
# - Resolve source id naming (DATABASE_PROFILE_N preferred, fallback assets_N)
# - Derive SX_DB_PATH from source id using a stable naming pattern
# - Export SX_DEFAULT_SOURCE_ID and SX_DB_PATH for sx_db commands
# - Print a clear targeting banner so users know what they are operating on

sx_pa_root_dir() {
  cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd
}

sx_pa_sanitize_id() {
  local raw="${1:-}"
  raw="${raw//[^a-zA-Z0-9._-]/}"
  if [ -z "$raw" ]; then
    printf "default"
  else
    printf "%s" "$raw"
  fi
}

sx_pa_load_env_file() {
  local f="${1:-}"
  local preserve_existing="${2:-1}"
  if [ -z "$f" ] || [ ! -f "$f" ]; then
    return 0
  fi

  local line key val
  while IFS= read -r line || [ -n "$line" ]; do
    # Normalize CRLF endings.
    line="${line%$'\r'}"

    # Skip blank lines and comments.
    if [[ "$line" =~ ^[[:space:]]*$ ]]; then
      continue
    fi
    if [[ "$line" =~ ^[[:space:]]*# ]]; then
      continue
    fi

    # Parse KEY=VALUE (optionally prefixed with 'export ').
    if [[ "$line" =~ ^[[:space:]]*(export[[:space:]]+)?([A-Za-z_][A-Za-z0-9_]*)[[:space:]]*=(.*)$ ]]; then
      key="${BASH_REMATCH[2]}"
      val="${BASH_REMATCH[3]}"

      # Trim outer whitespace.
      val="${val#"${val%%[![:space:]]*}"}"
      val="${val%"${val##*[![:space:]]}"}"

      # Remove simple inline comments for unquoted values.
      if [[ ! "$val" =~ ^".*"$ ]] && [[ ! "$val" =~ ^\'.*\'$ ]]; then
        val="${val%%[[:space:]]#*}"
        val="${val%"${val##*[![:space:]]}"}"
      fi

      # Strip matching single/double quotes.
      if [[ "$val" =~ ^"(.*)"$ ]]; then
        val="${BASH_REMATCH[1]}"
      elif [[ "$val" =~ ^\'(.*)\'$ ]]; then
        val="${BASH_REMATCH[1]}"
      fi

      # Keep runtime-exported overrides (e.g., menu selection/context) authoritative.
      if [ "$preserve_existing" = "1" ] && [ -n "${!key+x}" ]; then
        continue
      fi

      export "$key=$val"
    fi
  done <"$f"
}

sx_pa_val() {
  local key="${1:?key required}"
  if [ -n "${!key:-}" ]; then
    printf "%s" "${!key}"
  fi
}

sx_pa_profile_indices() {
  local vars i
  vars="$(compgen -A variable | grep -E '^(SRC_PROFILE|SRC_PATH)_[0-9]+$' || true)"
  if [ -z "$vars" ]; then
    printf "1\n"
    return 0
  fi

  for i in $vars; do
    printf "%s\n" "$i"
  done \
    | sed -E 's/^(SRC_PROFILE|SRC_PATH)_([0-9]+)$/\2/' \
    | sort -n -u
}

sx_pa_profile_path_by_index() {
  local idx="${1:?idx required}"
  local k1="SRC_PROFILE_${idx}"
  local k2="SRC_PATH_${idx}"
  local v=""
  v="$(sx_pa_val "$k1")"
  if [ -z "$v" ]; then
    v="$(sx_pa_val "$k2")"
  fi
  if [ -z "$v" ]; then
    v="${SRC_PROFILE:-${SRC_PATH:-}}"
  fi
  printf "%s" "$v"
}

sx_pa_profile_label_by_index() {
  local idx="${1:?idx required}"
  local k1="SRC_PROFILE_${idx}_LABEL"
  local k2="SRC_PATH_${idx}_LABEL"
  local v=""
  v="$(sx_pa_val "$k1")"
  if [ -z "$v" ]; then
    v="$(sx_pa_val "$k2")"
  fi
  if [ -z "$v" ]; then
    v="profile_${idx}"
  fi
  printf "%s" "$v"
}

sx_pa_source_id_by_index() {
  local idx="${1:?idx required}"
  local k1="DATABASE_PROFILE_${idx}"
  local k2="SRC_PROFILE_${idx}_ID"
  local v=""
  # Prefer explicit source id if defined.
  v="$(sx_pa_val "$k2")"

  # Legacy compatibility: some envs use DATABASE_PROFILE_N for source id,
  # but newer SchedulerX envs store comma-separated DB aliases there
  # (e.g. LOCAL_2,SUPABASE_SESSION_2,SUPABASE_TRANS_2).
  # That value must NOT be used as source_id.
  if [ -z "$v" ]; then
    v="$(sx_pa_val "$k1")"
    if [[ "$v" == *,* ]]; then
      v=""
    fi
    if [[ "$v" =~ ^(LOCAL|SUPABASE_SESSION|SUPABASE_TRANS|SUPABASE_TRANSACTION)_[0-9]+$ ]]; then
      v=""
    fi
  fi

  if [ -z "$v" ]; then
    v="assets_${idx}"
  fi
  sx_pa_sanitize_id "$v"
}

sx_pa_profile_db_aliases_by_index() {
  local idx="${1:?idx required}"
  local lk1="SRC_PATH_${idx}_DB_LOCAL"
  local lk2="SRC_PROFILE_${idx}_DB_LOCAL"
  local sk1="SRC_PATH_${idx}_DB_SESSION"
  local sk2="SRC_PROFILE_${idx}_DB_SESSION"
  local tk1="SRC_PATH_${idx}_DB_TRANSACTION"
  local tk2="SRC_PROFILE_${idx}_DB_TRANSACTION"

  local local_alias session_alias trans_alias
  local_alias="$(sx_pa_val "$lk1")"
  if [ -z "$local_alias" ]; then
    local_alias="$(sx_pa_val "$lk2")"
  fi

  session_alias="$(sx_pa_val "$sk1")"
  if [ -z "$session_alias" ]; then
    session_alias="$(sx_pa_val "$sk2")"
  fi

  trans_alias="$(sx_pa_val "$tk1")"
  if [ -z "$trans_alias" ]; then
    trans_alias="$(sx_pa_val "$tk2")"
  fi

  printf "%s|%s|%s" "$local_alias" "$session_alias" "$trans_alias"
}

sx_pa_profile_sql_db_path_by_index() {
  local idx="${1:?idx required}"
  local k1="SQL_DB_PATH_${idx}"
  local k2="SX_SQL_DB_PATH_${idx}"
  local k3="SRC_PATH_${idx}_DB_SQL"
  local k4="SRC_PROFILE_${idx}_DB_SQL"
  local v=""

  v="$(sx_pa_val "$k1")"
  if [ -z "$v" ]; then v="$(sx_pa_val "$k2")"; fi
  if [ -z "$v" ]; then v="$(sx_pa_val "$k3")"; fi
  if [ -z "$v" ]; then v="$(sx_pa_val "$k4")"; fi

  printf "%s" "$v"
}

sx_pa_redact_url() {
  local url="${1:-}"
  if [ -z "$url" ]; then
    printf ""
    return 0
  fi

  # redact credentials if present
  local out
  out="$(printf '%s' "$url" | sed -E 's#(postgres(ql)?://)[^/@]+(:[^/@]*)?@#\1***:***@#')"
  printf "%s" "$out"
}

sx_pa_db_url_from_alias() {
  local alias="${1:-}"
  if [ -z "$alias" ]; then
    printf ""
    return 0
  fi

  local user_key="${alias}_DB_USER"
  local pass_key="${alias}_DB_PASSWORD"
  local host_key="${alias}_DB_HOST"
  local port_key="${alias}_DB_PORT"
  local name_key="${alias}_DB_NAME"
  local schema_key="${alias}_DB_SCHEMA"

  local user pass host port name schema
  user="$(sx_pa_val "$user_key")"
  pass="$(sx_pa_val "$pass_key")"
  host="$(sx_pa_val "$host_key")"
  port="$(sx_pa_val "$port_key")"
  name="$(sx_pa_val "$name_key")"
  schema="$(sx_pa_val "$schema_key")"

  if [ -z "$user" ] || [ -z "$host" ] || [ -z "$port" ] || [ -z "$name" ]; then
    printf ""
    return 0
  fi

  local url="postgresql://${user}:${pass}@${host}:${port}/${name}"
  if [ -n "$schema" ]; then
    url="${url}?options=-c%20search_path%3D${schema}"
  fi
  printf "%s" "$url"
}

sx_profile_list() {
  sx_pa_ctx_init >/dev/null 2>&1 || true
  local idx path label sid aliases
  while IFS= read -r idx; do
    path="$(sx_pa_profile_path_by_index "$idx")"
    label="$(sx_pa_profile_label_by_index "$idx")"
    sid="$(sx_pa_source_id_by_index "$idx")"
    aliases="$(sx_pa_profile_db_aliases_by_index "$idx")"
    printf "%s|%s|%s|%s|%s\n" "$idx" "$label" "$path" "$sid" "$aliases"
  done < <(sx_pa_profile_indices)
}

sx_pa_ctx_init() {
  local root
  root="$(sx_pa_root_dir)"

  # Load sx_obsidian env first (base defaults), then SchedulerX env (profile mappings).
  sx_pa_load_env_file "$root/.env"

  local scheduler_env_default
  scheduler_env_default="$root/../SchedulerX/.env"
  export SX_SCHEDULERX_ENV="${SX_SCHEDULERX_ENV:-$scheduler_env_default}"
  sx_pa_load_env_file "$SX_SCHEDULERX_ENV"

  export SX_PROFILE_INDEX="${SX_PROFILE_INDEX:-1}"

  local idx
  idx="$SX_PROFILE_INDEX"

  # Support both user-mentioned and current naming conventions.
  local src_profile_path src_label source_id
  src_profile_path="$(sx_pa_profile_path_by_index "$idx")"
  src_label="$(sx_pa_profile_label_by_index "$idx")"
  source_id="$(sx_pa_source_id_by_index "$idx")"

  # Manual launch overrides (optional)
  if [ -n "${SX_PROFILE_SOURCE_PATH_OVERRIDE:-}" ]; then
    src_profile_path="$SX_PROFILE_SOURCE_PATH_OVERRIDE"
  fi
  if [ -n "${SX_PROFILE_LABEL_OVERRIDE:-}" ]; then
    src_label="$SX_PROFILE_LABEL_OVERRIDE"
  fi
  if [ -n "${SX_PROFILE_SOURCE_ID_OVERRIDE:-}" ]; then
    source_id="$(sx_pa_sanitize_id "$SX_PROFILE_SOURCE_ID_OVERRIDE")"
  fi

  local db_template
  db_template="${SX_DB_PATH_TEMPLATE:-}"
  if [ -z "$db_template" ]; then
    db_template='data/sx_obsidian_{source_id}.db'
  fi
  local db_path
  db_path="$(printf '%s' "$db_template" | sed "s/{source_id}/$source_id/g")"

  # Resolve vault context for awareness (plugin install/build targeting visibility).
  local vault_target="${OBSIDIAN_VAULT_PATH:-}"
  if [ -n "${SX_PROFILE_VAULT_OVERRIDE:-}" ]; then
    vault_target="$SX_PROFILE_VAULT_OVERRIDE"
  fi
  if [ -z "$vault_target" ]; then
    local sx_profile_key="${SX_PROFILE:-default}"
    local vault_key="VAULT_${sx_profile_key}"
    vault_target="$(sx_pa_val "$vault_key")"
    if [ -z "$vault_target" ]; then
      vault_target="${VAULT_default:-}"
    fi
  fi

  # Resolve optional pipeline PostgreSQL profile mapping for this source profile.
  local aliases local_alias session_alias trans_alias
  aliases="$(sx_pa_profile_db_aliases_by_index "$idx")"
  IFS='|' read -r local_alias session_alias trans_alias <<<"$aliases"

  local sql_db_path
  sql_db_path="$(sx_pa_profile_sql_db_path_by_index "$idx")"

  local mode selected_alias db_profile_key
  mode="${SX_PIPELINE_DB_MODE:-LOCAL}"
  mode="$(printf '%s' "$mode" | tr '[:lower:]' '[:upper:]')"
  selected_alias="${SX_PIPELINE_DB_PROFILE:-}"

  if [ -z "$selected_alias" ]; then
    case "$mode" in
      SQL | SQLITE) selected_alias="" ;;
      SESSION) selected_alias="$session_alias" ;;
      TRANS | TRANSACTION) selected_alias="$trans_alias" ;;
      *) selected_alias="$local_alias" ;;
    esac
  fi

  if [ "$mode" = "SQL" ] || [ "$mode" = "SQLITE" ]; then
    if [ -n "$sql_db_path" ]; then
      db_path="$sql_db_path"
    fi
  fi

  if [ -z "$selected_alias" ]; then
    db_profile_key="${DB_PROFILE:-}"
    if [ -n "$db_profile_key" ]; then
      selected_alias="$db_profile_key"
    fi
  fi

  local pipeline_db_url pipeline_db_url_redacted
  pipeline_db_url="$(sx_pa_db_url_from_alias "$selected_alias")"
  if [ -z "$pipeline_db_url" ]; then
    pipeline_db_url="${DATABASE_URL:-}"
  fi
  pipeline_db_url_redacted="$(sx_pa_redact_url "$pipeline_db_url")"

  export SX_PA_SOURCE_ID="$source_id"
  export SX_PA_SOURCE_LABEL="$src_label"
  export SX_PA_SOURCE_PATH="$src_profile_path"
  export SX_PA_DB_PATH="$db_path"
  export SX_PA_VAULT_PATH="$vault_target"

  export SX_PA_PIPELINE_DB_LOCAL_PROFILE="$local_alias"
  export SX_PA_PIPELINE_DB_SESSION_PROFILE="$session_alias"
  export SX_PA_PIPELINE_DB_TRANS_PROFILE="$trans_alias"
  export SX_PA_PIPELINE_DB_SQL_PATH="$sql_db_path"
  export SX_PA_PIPELINE_DB_SELECTED_PROFILE="$selected_alias"
  export SX_PA_PIPELINE_DB_URL="$pipeline_db_url"
  export SX_PA_PIPELINE_DB_URL_REDACTED="$pipeline_db_url_redacted"

  export SX_DEFAULT_SOURCE_ID="$SX_PA_SOURCE_ID"
  export SX_DB_PATH="$SX_PA_DB_PATH"
}

sx_profile_apply() {
  sx_pa_ctx_init
}

sx_profile_print_context() {
  local action="${1:-action}"
  if [ "${SXCTL_DEBUG:-0}" != "1" ] && [ "${SXCTL_VERBOSE:-0}" != "1" ] && [ "${SX_PROFILE_DEBUG:-0}" != "1" ]; then
    return 0
  fi
  sx_pa_ctx_init

  printf "\n"
  printf "[sx_profile] action=%s\n" "$action"
  printf "[sx_profile] scheduler_env=%s\n" "${SX_SCHEDULERX_ENV:-unset}"
  printf "[sx_profile] profile_index=%s\n" "${SX_PROFILE_INDEX:-1}"
  printf "[sx_profile] source_label=%s\n" "${SX_PA_SOURCE_LABEL:-profile}"
  printf "[sx_profile] source_path=%s\n" "${SX_PA_SOURCE_PATH:-unset}"
  printf "[sx_profile] source_id=%s\n" "${SX_PA_SOURCE_ID:-default}"
  printf "[sx_profile] sx_db_path=%s\n" "${SX_PA_DB_PATH:-data/sx_obsidian.db}"
  printf "[sx_profile] vault_target=%s\n" "${SX_PA_VAULT_PATH:-unset}"
  printf "[sx_profile] pipeline_db_profile=%s\n" "${SX_PA_PIPELINE_DB_SELECTED_PROFILE:-unset}"
  printf "[sx_profile] pipeline_db_mode=%s\n" "${SX_PIPELINE_DB_MODE:-LOCAL}"
  printf "[sx_profile] sql_db_path=%s\n" "${SX_PA_PIPELINE_DB_SQL_PATH:-unset}"
  printf "[sx_profile] pipeline_db_url=%s\n" "${SX_PA_PIPELINE_DB_URL_REDACTED:-unset}"
  printf "\n"
}
