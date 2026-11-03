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

## v0.3.8 Phase A: default-off lab execution remains excluded on this VPS

This release adds a **lab-only** write adapter, but its effective enable
setting is false by default. Do **not** configure
`PANEL_LOCAL_EXECUTION_ENABLED`, `AGENT_LOCAL_EXECUTION_ENABLED` or
the associated disposable-host lab acknowledgements in the existing
production VPS's environment file. Do **not** grant new privileges or
run a write-enabled agent on that VPS.

Before promotion, stage the release using the existing exact SHA-pinned
workflow. Only after activation, run:

```bash
python3 scripts/verify-live-vps.py --check --expected-version 0.3.8-dev
python3 scripts/vps-status.py --check
```

The post-promotion verifier additionally checks the local Docker agent's
health reports `lab_execution_enabled: false`, and fails rather than
claiming a safe deployment if this is missing or true. This does not
test or authorize the optional disposable-host lab write path.

## v0.3.9 operator-run safe sync and staging

To inspect the running source/installed versions without making changes:

```bash
cd ~/mt_easy_panel
bash scripts/vps-test-sync.sh --check
```

To fast-forward the reviewed main branch and create or reuse a fully tested
stage (run on the installed VPS as root):

```bash
cd ~/mt_easy_panel
bash scripts/vps-test-sync.sh --stage
```

This updates **only** the Git source checkout and a separate stage under
/opt. It does **not** activate it, restart any service or touch existing
Docker containers, Docker sockets, Tailscale Serve, Caddy or ports 80/443.

After staging prints the exact stage path and SHA, run the printed
`promote-vps.py --check --stage ... --expect-commit ...`. Only after PASS,
a human may invoke the printed confirmed activation and save the rollback
directory. Do not run the post-promotion verifier before activation.
After activation:

```bash
python3 scripts/verify-live-vps.py --check --expected-version 0.3.9-dev
python3 scripts/vps-status.py --check
```

Both panel and agent must report `lab_execution_enabled=false`; the
verifier fails closed if either is true or unavailable. **Do not enable
`PANEL_LOCAL_EXECUTION_ENABLED` or `AGENT_LOCAL_EXECUTION_ENABLED`
on the existing production VPS.** This release has not been validated
for write-enabled production operations.

## v0.3.10-dev — Stage/test UI update without enabling Docker writes

The first real Docker Engine integration test now runs **only** on an
ephemeral GitHub-hosted CI runner, not on this production VPS.
A production `bash scripts/vps-test-sync.sh --stage` performs normal
offline/staged Python and web checks while skipping the isolated Docker
integration tests. Only stage a commit with all GitHub CI checks green.

On the installed VPS:

```bash
cd ~/mt_easy_panel
bash scripts/vps-test-sync.sh --check
bash scripts/vps-test-sync.sh --stage
```

The second command updates the source checkout and stages/reuses the
exact commit without changing the active version. Follow **only** its
printed exact-SHA preflight/activation commands after review. This
restarts only MT Panel services and preserves a rollback backup.
After promotion, check:

```bash
python3 scripts/verify-live-vps.py --check --expected-version 0.3.10-dev
python3 scripts/vps-status.py --check
```

Both agent and panel must have `lab_execution_enabled=false`.
**Never** enable local lab writes, Docker proxy access, reverse proxy
changes, or ports 80/443 takeover on this production VPS to test this
candidate. A successful CI run alone does not authorize production
Docker execution.

## v0.3.11 — Update the read-only review UI safely

Source update and separate staging (no live service restart):

```bash
cd ~/mt_easy_panel
bash scripts/vps-test-sync.sh --check
bash scripts/vps-test-sync.sh --stage
```

Only after successful GitHub CI and the stage's printed SHA-pinned
promotion preflight, the operator may separately activate that exact
stage. After activation, not before:

```bash
python3 scripts/verify-live-vps.py --check --expected-version 0.3.11-dev
python3 scripts/vps-status.py --check
```

Confirm both health endpoints say `lab_execution_enabled=false`.
The evidence packet and review metadata do **not** authorize host
clearance. Never enable lab writes on the existing production VPS.

## v0.3.12 — Optional Next.js static preview, private original origin

A normal `vps-test-sync.sh --stage` now stages the Next frontend **source**
but deliberately does not run npm, build assets or enable the preview on
the installed VPS. Your existing `/` dashboard remains unchanged.

To preview the new UI safely:

1. Confirm the **exact commit** passed the Python 3.12/3.14, disposable
   Docker and **Next static preview** GitHub Actions checks.
2. Run `bash scripts/vps-test-sync.sh --stage` and copy the printed
   `STAGE_PATH` and `STAGE_REVISION`. If stage cap is reached, stop;
   review existing stages before deleting anything.
3. Download that exact CI run's `mt-panel-next-static` artifact into
   an empty local directory on the VPS. The GitHub CLI may be used, e.g.
   `gh run download <RUN_ID> -R migtam628/mt_easy_panel -n mt-panel-next-static -D /tmp/mt-panel-next-preview`.
   This is an **operator step**, not a background update.
4. Run the add-only validation, substituting your stage and SHA:

```bash
python3 scripts/install-next-preview-stage.py --check \
  --stage /opt/mt-panel-stage.EXAMPLE123 \
  --bundle-dir /tmp/mt-panel-next-preview \
  --expect-commit YOUR_EXACT_40_CHAR_SHA
```

5. Only after PASS, separately run `--install` with the **same** stage,
   bundle and SHA, adding `--confirm INSTALL_MT_PANEL_NEXT_PREVIEW`.
   The importer checks ownership, source revision, per-file hashes and
   symlinks, and copies static assets **only into the staged directory**.
6. Follow the existing printed `promote-vps.py --check` then separately
   approved activation commands. Verify
   `python3 scripts/verify-live-vps.py --check --expected-version 0.3.12-dev`
   and `scripts/vps-status.py --check` after activation.
7. **Only if you want to enable the parallel preview:** back up your
   root-owned `/etc/mt-panel/mt-panel.env`, then edit it using
   `sudoedit` and add `PANEL_NEXT_PREVIEW_ENABLED=true`. Restart **only**
   `mt-panel.service` with `sudo systemctl restart mt-panel.service`
   and verify the original `/api/health`, `/` and new
   `/next-preview/` URLs through the same private Tailscale HTTPS
   origin on port 8443. To disable, remove the setting and restart only
   that service. Keep the exact rollback backup from promotion.

**Do not** set `PANEL_LOCAL_EXECUTION_ENABLED` or
`AGENT_LOCAL_EXECUTION_ENABLED` on this shared VPS.
The preview flag is unrelated to Docker writes. Do not change Caddy,
Tailscale Serve, ports 80/443, or other applications.

## Recovery: v0.3.12 Next preview enabled but panel fails to listen on 8086

The original import implementation created the export in a root-owned
`mkdtemp` directory with mode `0700`. FastAPI's `mtpanel` service
account may be unable to traverse the promoted `frontend-next/out` path,
so enabling the preview can prevent the panel process from starting.
Do **not** change Docker permissions, the agent, Caddy or Tailscale.

Confirm file presence and directory permissions without exposing secrets:

```bash
sudo test -f /opt/mt-panel/frontend-next/out/index.html && echo 'Preview index present'
sudo namei -l /opt/mt-panel/frontend-next/out/index.html
sudo journalctl -u mt-panel.service -n 50 --no-pager
```

If `/opt/mt-panel/frontend-next/out/index.html` is present and the
`out` directory belongs to the root-owned stage but has mode `0700`,
repair **only its traverse/read permission**:

```bash
sudo chmod 0755 /opt/mt-panel/frontend-next/out
sudo systemctl restart mt-panel.service
curl -fsS http://127.0.0.1:8086/api/health
curl -I http://127.0.0.1:8086/next-preview/
```

If the panel is still unavailable, disable `PANEL_NEXT_PREVIEW_ENABLED`
through `sudoedit /etc/mt-panel/mt-panel.env`, restart only
`mt-panel.service`, and inspect the journal. Never dump the private
environment file into a ticket. The importer now uses public-readable,
root-owned `0755` directories and `0644` files for future stages;
previously promoted builds require the one-time mode correction.

## v0.3.13-dev — Next preview stuck at “Checking your session…”

**Root cause:** The legacy strict `script-src 'self'` CSP also applied to
Next's generated inline bootstrap scripts, blocking hydration even
though `/next-preview/` HTML, CSS and external JS were returned HTTP 200.

**Production-safe upgrade:** Do not modify the running FastAPI source
or relax CSP manually. First verify the green **v0.3.13** GitHub Actions
run and download its `mt-panel-next-static` artifact (matching the same
full Git commit SHA). Use `bash scripts/vps-test-sync.sh --stage`
to create an unactivated stage. Attach the matching static bundle via
`scripts/install-next-preview-stage.py --check` and, after PASS,
the separately confirmed `--install`. Continue with the **exact**
stage/SHA `scripts/promote-vps.py --check` then, after PASS, the
separately approved `--activate` command.

After activation:
```bash
python3 scripts/verify-live-vps.py --check --expected-version 0.3.13-dev
python3 scripts/vps-status.py --check
curl -fsSI http://127.0.0.1:8086/next-preview/
```

Check the browser Console for CSP blocking errors; the Next preview
HTML should have per-script `sha256-` values in its CSP header, but
the original dashboard and `/api/health` should still report
`script-src 'self'` **without** `unsafe-inline` or `unsafe-eval`.
Do not enable lab Docker writes. If preview startup fails, disable only
`PANEL_NEXT_PREVIEW_ENABLED` and restart only `mt-panel.service`;
the legacy dashboard is unaffected. Tailscale and other applications
remain outside the upgrade.

## v0.3.14-dev — Original-looking Next preview test deployment

CI for the exact commit must pass Next static export, Python 3.12/3.14,
disposable Docker, and parity source-contract tests before staging.

From the existing VPS checkout, run `bash scripts/vps-test-sync.sh --stage`.
Record the printed `STAGE_PATH` and full `STAGE_REVISION`. Download
the `mt-panel-next-static` artifact from the **matching** green
GitHub Actions run to a new empty `/tmp` directory. Run
`scripts/install-next-preview-stage.py --check` with that stage,
bundle directory and exact revision; if PASS, repeat `--install`
with explicit confirmation. Check the exact stage using
`scripts/promote-vps.py --check`, and only after PASS separately
activate with `--confirm ACTIVATE_MT_PANEL`.

After activation, verify v0.3.14-dev and confirm the agent and panel
still report `lab_execution_enabled=false`. The existing
`PANEL_NEXT_PREVIEW_ENABLED=true` setting should serve the new
export at `/next-preview/`, and `/` remains the old dashboard.
Do not attach an older preview artifact to a newer stage, alter
ports, or enable Docker writes. Rollback backup from the promotion
must be retained.

## Existing Tailscale HTTPS port 9443 (shared VPS)

If the existing private MT Panel origin already uses Tailscale Serve HTTPS
`9443` because `8443` is occupied by another application, **retain that
route and origin**. Do not run `tailscale-access.sh --prepare` or create a new
Serve route for this upgrade. `tailscale serve status` must show the MT Panel
path as `(tailnet only)` with a local `127.0.0.1:8086` proxy target.

The release verifier defaults to historical port 8443. For this existing
9443 configuration, after promotion run:

```bash
python3 scripts/verify-live-vps.py --check --expected-version 0.3.14-dev --tailscale-port 9443
```

The alternate-port flag only changes a read-only verification expectation;
it never configures Serve, Funnel, Caddy, Docker, or a listening socket.
Fail closed if the route is public, missing or points to a different backend.
