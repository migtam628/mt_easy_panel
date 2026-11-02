# MT Panel

**Independent self-hosted VPS operations dashboard.** Working project name, version `0.1.2`.

MT Panel is an Easypanel-style platform designed from scratch for managing Linux hosts and Docker applications. **Current Phase 1 is a functioning read-only pilot**: admin login, host information, containers, images, networks, volumes, bounded container logs, and a persistent authentication audit trail. It has not been installed on any user VPS or tested against a live Docker daemon in this environment.

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

To view remotely, use an SSH local port forward over Tailscale (details in [Deployment Guide](docs/DEPLOYMENT.md)). Both processes bind to loopback by default and do **not** take over 80/443 or replace Caddy.

## Documentation

- [Full technical specification, architecture, target schema, API, security and roadmap](docs/TECHNICAL_SPEC.md)
- [Pilot deployment and safety guide](docs/DEPLOYMENT.md)
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
| Container inspection | Name/image/state/ports/logs | Start/stop/restart with authorization |
| Images, networks, volumes | Read-only listing | Managed lifecycle |
| Git deploy | Not yet | GitHub, Buildx, queued rollout |
| Databases | Not yet | PostgreSQL, MongoDB, Redis etc. |
| Domains & TLS | Not yet | Caddy / Traefik integrations |
| Backups | Not yet | Restic, schedules and tested restores |
| Multiple servers | Local agent only | Secure registration/pairing |

## Security boundary

**Do not expose the agent to the Internet or the Docker daemon on unauthenticated TCP.** A Docker socket holder has root-equivalent host access, including if a socket mount is labeled `:ro`; the Python agent still needs special care even with read-only API routes. In Phase 1, only the host-local agent can open the Docker socket; the UI/API does not. Never run the dashboard as a Docker-group member. This is a test/pilot codebase, not a fully security-audited production panel.

## IP and licensing

The implementation is independently authored. It has no bundled Easypanel proprietary source, trademarks, or assets. Licensing/public repository visibility should be decided by the project owner before publication.
