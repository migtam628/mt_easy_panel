#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ -x ./.venv/bin/python3 ]; then
  PYTHON=./.venv/bin/python3
else
  PYTHON="$(command -v python3)"
fi
"$PYTHON" -m pytest -q
