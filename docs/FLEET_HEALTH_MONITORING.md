# Fleet Health Monitoring — v0.3.4-dev

This feature records **self-reported, signed Linux host health**, not Docker
status. The only running installation verified by the operator was v0.3.3-dev.
New v0.3.4-dev code must be staged, tested and explicitly promoted separately.

## Source of truth and trust

1. On an enrolled Linux host, run
   `python -m agent.heartbeat --report --config ~/.config/mt-panel/heartbeat.json`
   to send a single outbound signed report to the Tailscale-only HTTPS
   control plane at port 8443.
2. The controller validates the per-server Ed25519 key, fixed schema,
   120-second clock-skew window and strictly increasing sequence.
3. A valid signed report updates the latest host snapshot, last-seen timestamp
   and an append-only **bounded disk history** in one SQLite transaction.
4. Fleet readings are owner-scoped, read from SQLite and never result in
   a connection from the control plane to the remote machine.

No host reports are fabricated. The dashboard may show "No signed report"
until a real, enrolled host sends one. Heartbeats are distinct from full
host reports: a signed heartbeat without a report does not add a history point.

## Data and retention

- At most 288 recorded signed history points per server; earliest points are
  discarded as new points arrive. There is no time-based archive guarantee.
- Server history API returns at most 200 of the newest points, in chronological
  order, and defaults to 96. Values include timestamp, disk-free percentage
  and uptime. No raw request, signature, key, IP address, path or secrets.
- Revoking an agent identity or enrolling a replacement key deletes **all**
  old snapshots and history for that server. Historic values never attach to
  the new identity.
- Existing older snapshots are **not backfilled** into history. New history
  starts at the first signed report accepted after this release.
- SQLite schema is additive, created on normal application startup. The
  upgrade tool snapshots database and the prior application before activation.

## Warning logic

Warnings are evaluated when the owner loads `GET /api/fleet/summary`:

| Condition | Warning | Severity |
|---|---|---|
| Paired identity, no signed heartbeat in last 180 seconds | No recent signed heartbeat | Warning |
| Paired identity, latest signed report older than 180 seconds | Signed host report is stale | Warning |
| Last signed disk report: under 20% free | Last signed disk report below 20% | Warning |
| Last signed disk report: under 10% free | Last signed disk report below 10% | Critical |

The 10% and 20% thresholds are **exclusive**. An exact 10% report receives
the warning tier. Revoked/unpaired hosts do not produce actionable warnings.
The status represents the **last signed self-reported metric**, not verified
real-time disk use. Stale reports retain their stale label.

Warnings are calculated on page load; they are **not** background alerts.
No email, push, SMS or other notification is sent. No cron, timer, Docker
agent, or systemd unit is enabled during installation.

## Owner-only APIs

- `GET /api/fleet/summary` — up to 500 server summaries with warning codes.
- `GET /api/catalog/servers/{id}/host-report` — latest signed host report.
- `GET /api/catalog/servers/{id}/host-history?limit=96` — bounded signed
  history with server-owner authentication and limits of 1 to 200.
- Agent's `POST /api/agents/{id}/host-report` remains authenticated by its
  Ed25519 key, timestamp and monotonic counter; random REST clients cannot
  create "healthy" data.

## Safe VPS rollout

On the existing VPS, use [the existing VPS upgrade runbook](EXISTING_VPS_UPGRADE.md)
to stage a **new commit**, not an older staging directory. Verify that the
printed stage's `.staged-commit` exactly matches the desired commit, run
`scripts/promote-vps.py --check --stage /opt/mt-panel-stage.EXACT_ID`,
then activate explicitly in a brief MT Panel-only maintenance window.

After activation:

```bash
python3 scripts/verify-live-vps.py --check --expected-version 0.3.4-dev
curl -fsS http://127.0.0.1:8086/api/health
```

The live dashboard remains private on
`https://moobee-stream-vps.tail08e9d7.ts.net:8443`. No unrelated
containers, Tailscale Serve routes or Caddy configuration should change.

## Not implemented

- Remote Docker inventory or write operations
- Active remote polling, automatic server enrollment or background health jobs
- Notifications, configurable thresholds, durable notification state
- Hardware-attested host identity or proof of physical machine integrity
- PostgreSQL-based history, long-term metrics warehouse or multi-owner RBAC

A disposable, Tailscale-connected Linux test host is still required before
remote Docker inventory can be considered for production use.
