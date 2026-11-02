# Safe ongoing updates on the existing MT Panel VPS

This guide is for an **already installed, running** MT Panel systemd pilot
with code at /opt/mt-panel, private config at /etc/mt-panel, and SQLite at
/var/lib/mt-panel. It is not a clean installer and does not manage Tailscale
Serve routes or existing Docker applications.

## First: verify existing services and private access

Run read-only commands on the VPS:

```bash
cd ~/mt_easy_panel
python3 scripts/vps-status.py --check
tailscale serve status
curl -fsS http://127.0.0.1:8086/api/health
curl -fsS http://127.0.0.1:8788/health
```

Expected: both services active, each on its dedicated account, port 8086 and
8788 loopback-only, and the browser HTTPS origin configured for the private
8443 Tailscale URL. The status script does not reveal the agent token.

If the HTTPS origin has not been prepared, follow the
[Ubuntu 26.04 pilot](UBUNTU_26_04_VPS_PILOT.md) instructions. Do not reset
the shared tailnet Serve configuration; port 443 may belong to another app.

## Prepare the next release *without changing the running app*

```bash
cd ~/mt_easy_panel
git status --short
git pull --ff-only origin main
bash scripts/upgrade-vps.sh --check
bash scripts/upgrade-vps.sh --stage
```

The last command is the only state-changing action in this section. It
**creates a new root-owned directory under /opt**, restores tracked code only
via `git archive HEAD`, creates an isolated Python venv, installs Python
dependencies there, and runs the complete unit test suite and compile checks.
It does not modify /opt/mt-panel, the live SQLite database, private credentials,
systemd service definitions, Docker containers, Caddy, or Tailscale.

Untracked files such as `.bashrc` are never included because `git archive`
uses the committed revision, not the current filesystem tree.

The command prints the **exact stage directory** (for example,
`/opt/mt-panel-stage.XXXXXXXX`). Record that path. Do not guess the path.

## Activation gate (not implemented by this staging script)

There is intentionally no automatic promotion to production. The next
activation procedure needs an explicitly reviewed maintenance window and
working, verified backups of:

- /var/lib/mt-panel/panel.db (consistent SQLite backup);
- /etc/mt-panel/mt-panel.env (private; never paste into chat);
- /opt/mt-panel (the currently running code);
- both MT Panel systemd unit files.

The activation workflow must stop **only** mt-panel.service and
mt-panel-agent.service, switch the code atomically where possible, restart
those two units, validate the health endpoints and authorization, and provide
a tested rollback to the previous code/database. No other systemd service or
Docker workload may be restarted.

This upgrade stage is a **build-and-test candidate**, not a deploy. Always
send the stage command's result before using any promotion steps.

## Tailscale-specific notes

Use the tailnet HTTPS hostname shown by `tailscale serve status`, on port
8443. It must match `PANEL_PUBLIC_ORIGIN` including the scheme and port;
`PANEL_COOKIE_SECURE=true` is required. Keep the backend on
`127.0.0.1:8086` and the agent on `127.0.0.1:8788`.

Never configure Tailscale Funnel for MT Panel. Do not use
`tailscale serve reset` on a host that already serves other applications.

## Current development limits

The UI and agent are pilot-grade. Docker inventory is read-only and the agent
holds root-equivalent socket access. Saved server/project/Compose records
do not cause deployments. Do not enable arbitrary container writes, SSH agent
management, or live redeployment of production containers until the separate
deployment security gate and disposable-host tests pass.
