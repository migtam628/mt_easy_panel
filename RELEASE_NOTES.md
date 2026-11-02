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
