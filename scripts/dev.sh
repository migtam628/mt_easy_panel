#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -f .env ]; then echo 'Run bash scripts/init-env.sh first.' >&2; exit 1; fi
set -a
# shellcheck disable=SC1091
source .env
set +a
case "${AGENT_BIND:-127.0.0.1}" in 127.0.0.1|localhost|::1) ;; *) echo 'Refusing to expose the agent outside loopback in pilot mode.' >&2; exit 1;; esac
case "${PANEL_BIND:-127.0.0.1}" in 127.0.0.1|localhost|::1) ;; *) echo 'Refusing to expose the control plane outside loopback in pilot mode.' >&2; exit 1;; esac
# Prefer this repository's Python, even if Anaconda base is active.
if [ -x "./.venv/bin/python3" ]; then
  PYTHON="./.venv/bin/python3"
else
  PYTHON="$(command -v python3 || true)"
fi
if [ -z "$PYTHON" ] || ! "$PYTHON" -c 'import uvicorn' 2>/dev/null; then
  echo 'Python environment missing uvicorn. Run: python3 -m venv .venv && .venv/bin/python3 -m pip install -r requirements.txt' >&2
  exit 1
fi
AGENT_PID=''
cleanup(){ if [ -n "$AGENT_PID" ]; then kill "$AGENT_PID" 2>/dev/null || true; fi; }
trap cleanup EXIT INT TERM
"$PYTHON" -m uvicorn --factory agent.api:app_factory --host "${AGENT_BIND:-127.0.0.1}" --port "${AGENT_PORT:-8788}" &
AGENT_PID=$!
echo "Agent on ${AGENT_BIND:-127.0.0.1}:${AGENT_PORT:-8788}; dashboard on ${PANEL_BIND:-127.0.0.1}:${PANEL_PORT:-8086}"
"$PYTHON" -m uvicorn --factory panel.api:app_factory --host "${PANEL_BIND:-127.0.0.1}" --port "${PANEL_PORT:-8086}"
