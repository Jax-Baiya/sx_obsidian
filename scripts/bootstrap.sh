#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

echo "[sx_obsidian] Bootstrapping Python environment..."
./scripts/deploy.sh --dev

echo "[sx_obsidian] Bootstrapping Obsidian plugin (npm install)..."
if command -v npm >/dev/null 2>&1; then
  pushd obsidian-plugin >/dev/null
  npm install
  popd >/dev/null
else
  echo "npm not found; skipping plugin bootstrap" >&2
fi

echo "✅ Bootstrap complete"
