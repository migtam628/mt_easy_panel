## Tailscale-only VPS access update (v0.2.1-dev)

- Added `scripts/tailscale-access.sh --check` to identify the node's actual Tailscale HTTPS hostname and refuse Serve/Funnel port 8443 conflicts.
- Added explicit `--prepare` that atomically configures `PANEL_PUBLIC_ORIGIN=https://<node>.<tailnet>.ts.net:8443` and `PANEL_COOKIE_SECURE=true` without revealing or changing agent credentials.
- Replaced the VPS SSH browser-tunnel guide with persistent private `tailscale serve --bg --https=8443 http://127.0.0.1:8086`.
- Preserves existing Tailscale port 443 routes, public HTTP/HTTPS proxies, Docker and all containers.
- Tailscale Serve activation remains a separate, user-approved VPS command; no live server changes have been made here.
- Added fake-Tailscale CLI tests for hostname validation and port-conflict detection.

## v0.2.1-dev — Ubuntu VPS systemd pilot (manual install only)

- Added read-only VPS compatibility and port preflight for Python 3.14 / Docker Engine 29.
- Added explicit first-install-only script that stages root-owned application code, a private environment, and two separate systemd units; it **never starts services automatically**.
- Split unprivileged control-plane account from Docker-group agent account.
- Added unit hardening, a dedicated SQLite state directory, conservative bind addresses, and a no-proxy-takeover policy.
- Added Ubuntu 26.04 installation, SSH/Tailscale tunnel, diagnostic and service disable instructions.
- Added CI matrix for Python 3.12 and 3.14 plus installer syntax/security tests.
- **Security warning:** docker group/socket grants root-equivalent authority; agent remains pilot-grade and requires hardening before production exposure.
- No live VPS installation, modification or validation was performed by ChatGPT.

## v0.2.0-dev — Research-driven catalog and deployment draft foundation

- Completed competitor analysis of Easypanel, Coolify, Dokploy, Portainer, CapRover and Dokku (documentation linked).
- Implemented persisted owner-scoped server identity, project, environment, and service draft records.
- Added Servers/Projects UI, project workspace, environment creation and image-digest draft editor.
- Restricted new mutations to authenticated same-origin requests and recorded creation audit events in the same SQLite transaction.
- Validated strict image digest, container port, conservative CPU/RAM limits and read-only root filesystem; reject unknown dangerous Docker settings.
- Added registry/manifest regression tests and closed database connections deterministically.
- Added non-executing restricted Compose YAML compatibility preview, validating digest-pinned images, read-only filesystems and internal-only ports. Unsafe or unsupported directives are rejected, including privileged access, host mounts, published ports, interpolated variables and build commands.
- **No remote server pairing, deployment execution, docker writes, arbitrary commands, published ports or proxy reconfiguration.**
- Status: pre-release development build; not yet validated against an owner's live Docker host.

## v0.1.2 — Authentication audit foundation

- Added SQLite audit event storage with backwards-compatible `CREATE TABLE IF NOT EXISTS` migration.
- Recorded administrator bootstrap, successful and failed sign-ins, and sign-outs without storing passwords, cookies or agent tokens.
- Added authenticated, bounded `GET /api/audit/events?limit=50` and a read-only Activity dashboard view.
- Added tests for access control, persistence across restarts, limit bounds and event contents.
- No Docker write operations or network exposure introduced. This is a partial MTP-02 milestone, not complete deployment audit coverage.

# Release notes

## v0.1.1 — macOS host-agent connectivity fixes

- Detect either Linux `/var/run/docker.sock` or Docker Desktop's `~/.docker/run/docker.sock`.
- Allow explicit local Unix socket override via `DOCKER_SOCKET_PATH` (no Docker TCP connection support).
- Show actionable agent-unreachable, token-mismatch, and Docker-unreachable errors in the dashboard.
- Add unauthenticated agent liveness endpoint `/health`; Docker inventory still requires the shared token.
- Add `scripts/doctor.py` for non-destructive connectivity checks that do not expose the token.
- Prefer project `.venv/bin/python3` in the launcher even when Anaconda base is active.
- Preserve existing `.env` and `state/panel.db` during upgrades. No deployment, container mutation or production-host changes.


## v0.1.0 — Phase 1 foundation

- Separate browser-facing FastAPI control-plane and host-local authenticated inventory agent.
- SQLite-backed offline administrator bootstrap with salted scrypt password storage and hashed random session cookies.
- Read-only Docker Engine API adapter with explicit endpoint allowlist.
- Dashboard: overview, containers, images, networks, volumes, bounded container logs.
- Demo mode with explicit visual distinction from live inventory.
- Local-only startup scripts, security headers, basic login throttling, origin validation and HTTP API tests.
- CI workflow, full specification, deployment guide, Phase 2 backlog and architecture decisions.

**Verification:** Seven automated test functions passed in local execution; demo-mode HTTP smoke test passed for health, login, authorization, overview, container data and frontend asset routing. JavaScript syntax and Python compilation validated. **Live Docker/VPS deployment not performed.**

**Known limitations:** Single-host and single-owner pilot. No MFA, no real Docker instance validation, no user roles, no Git deployments, no action audit DB, no container mutation APIs, no managed secrets, no production hardening audit. Network exposure is blocked by pilot launcher design. Do not use as a public production control panel.
