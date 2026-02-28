#!/usr/bin/env bash
# SX Obsidian DB Layer Generator - Deployment Script

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "--- SX Generator Deployment ---"

INSTALL_DEV=0
for arg in "$@"; do
    case "$arg" in
        --dev | --with-dev)
            INSTALL_DEV=1
            ;;
        *) ;;
    esac
done

# 1. Environment Check
PYTHON_BIN=""
if command -v python &>/dev/null; then
  PYTHON_BIN="python"
elif command -v python3 &>/dev/null; then
  PYTHON_BIN="python3"
else
  echo "Error: Python is not installed or not on PATH." >&2
  echo "In GitHub Actions, ensure actions/setup-python ran successfully." >&2
  exit 1
fi

# 2. Windows Metadata Cleanup (Optional but recommended for WSL)
echo "Cleaning up Windows metadata files (*:Zone.Identifier)..."
find . -name "*:Zone.Identifier" -delete 2>/dev/null || true

# 3. Venv Setup
VENV_DIR=".venv"
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment in $VENV_DIR..."
    "$PYTHON_BIN" -m venv "$VENV_DIR"
else
    echo "Virtual environment already exists."
fi

# 3. Install Dependencies
echo "Installing dependencies..."
# Using the full path to the venv python to ensure it installs in the right place
"$VENV_DIR/bin/python" -m pip install --upgrade pip

if [ -f "requirements.txt" ]; then
    "$VENV_DIR/bin/python" -m pip install -r requirements.txt
else
    # Backward-compatible fallback
    "$VENV_DIR/bin/python" -m pip install pandas pyyaml tqdm python-dotenv
fi

if [ "$INSTALL_DEV" -eq 1 ]; then
    if [ -f "requirements-dev.txt" ]; then
        echo "Installing dev dependencies (requirements-dev.txt)..."
        "$VENV_DIR/bin/python" -m pip install -r requirements-dev.txt
    else
        echo "Warning: --dev requested but requirements-dev.txt not found; skipping dev deps." >&2
    fi
fi

echo "--- Deployment Complete ---"
echo "You can now use ./scripts/run.sh to execute the generator."
