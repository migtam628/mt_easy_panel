#!/usr/bin/env bash
# Explicit first-time installation only. Does not start/stop Docker, proxies, or MT Panel.
set -euo pipefail
cd "$(dirname "$0")/.."
SRC="$(pwd -P)"

usage() {
  cat <<'HELP'
MT Panel read-only VPS pilot installer
  bash scripts/install-vps.sh --check     # No changes, safe to run anytime
  sudo bash scripts/install-vps.sh --install  # Explicit opt-in to first installation
The installer will not start or enable the MT Panel services.
It will never alter Docker containers, proxy configuration or ports 80/443.
HELP
}

case "${1:---help}" in
  --help|-h) usage; exit 0 ;;
  --check) exec bash "$SRC/scripts/vps-preflight.sh" --check ;;
  --install) ;;
  *) usage >&2; exit 2 ;;
esac

if [[ "$EUID" -ne 0 ]]; then
  echo "FAIL: --install requires root. The read-only --check does not." >&2
  exit 1
fi

bash "$SRC/scripts/vps-preflight.sh" --check
for command in useradd runuser install; do
  command -v "$command" >/dev/null || { echo "Missing command: $command" >&2; exit 1; }
done
echo "Creating isolated MT Panel pilot installation."
echo "The source checkout and any Docker services will remain untouched."

# Install root-owned application code without copying secrets, local DB or the git checkout.
install -d -o root -g root -m 0755 /opt/mt-panel
tar -C "$SRC" -cf - \
  --exclude='./.git' --exclude='./.venv' --exclude='./.env*' \
  --exclude='./state' --exclude='*.db' --exclude='*.db-*' \
  --exclude='./__pycache__' --exclude='./.pytest_cache' \
  --exclude='*.pyc' --exclude='./.DS_Store' . | tar -C /opt/mt-panel -xf -
chown -R root:root /opt/mt-panel
python3 -m venv /opt/mt-panel/.venv
/opt/mt-panel/.venv/bin/python -m pip install -r /opt/mt-panel/requirements.txt
# Keep the application directory immutable to non-root processes.
chown -R root:root /opt/mt-panel
chmod -R go-w /opt/mt-panel

useradd --system --user-group --no-create-home --home-dir /nonexistent \
  --shell /usr/sbin/nologin mtpanel
useradd --system --user-group --no-create-home --home-dir /nonexistent \
  --shell /usr/sbin/nologin --groups docker mtpanel-agent
install -d -o mtpanel -g mtpanel -m 0700 /var/lib/mt-panel
install -d -o root -g root -m 0700 /etc/mt-panel
umask 077
token="$(python3 -c 'import secrets; print(secrets.token_hex(48))')"
cat > /etc/mt-panel/mt-panel.env <<ENVFILE
AGENT_TOKEN=$token
AGENT_BIND=127.0.0.1
AGENT_PORT=8788
AGENT_DEMO_MODE=false
DOCKER_SOCKET_PATH=/var/run/docker.sock
PANEL_BIND=127.0.0.1
PANEL_PORT=8086
PANEL_AGENT_URL=http://127.0.0.1:8788
PANEL_DB_PATH=/var/lib/mt-panel/panel.db
PANEL_PUBLIC_ORIGIN=http://127.0.0.1:8086
PANEL_COOKIE_SECURE=false
ENVFILE
unset token
chmod 0600 /etc/mt-panel/mt-panel.env

install -o root -g root -m 0644 \
  /opt/mt-panel/deployment/systemd/mt-panel.service \
  /etc/systemd/system/mt-panel.service
install -o root -g root -m 0644 \
  /opt/mt-panel/deployment/systemd/mt-panel-agent.service \
  /etc/systemd/system/mt-panel-agent.service
systemctl daemon-reload

echo
echo "INSTALLATION STAGED: No services have been enabled or started."
echo "1. Bootstrap the administrator from an interactive root terminal:"
echo "   cd /opt/mt-panel"
echo "   runuser -u mtpanel -- env PANEL_DB_PATH=/var/lib/mt-panel/panel.db /opt/mt-panel/.venv/bin/python -m panel.cli create-admin --username admin"
echo "2. Verify that the Docker agent account can read Docker (root-equivalent trust):"
echo "   runuser -u mtpanel-agent -- docker info --format '{{.ServerVersion}}'"
echo "3. When ready, explicitly enable the two new units:"
echo "   systemctl enable --now mt-panel-agent.service mt-panel.service"
echo "4. Check: curl -fsS http://127.0.0.1:8086/api/health"
echo "5. Access through an SSH tunnel, never public 8086/8788."
