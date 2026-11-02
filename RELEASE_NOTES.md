## v0.3.1-dev — Durable outbound agent heartbeats

- Added a durable owner-only `*.sequence` heartbeat counter using Linux file locks and fsync; signed sequence numbers survive agent restarts and backward clock adjustments.
- Added a private JSON-configured `agent.heartbeat --check|--once` entry point, with no Docker access or inbound ports.
- Added optional, **disabled by default** user-systemd one-shot service and timer templates for heartbeat-only operation.
- Added in-process full API-to-agent enrollment/heartbeat/revocation integration tests without requiring a live remote host.
- Updated the operator runbook; production remote Docker inventory remains disabled until tested on a disposable Tailscale node.

## v0.3.0-dev — Private agent identity and enrollment foundation

- Added owner-only, expiring, one-use 256-bit enrollment invitations stored by SHA-256 hash, with automatic invalidation of replaced invitations.
- Added Ed25519 public-key proof-of-possession during enrollment and stored per-server identity fingerprints without private keys.
- Added signed, timestamp-bounded, strictly increasing heartbeat sequence verification, revocation, and re-enrollment after revocation.
- Added owner-side Servers dashboard identity management and one-time invitation display, with audit events.
- Added outbound-only agent CLI restricted to verified `https://*.ts.net:8443`; writes a private 0600 identity and supports manual signed heartbeats.
- Added tests for auth/CSRF, token expiry and replay, cross-owner access, invalid signatures, key file safety and revocation.
- **No remote Docker inventory or commands, no exposed agent ports, and no automatic production deployment.**
- Requires further operator validation on a disposable remote agent machine and Tailnet Grants before enabling any remote inventory.

## MT Panel-only staged activation and rollback tooling

- Added explicit `scripts/promote-vps.py --check|--activate|--rollback` with exact stage/backup paths and mandatory confirmation flags for changes.
- Activation stops only the two MT Panel systemd units, snapshots SQLite and configuration, retains previous root-owned application files, switches a tested stage, then validates module imports, health and unauthenticated authorization boundaries.
- Automatic recovery is attempted on failed activation; manual rollback is possible even when current MT Panel services are unhealthy, and backs up the current database before restoring the previous SQLite snapshot.
- The command **never** installs Docker, touches existing proxy/Tailscale Serve routes, or changes unrelated systemd units.
- Still pilot-grade: production rollout requires explicit operator review, database backup validation and a brief MT Panel maintenance window. This code has not been run against the user's VPS by the assistant.

## Existing VPS upgrade staging and status (development)

- Added `scripts/vps-status.py --check` for read-only verification of the installed control-plane/agent identities, local bindings and private HTTPS origin without leaking the agent token.
- Added `scripts/upgrade-vps.sh --check|--stage` to archive only Git-tracked sources, install dependencies in an isolated directory and run the test suite, without replacing or stopping the live installation.
- Documented staged-upgrade verification and future promotion/rollback gates for an existing systemd VPS.
- Still requires explicit VPS-side activation and backup verification before any live code switch.

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
