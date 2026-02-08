#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

./.venv/bin/python -m sx_db init
./.venv/bin/python -m sx_db import-csv
