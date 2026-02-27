#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
# install_alias.sh — One-command alias for sx_db CLI
#
# Usage:  bash scripts/install_alias.sh
# Effect: Adds 'sxdb' alias to ~/.bash_aliases (or ~/.bashrc)
#         so you can run: sxdb status, sxdb find "query", etc.
# ──────────────────────────────────────────────────────────────
set -euo pipefail

# Resolve the project root (parent of this script)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Managed block markers
BLOCK_BEGIN="# >>> sx_db CLI (managed by install_alias.sh) >>>"
BLOCK_END="# <<< sx_db CLI (managed by install_alias.sh) <<<"

# Use a shell function so `sxdb` works from any directory.
# Run in a subshell to preserve the caller's working directory.
read -r -d '' MANAGED_BLOCK <<EOF || true
${BLOCK_BEGIN}
sxdb() {
    (cd "${SCRIPT_DIR}" && "${SCRIPT_DIR}/.venv/bin/python" -m sx_db "\$@")
}
export -f sxdb 2>/dev/null || true
${BLOCK_END}
EOF

# Choose target file
if [[ -f "${HOME}/.bash_aliases" ]]; then
    TARGET="${HOME}/.bash_aliases"
else
    TARGET="${HOME}/.bashrc"
fi

touch "${TARGET}"

print_syntax_diagnostics() {
    local phase="$1"
    local err=""
    if err="$(bash -n "${TARGET}" 2>&1)"; then
        return 0
    fi

    echo "⚠ Detected shell syntax issue in ${TARGET} (${phase})."
    echo "  ${err}"

    # Try to show context around the reported line number.
    local line
    line="$(printf '%s' "${err}" | sed -n 's/.*line \([0-9][0-9]*\).*/\1/p' | head -n1)"
    if [[ -n "${line}" ]]; then
        local start=$(( line > 2 ? line - 2 : 1 ))
        local end=$(( line + 2 ))
        echo "  Context (${start}-${end}):"
        nl -ba "${TARGET}" | sed -n "${start},${end}p"
    fi
    echo
    return 1
}

print_syntax_diagnostics "before update" || true

# Remove old managed block (if present)
if grep -qF "${BLOCK_BEGIN}" "${TARGET}" 2>/dev/null; then
    tmpfile="$(mktemp)"
    awk -v b="${BLOCK_BEGIN}" -v e="${BLOCK_END}" '
        $0==b {skip=1; next}
        $0==e {skip=0; next}
        !skip {print}
    ' "${TARGET}" > "${tmpfile}"
    mv "${tmpfile}" "${TARGET}"
fi

# Remove legacy one-line alias if present
if grep -qE "^[[:space:]]*alias[[:space:]]+sxdb=" "${TARGET}" 2>/dev/null; then
    tmpfile="$(mktemp)"
    grep -Ev "^[[:space:]]*alias[[:space:]]+sxdb=" "${TARGET}" > "${tmpfile}" || true
    mv "${tmpfile}" "${TARGET}"
fi

# Append managed block
{
    echo ""
    echo "${MANAGED_BLOCK}"
} >> "${TARGET}"

print_syntax_diagnostics "after update" || true

echo "✓ Command 'sxdb' installed/updated in ${TARGET}"
echo ""
echo "  To activate now: source ${TARGET}"
echo "  Then run:        sxdb --help"
echo ""
echo "  Quick commands:"
echo "    sxdb              → Interactive TUI"
echo "    sxdb status       → Database stats"
echo "    sxdb find \"query\" → Search library"
echo "    sxdb run          → Start API server"
echo "    sxdb setup        → First-time wizard"
