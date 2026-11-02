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

**Existing staged revisions are preserved.** The staging tool may retain up
to five separate candidates, so preparing a new revision does not
require deleting an older verified staging candidate.
If five candidates already exist, it refuses to stage another. Review those
directories and available disk space manually; do not recursively delete
unidentified directories.

After staging a newer release, copy the **exact printed directory and SHA**
for promotion preflight. The command now prints both pinned commands, so
there is no need to guess or substitute a previous release's directory.

The 0.3.x application code has passed repository CI but is not active on the
VPS until you explicitly run a tested candidate's activation command.

## Activation of a *verified staged* candidate (operator action)

The activation tool lives in your GitHub checkout as `scripts/promote-vps.py`;
it is **not** automatically invoked by staging. Its --check mode reads the
existing systemd/Tailscale security settings, requires both services to be
healthy, verifies the candidate marker, and makes no changes.

**Use the exact commands printed by your successful --stage invocation.**
Never reuse a directory name from a previous session or an example in
this guide. The `--expect-commit FULL_SHA` argument is recommended for
both operations, to prevent activating a different tested revision:

```text
PASS: Upgrade candidate staged and tested: /opt/mt-panel-stage.EXACT_ID
STAGE_PATH=/opt/mt-panel-stage.EXACT_ID
STAGE_REVISION=40_CHARACTER_COMMIT
NEXT - read-only promotion preflight:
  python3 scripts/promote-vps.py --check --stage EXACT_PATH --expect-commit EXACT_SHA
AFTER preflight passes - explicitly activate the same tested stage:
  python3 scripts/promote-vps.py --activate --stage EXACT_PATH --expect-commit EXACT_SHA --confirm ACTIVATE_MT_PANEL
```

The values above illustrate the output format; **do not paste the
placeholders**. Copy your own stage command's printed path and SHA exactly.
The --check preflight validates the specific installed services and staging
revision, but does not activate the candidate.

Before or after staging, you can also inspect all versions **without
making changes**:

```bash
python3 scripts/release-status.py --check
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

After successful activation, run the read-only verifier from your
Git checkout, specifying the **version that was actually staged**:

```bash
cd ~/mt_easy_panel
python3 scripts/verify-live-vps.py --check --expected-version 0.3.5-dev
```

The version above is an example for the v0.3.5 release. For the
subsequent release, use its own expected version. Never run this verifier
as the staging test: staging tests already run in the isolated stage.
If a prior version is still running, the verifier returns status **2** with
a single `NOT ACTIVE` message and instructions for promotion. It will
not misreport new endpoints or database tables as damaged just because
they have not yet been installed.

After promotion, also confirm:

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
pre-upgrade SQLite snapshot, and preserves the replaced candidate and a
pre-rollback copy of the newer database under the backup path for inspection.
It can operate even if MT Panel's currently installed units are unhealthy. **Database changes made after activation will
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

## Upgrading to the v0.3.5 operational screens

After a release with v0.3.5-dev is pushed and CI is green, pull the source
on the existing VPS, use `bash scripts/upgrade-vps.sh --stage` and record
the **newly printed** directory. Compare its `.staged-commit` to the exact
commit you intend to deploy. Do not reuse an older staged directory because
it has passed checks in a different release.

Run `python3 scripts/promote-vps.py --check --stage /opt/mt-panel-stage.EXACT_ID`
and review the output before the explicitly confirmed `--activate`
operation. Activation briefly stops only the MT Panel services, captures
a private SQLite/code backup, and runs local health/auth checks.
After successful activation, run:

```bash
python3 scripts/verify-live-vps.py --check --expected-version 0.3.5-dev
```

A verifier run **before activation** should fail on the older live version;
that is not a staging failure. Nothing in this upgrade enables Docker write
operations, deployment jobs, automatic alerts or remote agent execution.

## Current development limits

The UI and agent are pilot-grade. Docker inventory is read-only and the agent
holds root-equivalent socket access. Saved server/project/Compose records
do not cause deployments. Do not enable arbitrary container writes, SSH agent
management, or live redeployment of production containers until the separate
deployment security gate and disposable-host tests pass.

## v0.3.7: local diagnostic screens, staged-only until promoted

Before a fresh upgrade, use `python3 scripts/release-status.py --check`
to distinguish the currently running MT Panel from the repository checkout.
The new diagnostics endpoints are **not** present in an older active build,
so `scripts/verify-live-vps.py --check --expected-version 0.3.7-dev`
must be run **only after successful activation** of a v0.3.7 candidate.

The staged promotion workflow prints exact SHA-pinned commands.
Verify `STAGE_REVISION` before invoking `--activate`. On success,
run the expected-version verifier and `scripts/vps-status.py --check`.
This release does not add Docker write actions or deployment execution.
