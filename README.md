# MT Panel

**Independent self-hosted VPS operations dashboard.** Working project name, version `0.2.1-dev`.

MT Panel is an Easypanel-style platform designed from scratch for managing Linux hosts and Docker applications. **Current release is a pilot with read-only Docker inventory and metadata-only project/server definitions**: admin login, host information, containers, images, networks, volumes, bounded container logs, persistent authentication audit, owner-scoped servers/projects/environments and strictly validated deployment drafts. No actual deployments are enabled. The dedicated Ubuntu 26.04 systemd pilot installer and Python 3.14 CI checks are available, but live Docker inventory and installer operation on the user's VPS are not yet verified.

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
| Server registry | Saved, unpaired host identities (no remote access) | Trusted pairing, heartbeats, revocation |
| Projects/environments | Persisted owner-scoped configuration + UI | Service lifecycle + multi-user RBAC |
| Deployment drafts | Immutable image digest, strict resources and no dangerous fields | Authenticated deployment executor |
| Container inspection | Name/image/state/ports/logs | Start/stop/restart with authorization |
| Images, networks, volumes | Read-only listing | Managed lifecycle |
| Git deploy | Not yet | GitHub, Buildx, queued rollout |
| Databases | Not yet | PostgreSQL, MongoDB, Redis etc. |
| Domains & TLS | Not yet | Caddy / Traefik integrations |
| Backups | Not yet | Restic, schedules and tested restores |
| Multiple servers | Local agent only | Secure registration/pairing |

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

## Security boundary

**Do not expose the agent to the Internet or the Docker daemon on unauthenticated TCP.** A Docker socket holder has root-equivalent host access, including if a socket mount is labeled `:ro`; the Python agent still needs special care even with read-only API routes. In Phase 1, only the host-local agent can open the Docker socket; the UI/API does not. Never run the dashboard as a Docker-group member. This is a test/pilot codebase, not a fully security-audited production panel.

## IP and licensing

The implementation is independently authored. It has no bundled Easypanel proprietary source, trademarks, or assets. Licensing/public repository visibility should be decided by the project owner before publication.
