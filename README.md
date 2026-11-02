# MT Panel

**Independent self-hosted VPS operations dashboard.** Working project name, version `0.3.6-dev`.

MT Panel is an Easypanel-style platform designed from scratch for managing Linux hosts and Docker applications. **Current release is a pilot with read-only Docker inventory and metadata-only project/server definitions**: admin login, host information, containers, images, networks, volumes, bounded container logs, persistent authentication audit, owner-scoped servers/projects/environments and strictly validated deployment drafts. No actual deployments are enabled. Private one-time agent enrollment and signed heartbeats are now available for trust establishment, but remote Docker inventory is not yet enabled. The Ubuntu 26.04 VPS pilot has been observed running with valid dashboard/agent health and live Docker inventory; later code changes remain GitHub-only until explicitly promoted.

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
bash scripts/init-env.sh
set -a; source .env; set +a
python -m panel.cli create-admin --username admin
bash scripts/dev.sh
```

Dashboard: `http://127.0.0.1:8086` (local server only). For demo mode without Docker, set `AGENT_DEMO_MODE=true` in `.env` before starting. Test: `bash scripts/test.sh`.

On macOS, ensure Docker Desktop is installed and running for live Docker inventory. MT Panel now checks both `/var/run/docker.sock` and `~/.docker/run/docker.sock`. If needed, specify a local Unix socket with `DOCKER_SOCKET_PATH=/absolute/path/to/docker.sock` in `.env`. Run `python3 scripts/doctor.py` for non-destructive connectivity diagnostics. The launcher selects `.venv/bin/python3` automatically if it exists.

For VPS browser access, use **Tailscale Serve over private HTTPS on port 8443** (no SSH tunnel, public IP or Tailscale Funnel). See the [Ubuntu 26.04 runbook](docs/UBUNTU_26_04_VPS_PILOT.md). Both processes bind to loopback and do not take over Caddy or the existing Tailscale HTTPS port 443.

## Documentation

- [Full technical specification, architecture, target schema, API, security and roadmap](docs/TECHNICAL_SPEC.md)
- [Pilot deployment and safety guide](docs/DEPLOYMENT.md)
- [Ubuntu 26.04 VPS installer, preflight and activation runbook](docs/UBUNTU_26_04_VPS_PILOT.md)
- [Existing VPS status and staged-only upgrade guide](docs/EXISTING_VPS_UPGRADE.md)
- [Private remote-agent enrollment and signed heartbeat guide](docs/REMOTE_AGENT_ENROLLMENT.md)
- [Fleet signed-health history, warnings and operational safety](docs/FLEET_HEALTH_MONITORING.md)
- [Architecture decision records](docs/ARCHITECTURE_DECISIONS.md)
- [Next implementation backlog and release gates](docs/PHASE2_BACKLOG.md)
- [Release notes](RELEASE_NOTES.md)

## Repository layout

```text
mt-panel/
├── agent/                 # Privileged host agent; GET-only Docker adapter
│   ├── api.py             # Authenticated resource inventory endpoints
│   └── docker.py          # Explicit Docker Engine allowlist
├── panel/                 # Unprivileged control-plane
│   ├── api.py             # FastAPI auth and inventory proxy
│   ├── auth.py            # SQLite admin, scrypt, sessions
│   └── cli.py             # Offline initial admin setup
├── web/                   # Responsive, dependency-light UI
│   ├── index.html
│   ├── styles.css
│   └── app.js
├── deployment/systemd/    # Isolated control plane and agent units
├── tests/                 # Auth, read-only access, routes, log framing
├── scripts/               # Setup, local launch, tests
├── docs/                  # Spec, deployment, ADRs, Phase 2 backlog
├── .env.example
├── requirements.txt
├── requirements-dev.txt
└── pyproject.toml
```

## Project scope

| Area | v0.1.0 | Planned |
|---|---|---|
| Admin login | Yes, offline bootstrap | Multi-user RBAC, MFA |
| Audit events | Local SQLite login/logout/bootstrap events and owner-only activity page | Configuration/job events, export and retention |
| Host health | Capacity and counts | Live utilization graphs |
| Server registry | Saved host identities, one-time Ed25519 enrollment, revocation, signed manual heartbeats | Remote Docker inventory and automatic health polling |
| Projects/environments | Persisted owner-scoped configuration + UI | Service lifecycle + multi-user RBAC |
| Deployment drafts | Immutable image digest, strict resources and no dangerous fields | Authenticated deployment executor |
| Container inspection | Name/image/state/ports/logs | Start/stop/restart with authorization |
| Images, networks, volumes | Read-only listing | Managed lifecycle |
| Git deploy | Not yet | GitHub, Buildx, queued rollout |
| Databases | Not yet | PostgreSQL, MongoDB, Redis etc. |
| Domains & TLS | Not yet | Caddy / Traefik integrations |
| Backups | Not yet | Restic, schedules and tested restores |
| Multiple servers | Cryptographic enrollment metadata only; local Docker agent remains the only reader | Per-server remote inventory and managed deployments |

## New pilot workflow (v0.2.1-dev)

After logging in, open **Servers** to create a local server *record* (unpaired) and **Projects** to create a project. Select **Manage** on a project to add environments and save image deployment drafts. A draft requires an image reference pinned to a complete sha256 digest, an internal container port, and conservative default resources. No actual Docker action is performed. The server registry does not accept SSH keys, host addresses or arbitrary URLs. The **Compose preview** in project management accepts only 1-4 digest-pinned, read-only services with internal exposed ports. Rejecting unsupported fields is intentional. It does not create containers, perform builds, or run Compose.

For the VPS upgrade: stop the running development server, run `git pull --ff-only origin main`, install requirements using `.venv/bin/python -m pip install -r requirements.txt`, optionally install dev requirements and run `bash scripts/test.sh`, then restart. Existing `.env` and `state/` remain local; SQLite adds the new tables without overwriting administrators. Keep MT Panel's ports loopback-only and use the separate Tailscale Serve HTTPS endpoint (port 8443) for browser access.

See [competitive research and implementation plan](docs/COMPETITIVE_RESEARCH_AND_PLAN.md).

## Ubuntu 26.04 systemd pilot

For a busy VPS, follow the [isolated installation runbook](docs/UBUNTU_26_04_VPS_PILOT.md). It begins with `bash scripts/install-vps.sh --check` and `bash scripts/tailscale-access.sh --check` (both read-only); installation requires explicit `--install`, and the HTTPS origin must be prepared with `bash scripts/tailscale-access.sh --prepare` before starting services. Services are **not started** automatically. The code is installed under `/opt/mt-panel`, separate from the GitHub checkout, with distinct Unix users. The dashboard stays off Docker's group, the agent has root-equivalent Docker group access, and both bind loopback-only without touching 80/443. Do not use this pilot as an Internet-facing production admin panel.

## Updates to an already installed VPS

Do **not** rerun the first-install script on an existing systemd installation.
To inspect running MT Panel services safely, run:
`python3 scripts/vps-status.py --check`.
After `git pull --ff-only origin main`, use
`bash scripts/upgrade-vps.sh --check` and then
`bash scripts/upgrade-vps.sh --stage` to build/test an isolated candidate.
The staging script never switches code, modifies the live database, or
restarts services; see the
[existing VPS upgrade guide](docs/EXISTING_VPS_UPGRADE.md).
Access the dashboard over the HTTPS Tailscale Serve endpoint, not a public port.

To promote an **already tested** candidate manually, the operator may run
`python3 scripts/promote-vps.py --check --stage /opt/mt-panel-stage.EXACT_ID`,
then `--activate --stage /opt/mt-panel-stage.EXACT_ID --confirm ACTIVATE_MT_PANEL`
in a short MT Panel maintenance window. This stops/restarts only the MT Panel
dashboard and agent, snapshots the existing SQLite database and code, and
performs automatic post-start health/authentication checks with rollback on failure.
Never guess stage or backup directory names. See the
[existing VPS upgrade and rollback guide](docs/EXISTING_VPS_UPGRADE.md).
The stage must be a previously verified candidate; the script does not promote
uncommitted code or restart Docker.

## Private enrollment foundation (v0.3.0-dev)

From **Servers → Identity**, an owner may issue an expiring single-use code,
view the public identity fingerprint and last signed heartbeat, and revoke the
identity. An outbound-only CLI in `agent/enroll.py` generates a host Ed25519
key, presents a signed enrollment proof to the existing private Tailscale HTTPS
endpoint, and sends signed manual heartbeats. No remote Docker connection or
application deployment is enabled; a "paired" identity proves a private key,
**not** remote Docker availability. The invitation is shown only once and never
stored in plaintext. See the [enrollment operator guide](docs/REMOTE_AGENT_ENROLLMENT.md).

Existing MT Panel installations must be updated using the reviewed staged
promotion procedure; `git pull` alone does not update the running systemd
services. The current VPS still runs whichever code was most recently promoted.

## Optional outbound heartbeat runner (v0.3.1-dev)

A separate enrolled Linux user may validate a private heartbeat JSON config
with `python -m agent.heartbeat --check --config PATH`, send a manual
`--once` heartbeat, or explicitly enable the supplied systemd user timer.
Durable, synchronized sequence counters prevent reuse after clock corrections.
No timer is enabled by installing or upgrading MT Panel, and the control
plane never executes commands on an enrolled host. Follow the
[agent enrollment guide](docs/REMOTE_AGENT_ENROLLMENT.md).

## Signed host-health reports (v0.3.2-dev)

An enrolled Tailscale-connected agent may **optionally** submit a signed
host summary using `python -m agent.heartbeat --report --config PATH`.
The fixed report schema contains hostname, Linux release, CPU count,
total RAM, disk capacity/free space and uptime. Each report is bound
to its enrolled Ed25519 key, strict schema, clock window and sequence.
Owners can view recent/stale snapshots under Servers > Identity.

A signed report is not proof of remote Docker connectivity or permission
to modify any container. The control plane never initiates remote
network requests to saved servers. Reports are never scheduled automatically.
See [agent enrollment instructions](docs/REMOTE_AGENT_ENROLLMENT.md).

## Installed-release verification

Run `python3 scripts/verify-live-vps.py --check --expected-version 0.3.2-dev`
from the VPS Git checkout **after** explicitly promoting the tested
candidate. This is a non-destructive check of live version, authentication
boundaries, private SQLite schema, and Tailscale Serve 8443. Merely pulling
GitHub source into `~/mt_easy_panel` does not upgrade `/opt/mt-panel`.

## Fleet-wide signed health monitoring (v0.3.3-dev)

The **Servers** page now offers an owner-scoped fleet overview with verified
identity state, recent/stale signed heartbeats, and last signed Linux host
health reports. The `GET /api/fleet/summary` API reads only SQLite data,
limits returned server records to 500, and never attempts a connection to
registered machines. Agent revocation and key re-enrollment clear any old
signed host snapshots to prevent attributing one host's telemetry to a
different key.

**Paired does not mean Docker-connected**: signed host reports are
self-reported, not hardware-attested. This feature does not enumerate remote
Docker containers, run privileged remote agents, or expose new server ports.
See [agent enrollment](docs/REMOTE_AGENT_ENROLLMENT.md) and the
[existing VPS upgrade runbook](docs/EXISTING_VPS_UPGRADE.md) for the
separate deployment and disposable test-host requirements.

## Signed fleet-health history and warnings (v0.3.4-dev)

Each valid Ed25519-signed Linux host report adds one disk-free history
point to a server-specific SQLite series (288 retained samples per server).
An owner can inspect recent signed history on the **Servers → Identity /
health** screen. The fleet listing now calculates on-request warnings for
missing recent signed heartbeats (3-minute freshness window), stale full
reports and low disk-free space (below 20% warning; below 10% critical).

Warnings are informative summaries of the **last self-reported signed
metrics**; they do not represent remote Docker health, do not run as
background checks and send no notifications. Revoking or replacing an
identity deletes its prior report history. The control plane never connects
to enrolled hosts. See [fleet monitoring guide](docs/FLEET_HEALTH_MONITORING.md)
for thresholds, retention and limitations.

## Operational pages (v0.3.5-dev)

The previously disabled **Monitoring**, **Deployments**, and **Settings**
navigation items now work, but **none perform host mutations**:

- **Monitoring:** on-demand local Docker overview (via the existing
  loopback-only, GET-only agent) alongside per-owner signed fleet health,
  staleness and warning counts. If the local agent is unavailable, the
  fleet data still renders with a truthful offline indication. No
  background polling, notifications, or automatic host interventions.
- **Deployments:** owner-only, read-only inventory of the first 200 saved
  digest-pinned application drafts, with their project, environment,
  optional server assignment and explicit blockers. Every item is marked
  `draft_only` / `executable: false`. No deployment ledger of actual
  executions exists, and no deploy/restart/Compose command is offered.
- **Settings:** a read-only security posture view showing HTTPS origin,
  session cookie policy, local agent isolation, disabled Docker writes,
  absence of MFA/multi-user RBAC and other production prerequisites.
  Never includes the agent token, private identity keys, passwords,
  database paths, or session cookies.

The APIs `GET /api/monitoring/overview`,
`GET /api/deployments/readiness`, and
`GET /api/settings/security` require owner authentication.
They do not expose unscoped host access or mutate any remote resources.

The user's existing v0.3.4-dev VPS is **not** automatically upgraded when
commits land in GitHub. For each release use the
[staged upgrade runbook](docs/EXISTING_VPS_UPGRADE.md), verify the exact
new staging commit and explicitly promote only that release.

## Safe VPS release lifecycle (v0.3.6-dev)

Use `python3 scripts/release-status.py --check` on the existing VPS for a
**read-only** report of the running dashboard version, installed code
revision, current Git checkout, and every verified staging directory.
This does not change the running application, Docker, systemd, Tailscale,
SQLite, credentials or any deployment.

After a successful `bash scripts/upgrade-vps.sh --stage`, the script prints
the **exact tested directory, full commit SHA and two copyable commands**
for promotion preflight and explicit activation. The commands use
`--expect-commit FULL_SHA`; choosing a different stage is refused before
services are touched.

`scripts/verify-live-vps.py --check --expected-version VERSION` is a
**post-activation-only** verifier. When the running dashboard is older it
prints `NOT ACTIVE` and explains the remaining activation step, without
issuing misleading failures about endpoints and schema that exist only in
the staged release. It exits with status 2 (not yet live); this is not a
staging or installation failure.

The operator still explicitly activates a tested release in a brief MT
Panel-only maintenance window. Old staging candidates and rollback
snapshots are never automatically deleted. See the
[existing VPS upgrade guide](docs/EXISTING_VPS_UPGRADE.md).

## Security boundary

**Do not expose the agent to the Internet or the Docker daemon on unauthenticated TCP.** A Docker socket holder has root-equivalent host access, including if a socket mount is labeled `:ro`; the Python agent still needs special care even with read-only API routes. In Phase 1, only the host-local agent can open the Docker socket; the UI/API does not. Never run the dashboard as a Docker-group member. This is a test/pilot codebase, not a fully security-audited production panel.

## IP and licensing

The implementation is independently authored. It has no bundled Easypanel proprietary source, trademarks, or assets. Licensing/public repository visibility should be decided by the project owner before publication.
