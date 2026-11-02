# Ubuntu 26.04 VPS pilot — isolated read-only installation

This runbook is designed for a **busy VPS already running Docker and applications**.
It was prepared for Ubuntu 26.04 / Python 3.14 / Docker Engine 29.
The code has passed Python 3.12 and 3.14 CI but the installer is **not yet
verified on this VPS**. It must not be treated as production-hardened software.

## Safety boundaries

- No installation, reconfiguration, restart, or removal of Docker Engine.
- No replacement of Caddy, nginx, Traefik, or Tailscale.
- Never take ports 80 or 443. Dashboard and agent use loopback-only 8086 and 8788.
- The dashboard process has NO Docker group. The local host agent has docker
  group access (root-equivalent trust). The application adapter supports
  hardcoded GET endpoints only, but socket compromise is still serious.
- No Docker write operations, no remote host pairing, no app deployments.
- Explicit `--install` stages files and systemd units but **does not start**
  or enable services. Only the administrator can run the enable command.

## 1. Refresh checkout and preflight (read-only to system services)

Run as root on the target VPS in the existing source checkout:

```bash
cd ~/mt_easy_panel
git status --short
git pull --ff-only origin main
bash scripts/install-vps.sh --check
```

Read any failures before proceeding. If 8086 or 8788 has an existing listener,
identify it with `ss -lntp` and do not terminate unrelated processes.
The preflight checks Docker Engine, python3, venv availability, Docker socket
group, existing MT Panel accounts/installation, and port occupancy. It prints
80/443 listeners for information only.

## 2. Stage MT Panel services (explicit changes limited to its paths)

Only after a passing preflight:

```bash
cd ~/mt_easy_panel
bash scripts/install-vps.sh --install
```

The script creates:
- Root-owned application snapshot: `/opt/mt-panel` (not live-linked to the checkout).
- New service identities: `mtpanel` and `mtpanel-agent`.
- Private SQLite data directory: `/var/lib/mt-panel` (owned by mtpanel).
- Root-readable private configuration: `/etc/mt-panel/mt-panel.env`.
- Two **disabled / stopped** systemd unit files:
  `mt-panel.service` and `mt-panel-agent.service`.

It does NOT replace existing root checkout files, source credentials, or any
application container.

## 3. Offline admin bootstrap

```bash
cd /opt/mt-panel
runuser -u mtpanel -- env PANEL_DB_PATH=/var/lib/mt-panel/panel.db \
  /opt/mt-panel/.venv/bin/python -m panel.cli create-admin --username admin
```

Choose a unique password at least 14 characters long. This account/database
is separate from any prior pilot installation under `~/mt_easy_panel/state`.

## 4. Explicitly start the isolated new units

Only when you choose to activate them:

```bash
runuser -u mtpanel-agent -- docker info --format '{{.ServerVersion}}'
systemctl enable --now mt-panel-agent.service mt-panel.service
systemctl status mt-panel-agent.service mt-panel.service --no-pager
curl -fsS http://127.0.0.1:8788/health
curl -fsS http://127.0.0.1:8086/api/health
ss -lntp | grep -E ':(8086|8788)[[:space:]]'
```

Both listeners must be `127.0.0.1`, not a public/Tailscale interface.

If a new unit fails, inspect just the new service logs:

```bash
journalctl -u mt-panel.service -u mt-panel-agent.service -n 70 --no-pager
```

**Do not** send API tokens or password hashes with diagnostic output.

## 5. Access from the Mac over Tailscale SSH

Open a separate macOS Terminal (ensure local port 8086 is unused):

```bash
ssh -N -L 8086:127.0.0.1:8086 root@YOUR_VPS_TAILSCALE_IP
```

Then navigate to `http://127.0.0.1:8086` and sign in.
The configured exact browser origin is `http://127.0.0.1:8086`.
`localhost` is not equivalent for the origin check.

## Disable or back out without touching other applications

```bash
systemctl disable --now mt-panel.service mt-panel-agent.service
```

This stops only MT Panel. It does not remove any services, Docker workloads,
the installation, or the local DB. If cleanup is needed later, take a backup
of the isolated MT Panel database/config and review the install manifest first;
do not delete shared Docker directories.

## Upgrades

This script is **first-install only**. It does not update an already installed
`/opt/mt-panel`. Pulling GitHub changes into `~/mt_easy_panel` alone will
NOT update running systemd services. An upgrade/rollback procedure will be
published and validated separately before doing in-place updates.

## Security and limitations

The Docker group grants root-equivalent access despite the app's read-only
HTTP endpoints. There is not yet a hardened socket proxy or completed security
audit. Avoid direct Internet exposure, untrusted users and arbitrary plugins.
Use a disposable host for write-path and deployment testing.
