#!/usr/bin/env bats

REPO_ROOT=""
CONTEXT_FILE=""
CONTEXT_JSON=""

setup() {
  if [ -z "$REPO_ROOT" ]; then
    local test_dir="${BATS_TEST_DIRNAME:-}"
    if [ -z "$test_dir" ] && [ -n "${BATS_TEST_FILENAME:-}" ]; then
      test_dir="$(cd "$(dirname "${BATS_TEST_FILENAME}")" && pwd)"
    fi
    if [ -z "$test_dir" ]; then
      test_dir="$(cd "$(dirname "$0")" && pwd)"
    fi
    REPO_ROOT="$(cd "$test_dir/../.." && pwd)"
    CONTEXT_FILE="$REPO_ROOT/.sxctl/context.env"
    CONTEXT_JSON="$REPO_ROOT/.sxctl/context.json"
  fi

  mkdir -p "$REPO_ROOT/.sxctl"
  mkdir -p "$REPO_ROOT/_logs"

  BACKUP_CONTEXT=""
  BACKUP_CONTEXT_JSON=""
  if [ -f "$CONTEXT_FILE" ]; then
    BACKUP_CONTEXT="$(mktemp)"
    cp "$CONTEXT_FILE" "$BACKUP_CONTEXT"
  fi
  if [ -f "$CONTEXT_JSON" ]; then
    BACKUP_CONTEXT_JSON="$(mktemp)"
    cp "$CONTEXT_JSON" "$BACKUP_CONTEXT_JSON"
  fi

  TEST_VAULT="$(mktemp -d)"
  mkdir -p "$TEST_VAULT/.obsidian"
}

teardown() {
  rm -rf "$TEST_VAULT"

  if [ -n "$BACKUP_CONTEXT" ] && [ -f "$BACKUP_CONTEXT" ]; then
    cp "$BACKUP_CONTEXT" "$CONTEXT_FILE"
    rm -f "$BACKUP_CONTEXT"
  else
    rm -f "$CONTEXT_FILE"
  fi

  if [ -n "$BACKUP_CONTEXT_JSON" ] && [ -f "$BACKUP_CONTEXT_JSON" ]; then
    cp "$BACKUP_CONTEXT_JSON" "$CONTEXT_JSON"
    rm -f "$BACKUP_CONTEXT_JSON"
  else
    rm -f "$CONTEXT_JSON"
  fi
}

@test "profile adapter respects explicit SX_PROFILE_INDEX" {
  run bash -lc "cd '$REPO_ROOT' && source ./scripts/profile_adapter.sh && export SX_PROFILE_INDEX=2 && sx_profile_apply && echo \"IDX=\$SX_PROFILE_INDEX SID=\$SX_PA_SOURCE_ID\""
  [ "$status" -eq 0 ]
  [[ "$output" == *"IDX=2 SID=assets_2"* ]]
}

@test "noninteractive context init writes sqlite context" {
  run env \
    SXCTL_NONINTERACTIVE=1 \
    SXCTL_PROFILE_INDEX=2 \
    SXCTL_VAULT_ROOT="$TEST_VAULT" \
    SXCTL_DB_BACKEND=sqlite \
    bash -lc "cd '$REPO_ROOT' && ./scripts/sxctl.sh context init"

  [ "$status" -eq 0 ]

  run bash -lc "grep -E '^SXCTL_PROFILE_INDEX=2$' '$CONTEXT_FILE'"
  [ "$status" -eq 0 ]

  run bash -lc "grep -E '^SXCTL_DB_BACKEND=sqlite$' '$CONTEXT_FILE'"
  [ "$status" -eq 0 ]

  run bash -lc "grep -E '^SXCTL_DB_PATH=data/sx_obsidian_assets_2.db$' '$CONTEXT_FILE'"
  [ "$status" -eq 0 ]
}

@test "noninteractive invalid vault fails cleanly" {
  run env \
    SXCTL_NONINTERACTIVE=1 \
    SXCTL_PROFILE_INDEX=1 \
    SXCTL_VAULT_ROOT=/definitely/invalid/vault \
    SXCTL_DB_BACKEND=sqlite \
    bash -lc "cd '$REPO_ROOT' && ./scripts/sxctl.sh context init"

  [ "$status" -eq 1 ]
  [[ "$output" == *"Invalid vault root"* ]]
  [[ "$output" == *"path does not exist"* ]]
}

@test "noninteractive postgres context captures db profile" {
  run env \
    SXCTL_NONINTERACTIVE=1 \
    SXCTL_PROFILE_INDEX=3 \
    SXCTL_VAULT_ROOT="$TEST_VAULT" \
    SXCTL_DB_BACKEND=postgres \
    SXCTL_DB_PROFILE=LOCAL_3 \
    LOCAL_3_DB_USER=test \
    LOCAL_3_DB_PASSWORD=test \
    LOCAL_3_DB_HOST=localhost \
    LOCAL_3_DB_PORT=5432 \
    LOCAL_3_DB_NAME=sx_obsidian_test \
    bash -lc "cd '$REPO_ROOT' && ./scripts/sxctl.sh context init"

  [ "$status" -eq 0 ]

  run bash -lc "grep -E '^SXCTL_DB_BACKEND=postgres$' '$CONTEXT_FILE'"
  [ "$status" -eq 0 ]

  run bash -lc "grep -E '^SXCTL_PIPELINE_DB_PROFILE=LOCAL_3$' '$CONTEXT_FILE'"
  [ "$status" -eq 0 ]

  run bash -lc "grep -E '^SXCTL_PIPELINE_DB_MODE=LOCAL$' '$CONTEXT_FILE'"
  [ "$status" -eq 0 ]
}

@test "noninteractive aliases map to sxctl vars" {
  run env \
    SXCTL_NONINTERACTIVE=1 \
    PROFILE_INDEX=2 \
    VAULT_ROOT="$TEST_VAULT" \
    DB_BACKEND=sqlite \
    bash -lc "cd '$REPO_ROOT' && ./scripts/sxctl.sh context init"

  [ "$status" -eq 0 ]

  run bash -lc "grep -E '^SXCTL_PROFILE_INDEX=2$' '$CONTEXT_FILE'"
  [ "$status" -eq 0 ]

  run bash -lc "awk -F= '/^SXCTL_VAULT_ROOT=/{print substr(\$0, index(\$0,\"=\")+1)}' '$CONTEXT_FILE'"
  [ "$status" -eq 0 ]
  [ "$output" = "$TEST_VAULT" ]
}

@test "context init writes json snapshot" {
  run env \
    SXCTL_NONINTERACTIVE=1 \
    SXCTL_PROFILE_INDEX=1 \
    SXCTL_VAULT_ROOT="$TEST_VAULT" \
    SXCTL_DB_BACKEND=sqlite \
    bash -lc "cd '$REPO_ROOT' && ./scripts/sxctl.sh context init"

  [ "$status" -eq 0 ]

  run bash -lc "test -f '$CONTEXT_JSON'"
  [ "$status" -eq 0 ]

  run bash -lc "python - <<'PY'
import json
f='${CONTEXT_JSON}'
d=json.load(open(f,"r",encoding="utf-8"))
assert str(d.get("SXCTL_PROFILE_INDEX"))=="1"
assert str(d.get("SXCTL_DB_BACKEND"))=="sqlite"
print("ok")
PY"
  [ "$status" -eq 0 ]
  [[ "$output" == *"ok"* ]]
}
