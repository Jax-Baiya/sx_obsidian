#!/bin/bash
# SX Obsidian DB Layer Generator - Runner Script

VENV_DIR=".venv"

print_venv_diagnostics() {
    echo "--- SX venv diagnostics ---" >&2
    echo "CWD: $(pwd)" >&2
    echo "VENV_DIR: $VENV_DIR" >&2

    if [ -d "$VENV_DIR" ]; then
        echo "Contents: $VENV_DIR/bin" >&2
        ls -la "$VENV_DIR/bin" 2>/dev/null | sed -n '1,120p' >&2 || true

        if [ -f "$VENV_DIR/pyvenv.cfg" ]; then
            echo "\n$VENV_DIR/pyvenv.cfg:" >&2
            sed -n '1,120p' "$VENV_DIR/pyvenv.cfg" >&2 || true
        fi
    else
        echo "(missing) $VENV_DIR" >&2
    fi

    echo "\nFix: rm -rf $VENV_DIR && ./deploy.sh" >&2
}

if [ ! -d "$VENV_DIR" ]; then
    echo "Error: Virtual environment not found. Please run ./deploy.sh first."
    exit 1
fi

# Prefer python3, fall back to python.
PY="$VENV_DIR/bin/python3"
if [ -x "$PY" ]; then
    :
elif [ -L "$PY" ] && [ ! -e "$PY" ]; then
    echo "Error: $PY is a broken symlink." >&2
    print_venv_diagnostics
    exit 1
else
    PY="$VENV_DIR/bin/python"
    if [ -x "$PY" ]; then
        :
    elif [ -L "$PY" ] && [ ! -e "$PY" ]; then
        echo "Error: $PY is a broken symlink." >&2
        print_venv_diagnostics
        exit 1
    else
        echo "Error: Could not find an executable Python interpreter in $VENV_DIR/bin" >&2
        echo "Tried: $VENV_DIR/bin/python3, $VENV_DIR/bin/python" >&2
        print_venv_diagnostics
        exit 1
    fi
fi

# Print SX System Info
if [[ "$*" == *"--help"* ]]; then
    echo "SX Obsidian Media Control - Senior Edition"
    echo "Documentation: docs/ENVIRONMENT.md, docs/PROFILES.md, docs/SCHEMA_GUIDE.md"
    echo "-------------------------------------------"
fi

# Execute the generator via the package entrypoint.
# This avoids relying on a root-level generator.py and keeps layout clean.
"./$PY" -m sx "$@"
