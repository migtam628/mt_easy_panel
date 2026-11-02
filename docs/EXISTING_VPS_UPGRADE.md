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

## Activation of a *verified staged* candidate (operator action)

The activation tool lives in your GitHub checkout as `scripts/promote-vps.py`;
it is **not** automatically invoked by staging. Its --check mode reads the
existing systemd/Tailscale security settings, requires both services to be
healthy, verifies the candidate marker, and makes no changes.

For the stage that was tested successfully on Ubuntu 26.04:

```bash
cd ~/mt_easy_panel
python3 scripts/promote-vps.py --check --stage /opt/mt-panel-stage.rjP8TppP
```

The stage's saved commit is `9d279a6`. It does not automatically include
more recent GitHub commits; this is intentional so the tested candidate is
promoted, not untested source.

When approved for a brief, MT Panel-only maintenance interruption:

```bash
python3 scripts/promote-vps.py --activate \
  --stage /opt/mt-panel-stage.rjP8TppP \
  --confirm ACTIVATE_MT_PANEL
```

**This is a live change**: it stops/restarts `mt-panel.service` and
`mt-panel-agent.service`, temporarily interrupting the MT Panel dashboard.
Other Docker containers and host services are not intentionally modified.
The script snapshots the stopped SQLite database, private environment file,
and both unit files into a root-only backup under `/opt/mt-panel-backups/`;
it retains the previous application directory in that backup.

It moves the staged app into `/opt/mt-panel` and verifies Python imports,
both local health endpoints and unauthenticated HTTP 401 boundaries. If these
checks fail, it attempts to restore the prior application directory and SQLite
snapshot and restart the two MT Panel services automatically. **Do not assume
rollback succeeded without reading the command output and rechecking health.**

After promotion, confirm:

```bash
python3 scripts/vps-status.py --check
curl -fsS http://127.0.0.1:8086/api/health
curl -fsS http://127.0.0.1:8788/health
tailscale serve status
```

The browser stays at the existing private Tailscale port 8443 URL.

## Explicit manual rollback

Use the **exact backup path printed by the successful activation**:

```bash
python3 scripts/promote-vps.py --rollback \
  --backup /opt/mt-panel-backups/mt-panel-backup.EXACT_ID_FROM_OUTPUT \
  --confirm ROLLBACK_MT_PANEL
```

This stops/restarts *only* the two MT Panel units, restores the old code and
pre-upgrade SQLite snapshot, and preserves the replaced candidate under the
backup path for inspection. **Database changes made after activation will
be lost on rollback**; back up any new activity you want to preserve.
Never guess the backup directory. Avoid this operation if other processes are
writing the MT Panel SQLite database; use a maintenance period.

The upgrade does not change existing Tailscale Serve routes, credentials,
systemd unit definitions or other Docker workloads. It does not run Docker
Compose, install packages system-wide, or reconfigure a proxy.

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
