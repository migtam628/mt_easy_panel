# MT Panel — Local and VPS setup (Phase 1)

## Important: pilot only, no automatic changes to existing services

This repository does **not** install Docker, replace Caddy, allocate ports 80/443, initialize Swarm, run Compose deployments, or touch an existing application. Test first on a separate VM or a maintenance-approved host. The current code has not been live-validated against the user's production Docker Engine.

## Prerequisites

- Linux server with Python 3.11+ and a virtual environment/pip.
- Docker Engine running, only if you want **live** inventory. The agent service identity must have legitimate access to the Docker socket (this is effectively root-level trust).
- Ports 8086 and 8788 free on the server's **loopback interface**.
- SSH/Tailscale access for viewing from another machine.

## Installation (non-destructive development/pilot)

```bash
# On the test server; after copying or cloning the mt-panel repository:
cd mt-panel
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
bash scripts/init-env.sh

# Review .env, and ensure the database folder is private:
chmod 600 .env
chmod 700 state
set -a; source .env; set +a
python -m panel.cli create-admin --username admin

# Starts both local services. No Docker operations other than GET requests.
bash scripts/dev.sh
```

For an environment without Docker, edit `.env` and set `AGENT_DEMO_MODE=true`. The UI prominently shows a DEMO DATA warning. Do **not** mistake demo inventory for a real server.

Access from the **server itself**: `http://127.0.0.1:8086`.

### Connecting from your workstation over Tailscale

Run an SSH tunnel from your own machine to the test host's Tailscale hostname or IP:

```bash
ssh -N -L 8086:127.0.0.1:8086 youruser@your-test-host-tailnet-ip
```

Then open `http://127.0.0.1:8086` on that workstation. This avoids public ingress and keeps browser origin/cookie configuration simple. Note that the local tunnel port must be free.

### Optional later HTTPS access

If publishing over a private HTTPS gateway, configure `PANEL_PUBLIC_ORIGIN=https://your-hostname` and `PANEL_COOKIE_SECURE=true`, and bind the application to a **trusted private interface** only. Ensure the reverse proxy and network firewall restrict access, and do not put the privileged agent behind a public proxy. Tailscale Grants should restrict access to approved users/devices. Do not simply change `PANEL_BIND=0.0.0.0` on a live VPS.

## Existing VPS service preservation

For a server already hosting a service such as a fax API behind Caddy, keep Caddy and all current published application ports unchanged. The Phase 1 control-plane uses a distinct local port and does not install another reverse proxy. Perform initial verification of available ports and Docker group membership before starting.

## Operational checks

```bash
# In a separate terminal, while services are running:
curl -fsS http://127.0.0.1:8086/api/health
# Expected: {"ok":true,"service":"mt-panel","version":"0.1.0"}

# Agent inventory routes require authentication and should reject this:
curl -i http://127.0.0.1:8788/v1/containers
# Expected: HTTP 401

# Browser inventory routes should also reject unauthorized requests:
curl -i http://127.0.0.1:8086/api/server/containers
# Expected: HTTP 401

# Run local tests:
python -m pip install -r requirements-dev.txt
bash scripts/test.sh
```

## Local service security recommendations

The shipped script is a **pilot launcher**, not an unattended production installer. For long-running service deployment:

- Use distinct OS users: unprivileged control-plane user with no `docker` group, and a dedicated host-agent user with only the required group/socket access.
- Use separate systemd units, `EnvironmentFile` outside the repository, strict permissions and restart policies.
- Confine the agent with systemd hardening and a host firewall; remember that Docker socket access is root-equivalent even if the container mount is marked read-only.
- Restrict the user, service account, and Tailscale ACL/Grants. Retain MFA-enabled SSH access.
- Log successful/failed owner sign-ins and agent connectivity externally until the audit module is introduced.
- Backup `state/panel.db` consistently and store `.env` securely; it contains a credential.
- Review and pin Python dependencies before a production release.

## Diagnostics

| Symptom | Likely cause | Next check |
|---|---|---|
| `Host agent unavailable` | Agent down, wrong token, or Docker access failure | Confirm `AGENT_TOKEN` matches in both services and agent is on loopback |
| `Docker Engine is not reachable` | Socket missing or agent lacks permission | Check Engine running and UNIX socket permission; do not expose daemon TCP |
| Login rejected | No admin, incorrect password, Origin mismatch | Run offline bootstrap once, verify `PANEL_PUBLIC_ORIGIN` |
| Login works but reload redirects to login | Cookie `Secure` enabled on plain HTTP | Use HTTPS with secure cookies or local HTTP pilot setting |
| Blank screen | Asset error | GET `/assets/app.js` and `/assets/styles.css`; check browser console |

## Change management

There is **no automatic server installation, public deployment, DNS update, GitHub push or release** performed by the downloadable project. Those are separate user-authorized operational steps.