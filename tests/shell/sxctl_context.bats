#!/usr/bin/env bats

REPO_ROOT="/home/An_Xing/projects/ANA/core/portfolio/sx_obsidian"
CONTEXT_FILE="$REPO_ROOT/.sxctl/context.env"
CONTEXT_JSON="$REPO_ROOT/.sxctl/context.json"

setup() {
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
  run bash -lc 'cd /home/An_Xing/projects/ANA/core/portfolio/sx_obsidian && source ./scripts/profile_adapter.sh && export SX_PROFILE_INDEX=2 && sx_profile_apply && echo "IDX=$SX_PROFILE_INDEX SID=$SX_PA_SOURCE_ID"'
  [ "$status" -eq 0 ]
  [[ "$output" == *"IDX=2 SID=assets_2"* ]]
}

@test "noninteractive context init writes sqlite context" {
  run env \
    SXCTL_NONINTERACTIVE=1 \
    SXCTL_PROFILE_INDEX=2 \
    SXCTL_VAULT_ROOT="$TEST_VAULT" \
    SXCTL_DB_BACKEND=sqlite \
    bash -lc 'cd /home/An_Xing/projects/ANA/core/portfolio/sx_obsidian && ./sxctl.sh context init'

  [ "$status" -eq 0 ]

  run bash -lc 'grep -E "^SXCTL_PROFILE_INDEX=2$" /home/An_Xing/projects/ANA/core/portfolio/sx_obsidian/.sxctl/context.env'
  [ "$status" -eq 0 ]

  run bash -lc 'grep -E "^SXCTL_DB_BACKEND=sqlite$" /home/An_Xing/projects/ANA/core/portfolio/sx_obsidian/.sxctl/context.env'
  [ "$status" -eq 0 ]

  run bash -lc 'grep -E "^SXCTL_DB_PATH=data/sx_obsidian_assets_2.db$" /home/An_Xing/projects/ANA/core/portfolio/sx_obsidian/.sxctl/context.env'
  [ "$status" -eq 0 ]
}

@test "noninteractive invalid vault fails cleanly" {
  run env \
    SXCTL_NONINTERACTIVE=1 \
    SXCTL_PROFILE_INDEX=1 \
    SXCTL_VAULT_ROOT=/definitely/invalid/vault \
    SXCTL_DB_BACKEND=sqlite \
    bash -lc 'cd /home/An_Xing/projects/ANA/core/portfolio/sx_obsidian && ./sxctl.sh context init'

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
    bash -lc 'cd /home/An_Xing/projects/ANA/core/portfolio/sx_obsidian && ./sxctl.sh context init'

  [ "$status" -eq 0 ]

  run bash -lc 'grep -E "^SXCTL_DB_BACKEND=postgres$" /home/An_Xing/projects/ANA/core/portfolio/sx_obsidian/.sxctl/context.env'
  [ "$status" -eq 0 ]

  run bash -lc 'grep -E "^SXCTL_PIPELINE_DB_PROFILE=LOCAL_3$" /home/An_Xing/projects/ANA/core/portfolio/sx_obsidian/.sxctl/context.env'
  [ "$status" -eq 0 ]

  run bash -lc 'grep -E "^SXCTL_PIPELINE_DB_MODE=LOCAL$" /home/An_Xing/projects/ANA/core/portfolio/sx_obsidian/.sxctl/context.env'
  [ "$status" -eq 0 ]
}

@test "noninteractive aliases map to sxctl vars" {
  run env \
    SXCTL_NONINTERACTIVE=1 \
    PROFILE_INDEX=2 \
    VAULT_ROOT="$TEST_VAULT" \
    DB_BACKEND=sqlite \
    bash -lc 'cd /home/An_Xing/projects/ANA/core/portfolio/sx_obsidian && ./sxctl.sh context init'

  [ "$status" -eq 0 ]

  run bash -lc 'grep -E "^SXCTL_PROFILE_INDEX=2$" /home/An_Xing/projects/ANA/core/portfolio/sx_obsidian/.sxctl/context.env'
  [ "$status" -eq 0 ]

  run bash -lc 'awk -F= "/^SXCTL_VAULT_ROOT=/{print substr(\$0, index(\$0,\"=\")+1)}" /home/An_Xing/projects/ANA/core/portfolio/sx_obsidian/.sxctl/context.env'
  [ "$status" -eq 0 ]
  [ "$output" = "$TEST_VAULT" ]
}

@test "context init writes json snapshot" {
  run env \
    SXCTL_NONINTERACTIVE=1 \
    SXCTL_PROFILE_INDEX=1 \
    SXCTL_VAULT_ROOT="$TEST_VAULT" \
    SXCTL_DB_BACKEND=sqlite \
    bash -lc 'cd /home/An_Xing/projects/ANA/core/portfolio/sx_obsidian && ./sxctl.sh context init'

  [ "$status" -eq 0 ]

  run bash -lc 'test -f /home/An_Xing/projects/ANA/core/portfolio/sx_obsidian/.sxctl/context.json'
  [ "$status" -eq 0 ]

  run bash -lc 'python3 - <<"PY"
import json
f="/home/An_Xing/projects/ANA/core/portfolio/sx_obsidian/.sxctl/context.json"
d=json.load(open(f,"r",encoding="utf-8"))
assert str(d.get("SXCTL_PROFILE_INDEX"))=="1"
assert str(d.get("SXCTL_DB_BACKEND"))=="sqlite"
print("ok")
PY'
  [ "$status" -eq 0 ]
  [[ "$output" == *"ok"* ]]
}
