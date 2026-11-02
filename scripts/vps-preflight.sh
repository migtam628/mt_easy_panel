#!/usr/bin/env bash
# VPS checks only. This script never installs, restarts, or modifies services.
set -euo pipefail

if [[ "${1:---check}" != "--check" ]]; then
  echo "Usage: bash scripts/vps-preflight.sh --check" >&2
  exit 2
fi

echo "MT Panel VPS preflight (read-only)"
if [[ "$(uname -s)" != "Linux" ]]; then
  echo "FAIL: This preflight targets a Linux VPS." >&2
  exit 1
fi
if ! command -v python3 >/dev/null 2>&1; then
  echo "FAIL: Python 3 is missing." >&2
  exit 1
fi
python3 -c 'import sys; print("Python:", sys.version.split()[0]); sys.exit(0 if sys.version_info >= (3,11) else 1)' || {
  echo "FAIL: Python 3.11+ is required." >&2; exit 1;
}
for command in git tar systemctl ss; do
  if ! command -v "$command" >/dev/null 2>&1; then
    echo "FAIL: Missing command: $command" >&2
    exit 1
  fi
done

if ! python3 -m venv --help >/dev/null 2>&1; then
  echo "FAIL: python3-venv is unavailable." >&2
  exit 1
fi
if ! command -v docker >/dev/null 2>&1; then
  echo "FAIL: Docker CLI is unavailable." >&2
  exit 1
fi
docker --version
if ! docker info --format 'Docker server: {{.ServerVersion}}' 2>/dev/null; then
  echo "FAIL: Docker Engine is not responding." >&2
  exit 1
fi
if [[ ! -S /var/run/docker.sock ]]; then
  echo "FAIL: /var/run/docker.sock is not a Unix socket." >&2
  exit 1
fi
socket_group="$(stat -c '%G' /var/run/docker.sock)"
echo "Docker socket group: $socket_group"
if [[ "$socket_group" != "docker" ]] || ! getent group docker >/dev/null; then
  echo "FAIL: Installation requires a docker-group owned Unix socket; do not change Docker permissions automatically." >&2
  exit 1
fi

# The installer never takes over HTTP/HTTPS ports. Report them for awareness.
echo "Existing listeners on 80/443 (will not be touched):"
ss -lnt | grep -E ':(80|443)[[:space:]]' || true
for port in 8086 8788; do
  if ss -H -lnt | awk '{print $4}' | grep -Eq ":$port$"; then
    echo "FAIL: Port $port already has a listener. Stop only the conflicting instance after reviewing it." >&2
    exit 1
  fi
  echo "Port $port: no listener detected"
done
if [[ -e /opt/mt-panel || -e /etc/mt-panel/mt-panel.env ||
      -e /etc/systemd/system/mt-panel.service ||
      -e /etc/systemd/system/mt-panel-agent.service ]]; then
  echo "FAIL: A systemd MT Panel installation already exists; this first-install script will not overwrite it." >&2
  exit 1
fi
if id mtpanel >/dev/null 2>&1 || id mtpanel-agent >/dev/null 2>&1; then
  echo "FAIL: mtpanel or mtpanel-agent system users already exist; manual review required." >&2
  exit 1
fi
echo "PASS: First-install preflight complete. No system changes made."
