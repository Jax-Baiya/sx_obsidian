#!/usr/bin/env bash
set -euo pipefail

# Installs the built plugin into an Obsidian vault.
# Requires OBSIDIAN_VAULT_PATH (Windows path or WSL path).

cd "$(dirname "$0")/.."

if [ -z "${OBSIDIAN_VAULT_PATH:-}" ]; then
  echo "Missing OBSIDIAN_VAULT_PATH. Example:" >&2
  echo "  export OBSIDIAN_VAULT_PATH=\"/mnt/t/AlexNova\"" >&2
  exit 1
fi

PLUGIN_ID="sx-obsidian-db"
TARGET="$OBSIDIAN_VAULT_PATH/.obsidian/plugins/$PLUGIN_ID"

mkdir -p "$TARGET"
cp -f obsidian-plugin/manifest.json "$TARGET/manifest.json"
cp -f obsidian-plugin/main.js "$TARGET/main.js"
cp -f obsidian-plugin/styles.css "$TARGET/styles.css"

echo "✅ Installed plugin to: $TARGET"
