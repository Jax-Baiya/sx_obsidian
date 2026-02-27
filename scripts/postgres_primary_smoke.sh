#!/usr/bin/env bash
set -euo pipefail

# Smoke checks for POSTGRES_PRIMARY runtime.
#
# Usage:
#   ./scripts/postgres_primary_smoke.sh \
#     --base-url http://127.0.0.1:8123 \
#     --source-id assets_1

BASE_URL="http://127.0.0.1:8123"
SOURCE_ID=""
BAD_SOURCE_ID="__missing_schema__"
EXPECT_BAD_SOURCE_400="1"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --base-url)
      BASE_URL="$2"
      shift 2
      ;;
    --source-id)
      SOURCE_ID="$2"
      shift 2
      ;;
    --bad-source-id)
      BAD_SOURCE_ID="$2"
      shift 2
      ;;
    --expect-bad-source-400)
      EXPECT_BAD_SOURCE_400="$2"
      shift 2
      ;;
    *)
      echo "Unknown arg: $1" >&2
      exit 2
      ;;
  esac
done

if [[ -z "${SOURCE_ID}" ]]; then
  echo "Missing required --source-id" >&2
  exit 2
fi

fail() {
  echo "[FAIL] $1" >&2
  exit 1
}

pass() {
  echo "[PASS] $1"
}

json_get() {
  local key="$1"
  python3 -c '
import json,sys
key=sys.argv[1]
obj=json.load(sys.stdin)
cur=obj
for part in key.split("."):
  if not part:
    continue
  if isinstance(cur, dict) and part in cur:
    cur=cur[part]
  else:
    print("")
    raise SystemExit(0)
print("" if cur is None else cur)
' "$key"
}

echo "Running Postgres-primary smoke checks against ${BASE_URL} (source=${SOURCE_ID})"

# 1) /health must be reachable
health="$(curl -fsS "${BASE_URL}/health")" || fail "/health unreachable"
ok="$(printf '%s' "$health" | json_get ok)"
[[ "$ok" == "True" || "$ok" == "true" ]] || fail "/health ok=false"
pass "/health reachable"

# 2) backend should report postgres_primary
backend="$(printf '%s' "$health" | json_get backend.backend)"
[[ "$backend" == "postgres_primary" ]] || fail "backend.backend=${backend}, expected postgres_primary"
pass "backend is postgres_primary"

# 3) source header override should stick
header_source_resp="$(curl -fsS -H "X-SX-Source-ID: ${SOURCE_ID}" "${BASE_URL}/health")" || fail "/health with header failed"
resp_source="$(printf '%s' "$header_source_resp" | json_get source_id)"
[[ "$resp_source" == "$SOURCE_ID" ]] || fail "header source mismatch: got=${resp_source} expected=${SOURCE_ID}"
pass "header source routing works"

# 4) source query param should also stick
query_source_resp="$(curl -fsS "${BASE_URL}/health?source_id=${SOURCE_ID}")" || fail "/health with query source failed"
resp_source_q="$(printf '%s' "$query_source_resp" | json_get source_id)"
[[ "$resp_source_q" == "$SOURCE_ID" ]] || fail "query source mismatch: got=${resp_source_q} expected=${SOURCE_ID}"
pass "query source routing works"

# 5) list items endpoint should answer with the selected source context
items_status="$(curl -sS -o /tmp/sx_items_smoke.json -w "%{http_code}" -H "X-SX-Source-ID: ${SOURCE_ID}" "${BASE_URL}/items?limit=1")"
[[ "$items_status" == "200" ]] || fail "/items returned status ${items_status}"
pass "/items responds for selected source"

# 6) bad source should fail with 400 (strict mapping) unless disabled by flag
if [[ "${EXPECT_BAD_SOURCE_400}" == "1" ]]; then
  bad_status="$(curl -sS -o /tmp/sx_bad_source_smoke.json -w "%{http_code}" -H "X-SX-Source-ID: ${BAD_SOURCE_ID}" "${BASE_URL}/health")"
  [[ "$bad_status" == "400" ]] || fail "bad source expected 400, got ${bad_status}"
  pass "bad source rejected with 400"
fi

echo "All Postgres-primary smoke checks passed."
