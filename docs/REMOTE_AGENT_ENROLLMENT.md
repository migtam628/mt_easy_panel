# MT Panel v0.3.0-dev — private, outbound-only agent enrollment

**Security stage:** Agent identity and signed heartbeats. This does NOT activate
remote Docker monitoring or remote Docker command execution. It does not expose
ports on the enrolled server and does not contact any host address from the
control plane. Do not treat a "paired" identity as a Docker-managed host.

## Architecture

1. An authenticated owner creates a saved server identity in the **Servers**
   dashboard. The ID is a random 32-hex-character database key.
2. The owner opens **Identity → Create one-time enrollment code**. MT Panel
   creates a 256-bit random code, stores **only its SHA-256 hash**, and displays
   the code once. It expires in 10 minutes. A newly created invitation
   invalidates any earlier unused invitation for that server.
3. On a separate Linux server **already joined to the same Tailscale tailnet**,
   an operator starts the outbound enrollment CLI. It creates an Ed25519
   private key in a mode-0600 file, signs an enrollment nonce, and sends the
   one-time code and public-key proof over verified HTTPS to the MT Panel
   tailnet hostname on port 8443. No Docker socket access is needed.
4. MT Panel verifies the invitation, server ID, signature and expiration,
   atomically consumes the code, stores the public key, and marks identity
   `paired`. An audit event records this event without any secret.
5. The agent may send **signed, monotonic heartbeats** on demand. Clock skew
   over two minutes, signature mismatches and repeated sequences are rejected.
6. The dashboard distinguishes `never_seen`, `recent` (signed within 180
   seconds), `stale` and `revoked` heartbeat status. These are **cryptographic
   identity signals, not proof that Docker is healthy or even installed**.
7. The owner may **revoke** the identity and pending invitations from the
   Servers dashboard. The previous private key no longer authorizes heartbeats.

Identity credentials are scoped to each server and are never stored as
plaintext bearer tokens in SQLite. The control-plane API has no remote-target
URL field and cannot connect to an arbitrary server.

## Enrollment example (operator-run, not a background process)

First, establish private Tailscale connectivity between the agent host and the
MT Panel VPS, and allow HTTPS 8443 through the relevant tailnet Grants/ACLs.

On MT Panel: **Servers → Add server → Identity → Create code.** Keep the code
private; it must not be pasted into chat, a GitHub issue, log or script.

On the target Linux agent server, with a *trusted* checkout of MT Panel code
and Python virtual environment containing `requirements.txt`:

```bash
mkdir -p -m 700 ~/.local/share/mt-panel

.venv/bin/python -m agent.enroll --enroll \
  --control-url https://moobee-stream-vps.tail08e9d7.ts.net:8443 \
  --server-id SERVER_ID_FROM_MT_PANEL \
  --key-file ~/.local/share/mt-panel/agent-ed25519.pem
```

The command **prompts for the one-time code without echoing it**. Use the exact
server ID from the dashboard, not the display name. The private key remains on
the enrolled server and must not be committed to GitHub or copied into chat.

To verify signed liveness manually:

```bash
.venv/bin/python -m agent.enroll --heartbeat \
  --control-url https://moobee-stream-vps.tail08e9d7.ts.net:8443 \
  --server-id SERVER_ID_FROM_MT_PANEL \
  --key-file ~/.local/share/mt-panel/agent-ed25519.pem
```

The API and CLI refuse unencrypted HTTP, public-domain targets, public IPs,
URL credentials, and redirects. No Tailscale Serve route is changed by
enrollment. The control plane remains at the existing private HTTPS endpoint.

## Optional scheduled heartbeat — not installed automatically

After manually enrolling an identity on a **separate, trusted Linux machine**,
operators can run the one-shot heartbeat with a private JSON configuration.
Run these commands on the remote agent as an unprivileged user. Do **not**
enable the timer on the MT Panel control plane just to simulate a remote host.

Create `~/.config/mt-panel/heartbeat.json` (mode 0600) with this exact shape,
using the real server ID and an absolute file path for that user's private key:

```json
{
  "control_url": "https://moobee-stream-vps.tail08e9d7.ts.net:8443",
  "server_id": "YOUR_32_CHARACTER_SERVER_ID",
  "key_file": "/home/YOUR_USER/.local/share/mt-panel/agent-ed25519.pem"
}
```

Use `mkdir -p -m 700 ~/.config/mt-panel` and
`chmod 600 ~/.config/mt-panel/heartbeat.json`. No invitation code is stored
in this file. The application verifies the config file's owner and privacy,
the absolute key path, and the Tailscale-only HTTPS origin.

To validate without a network request and then send one heartbeat manually:

```bash
cd ~/mt_easy_panel
.venv/bin/python -m agent.heartbeat --check \
  --config ~/.config/mt-panel/heartbeat.json
.venv/bin/python -m agent.heartbeat --once \
  --config ~/.config/mt-panel/heartbeat.json
```

An optional **systemd user timer** is provided but never installed/enabled
automatically. The unit assumes the remote user's code checkout is at
`~/mt_easy_panel`, with its Python virtual environment in `.venv`.
After validating a manual heartbeat, the operator may opt into the timer:

```bash
mkdir -p ~/.config/systemd/user
install -m 644 deployment/systemd-user/mt-panel-heartbeat.service \
  ~/.config/systemd/user/mt-panel-heartbeat.service
install -m 644 deployment/systemd-user/mt-panel-heartbeat.timer \
  ~/.config/systemd/user/mt-panel-heartbeat.timer
systemctl --user daemon-reload
systemctl --user enable --now mt-panel-heartbeat.timer
systemctl --user list-timers --all
```

This timer runs under the user's own account, not Docker's group or root.
It issues an outbound heartbeat about every minute. Whether user timers
persist across logout or reboot depends on the host's user-session settings;
do not enable linger without understanding the resulting service persistence.
To disable this optional feature:

```bash
systemctl --user disable --now mt-panel-heartbeat.timer
```

The heartbeat sequence counter is saved beside the private key in a private
`*.sequence` file. It is locked, fsynced before network submission and
continues increasing across process restarts and backward wall-clock changes.
A lost request can skip a number, but an old number cannot be replayed.

## Optional signed, read-only Linux host reports

An enrolled Linux agent can send one system-health snapshot using:

```bash
cd ~/mt_easy_panel
.venv/bin/python -m agent.heartbeat --report \
  --config ~/.config/mt-panel/heartbeat.json
```

This reuses the owner's Tailscale HTTPS origin and enrolled Ed25519
identity. Only hostname, Linux kernel release, CPU count, RAM, total/free
root disk capacity and uptime are accepted. IP addresses, environment
values, file paths, Docker objects, commands and arbitrary extra fields
are rejected. The controller never connects to the agent.

The owner may view the last accepted report at
**Servers > Identity > Signed host health**. The dashboard distinguishes
recent from stale telemetry; it does not claim Docker connectivity.
The optional supplied systemd user timer still sends heartbeat-only
requests by default. No host report is scheduled automatically.

## Current limits

- Heartbeat CLI supports manual one-shot use and an **optional, uninstalled**
  systemd user timer template. Nothing schedules traffic without operator action.
- A heartbeat verifies the agent key and freshness only; it does **not**
  check Docker availability, report CPU/memory metrics, or attest the physical
  identity of the machine.
- Pairing by invitation relies on the operator giving the code to the
  intended host. Tailnet Grants must restrict which hosts can reach MT Panel.
- Revocation prevents future signed heartbeats; it does not automatically
  remove private keys from remote disks. Rotate keys through re-enrollment.
- No remote API proxy, SSH executor, Docker commands, deployments or container
  mutations have been added.
- Do not invite arbitrary agents into your production management environment
  before confirming the correct Tailscale access policies.

## Owner-only control-plane API

- `POST /api/catalog/servers/{id}/invites` — one-time code creation.
- `GET /api/catalog/servers/{id}/identity` — public fingerprint and last seen.
- `POST /api/catalog/servers/{id}/revoke` — revoke identity/invitations.
- `POST /api/agents/enroll` — one-time credential + Ed25519 possession proof.
- `POST /api/agents/{id}/heartbeat` — signed timestamp and monotonic sequence.

Invite and revoke actions require administrator login and exact same-origin
requests. Agent requests require code or cryptographic signature verification,
not administrator cookies. Events are auditable in the Activity page.

## Next gate

Before implementing remote Docker inventory, require real-host validation on a
disposable remote host, private transport hardening, agent privilege separation,
per-host authorization and revocation tests. The existing production Docker
Engine must not be used to develop write operations.
