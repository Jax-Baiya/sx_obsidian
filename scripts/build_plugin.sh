#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../obsidian-plugin"

npm install
npm run build
