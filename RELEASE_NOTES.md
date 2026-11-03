### v0.3.12-dev follow-up — Unprivileged Next preview file permissions

- Fixed static CI preview import: the temporary validated export is kept
  private during copying but published with directory mode `0755`, while
  static asset files stay root-owned and non-writable (`0644`). This allows
  the existing `mtpanel` systemd user to traverse `frontend-next/out`
  after stage promotion. Previously the root-created temporary directory
  retained `0700`, potentially preventing FastAPI startup when
  `PANEL_NEXT_PREVIEW_ENABLED=true` was selected.
- Added regression tests for output and nested-directory permissions.
- Existing installations can be repaired without rollback using
  `sudo chmod 0755 /opt/mt-panel/frontend-next/out` followed by restarting
  only `mt-panel.service` after verifying the static files exist.
- No new Docker privileges, service ports, proxy changes or Node runtime.

## v0.3.12-dev — Next.js static frontend migration foundation

- Added Next.js 16 App Router + TypeScript static frontend prototype,
  with working same-origin FastAPI cookie session integration.
- Implemented overview, container inventory, monitoring, servers,
  projects, deployment drafts with confirmation-only DRY-RUN metadata,
  audit activity and security settings.
- Added a separate Next.js CI build/typecheck and static route checks;
  no production Node daemon or Next route handlers introduced.
- Added default-off `PANEL_NEXT_PREVIEW_ENABLED` for static assets on
  the **existing private FastAPI origin**, under `/next-preview/`.
  The legacy `/` route and all authenticated APIs remain unchanged.
- Added CI static artifact, exact Git SHA + per-file hash manifest and
  a separately confirmed, add-only stage importer. No npm/root package
  installation on the production VPS.
- Added disabled-by-default preview authorization/route tests and
  bundle integrity/symlink/traversal regression tests.
- **Not complete:** Full previous UI parity, source lockfile and
  static artifact signing, browser e2e tests, and the production PaaS
  deployment/revision engine. No production Docker writes enabled.

## v0.3.11-dev — Fail-closed recovery evidence packet and owner review log

- Added deterministic SHA-256 job review packets from owner-scoped SQLite
  job state, manifest hash, lease, and full bounded transition history.
- Added append-only review references for unresolved NEEDS_REVIEW jobs.
  Explicit approval, exact origin/session, packet-freshness checking,
  strict reason codes and SHA-256 reference validation are mandatory.
- Duplicate submissions do not duplicate audits; state changes invalidate
  stale fingerprints. Owner isolation prevents cross-tenant access.
- Added a read-only Deployments UI evidence packet dialog showing history
  and untrusted operator references without revealing secrets.
- Added unit/API regression tests for missing approvals, bad origins,
  malformed or stale packets, duplicate evidence, owner isolation and
  preservation of the blocked host lock.
- **No manual host release, automatic retry, workload cutover or new
  Docker write capability is part of this release.** Existing production
  services, Tailscale configuration and ports 80/443 remain untouched.

## v0.3.10-dev — First successful real Docker Engine lab integration

- Added a strictly gated, **disposable GitHub-hosted runner** integration
  test. No self-hosted CI runner, production VPS, secrets, or existing
  deployment targets are used.
- Built immutable digest-pinned fixture images with healthy/unhealthy
  Docker HEALTHCHECKs through a temporary loopback registry (port 15000).
- Confirmed against a real Docker Engine: isolated health-gated container
  creation, candidate stop on unhealthy state, no host network/ports/
  mounts, no capabilities, non-root user, and continued operation of
  unrelated healthy candidates.
- Confirmed exact ownership enforcement against foreign same-name
  containers and separate HMAC/SQLite replay protection over the real
  agent write endpoint.
- Fixed a real-world Docker `stop` response timeout. The constrained
  stop path now uses a longer bounded socket deadline while read-only
  reads keep their short existing timeout.
- Added **post-stop re-inspection**: if the candidate still runs or is
  missing/unknown, the agent refuses to claim rollback, preserving
  NEEDS_REVIEW recovery semantics.
- Added regression tests for misleading stop acknowledgements and
  missing candidate states; documented test-host trust boundaries.
- This does not enable local Docker writes on the installed production
  VPS, change Caddy or Tailscale, or perform live service cutovers.
  Real previous-digest rollback and manual proof-based lock resolution
  remain incomplete.

## v0.3.9-dev — Fail-closed recovery inspections and safe staging sync

- Added allowlisted lab candidate GET inspection: validates exact job/draft
  ownership labels plus immutable pinned digest and exposes only sanitized
  state, never raw Docker data.
- Added owner-scoped recovery endpoint and explicitly approved, audited
  reconciliation of expired RUNNING / NEEDS_REVIEW jobs. Unknown outcomes
  continue to **lock** the host; no automated replay or release of locks.
- Added fail-closed behavior for offline agents, foreign same-name
  containers, malformed state and missing leases. Active leases may not
  be reconciled concurrently.
- Added `scripts/vps-test-sync.sh` for read-only sync checks or one-command
  fast-forward + idempotent staging without automatic activation.
- Added an explicit **Save dry-run** button for existing deployment
  drafts, using the same owner-authenticated, audited DRAFT job API.
  The browser exposes no queue/run action.
- Tightened post-promotion checks: refuse to certify production if the
  dashboard or local Docker agent has lab writes enabled or the policy is
  unknown.
- Expanded tests for authorization, recovery history, lease expiry,
  digest/ownership isolation and production-only read-only behavior.
- No remote execution, container deletion, workload cutover, proxy changes,
  automatic releases, Docker write enablement, or VPS modification.

## v0.3.8-dev — Phase A lab-only local deployment execution foundation

- Added a **disabled-by-default** local agent action endpoint and separately
  signed, strict-schema lab operations with HMAC replay protection and a
  dedicated private agent SQLite nonce/audit store. Existing Ed25519 remote
  agent trust remains intact.
- Added constrained Docker Engine write adapter for *new* MT Panel-labeled
  candidate containers only: pinned preloaded digest, no network, published
  ports, mounts or privileged flags; non-root UID and bounded resources.
  The candidate image must have a baked-in Docker HEALTHCHECK.
- Added owner-scoped SQLite draft/job queue, idempotency, immutable snapshot,
  explicit approval, per-host exclusive lease and atomic transition/audit
  events. An uncertain result enters NEEDS_REVIEW and holds the host lock.
- Added manual API operations: DRAFT creation, QUEUED approval and RUN,
  plus owner-only job list and events. The Deployments UI exposes a
  **read-only recent job status table**, not a write/execute button.
  No automatic background execution.
- Added basic candidate health gate: success marks HEALTHY; failure stops
  the new candidate and marks ROLLED_BACK **without any traffic switch**.
  Actual previous-digest production rollback is not yet implemented.
- Added strict agent ownership-label checks, deny-by-default tests,
  persisted nonce replay tests, fake Docker health/rollback tests, and job
  transition, origin, authorization and idempotency tests.
- Production verifier now checks the agent's effective lab-write flag is
  disabled. No existing systemd unit, Docker workload, reverse proxy,
  port 80/443, or existing installed VPS was changed.
- **Not production ready:** real disposable-host Docker integration,
  crash reconciliation and prior-digest cutover/rollback must pass first.

## v0.3.7-dev — On-demand local diagnostics and non-executing draft review

- Added read-only local Docker diagnostic triage from existing hard-coded
  agent GET inventory. Explicit Docker-reported unhealthy, restarting, and
  dead states are surfaced without treating every stopped container as an alert.
- Added disk capacity thresholds and clear offline/demo states; never imply
  health when the agent or metrics are unavailable.
- Added second monitoring table showing flagged local containers, alongside
  existing owner-scoped signed fleet summary. The UI only renders the first
  100 local diagnostics for performance; the API bounds parsing at 2,000.
- Added a per-draft **Review policy** dialog and owner-scoped GET endpoint
  that validates the stored strict digest-pinned, read-only service manifest.
  The review always denies execution/remote Docker access; no job is created.
- Strengthened live upgrade's unauthenticated endpoint checks for these
  new read-only routes, and added regression coverage for malformed data,
  authorization, offline agent handling and no new mutation methods.
- No host restarts, Docker writes, deployments, network reconfiguration or
  live VPS upgrade performed from GitHub.

## v0.3.6-dev — Safe release lifecycle, no Docker changes

- Added a read-only `scripts/release-status.py --check` to display
  current source, installed and available staged revisions separately.
- Updated staged upgrade output to print the exact new stage path, full
  SHA, and copyable, commit-pinned preflight/activation commands.
- Added optional `--expect-commit FULL_SHA` for both promotion preflight
  and activation, preventing accidental selection of a tested but older
  staging candidate.
- Fixed post-promotion verification's confusing failure cascade when
  invoked before activation. It now reports `NOT ACTIVE` once and exits
  with status 2, before checking future-only endpoints and schema.
- Added automated checks for wrong-stage refusal, status accuracy, and
  strict absence of service/container write operations.
- This release does not enable new API write endpoints, remote Docker
  inventory, background tasks or host changes. The previously staged
  v0.3.5-dev candidate is unaffected.

## v0.3.5-dev — Working Monitoring, Deployments preview and Security Settings

- Enabled Monitoring in the sidebar with an on-demand overview of local
  read-only Docker capacity and owner-scoped signed fleet warnings.
- Enabled Deployments as an explicit **non-executing** preparation ledger:
  saved draft image digests, project/environment context, optional server
  assignments and typed deployment blockers. No jobs or deployments are
  generated; remote Docker access remains disabled.
- Enabled Security Settings as a safe, owner-only read-only disclosure of
  effective security policies and planned missing protections (MFA/RBAC).
- Added dedicated authenticated APIs for these three pages with no new
  Docker write or job execution paths.
- Added integration tests for authentication, owner isolation, offline
  local host behavior, no sensitive metadata disclosure and forbidden
  mutation methods.
- Retained Tailscale-only browser access, loopback-only local Docker
  agent and the existing version-pinned, reversible staged promotion.

## v0.3.4-dev — Signed host-health history and on-demand fleet warnings

- Added bounded, chronological signed host-report disk history to SQLite,
  storing up to 288 entries per server with up to 200 queryable samples.
- Added owner-scoped `GET /api/catalog/servers/{id}/host-history` API.
- Added authenticated SVG disk-free trend to the server identity dialog.
- Added on-demand warnings for signed heartbeat/report staleness and disk
  thresholds (under 20% warning, under 10% critical).
- Revocation and new-key enrollment delete the old key's full report
  history and latest snapshot to avoid cross-identity telemetry.
- Added regression tests for accepted signatures, replay/tampering
  rejection, retention, owner isolation and warning thresholds.
- No remote Docker actions, background alerts or live-host configuration changes.

## v0.3.3-dev — Owner-scoped fleet monitoring and safe re-enrollment

- Added a read-only, owner-scoped `GET /api/fleet/summary` view of up to 500 saved
  server identities, with fresh/stale signed agent heartbeats and host reports.
- Servers dashboard now summarizes recent signed activity, last signed host
  report and disk-free percentage without suggesting remote Docker access.
- Fixed identity lifecycle handling: revocation and replacement enrollment
  clear old signed host telemetry atomically, so previous machine state cannot
  reappear under a newly enrolled key.
- Added integration tests for owner isolation, stale/fresh telemetry, revoked
  identity cleanup and bounded server results.
- No remote Docker inventory or commands, background polling, scheduled alerts,
  inbound agent listeners or live VPS changes.

## Read-only live deployment verification

- Added `scripts/verify-live-vps.py --check` to distinguish a staged checkout
  from the actual running dashboard version.
- Checks loopback dashboard/agent health, HTTP 401 on protected routes,
  read-only SQLite quick integrity/schema, and private Tailscale Serve 8443.
- Never imports application code (which initializes schema), authenticates,
  changes database content, contacts Docker, or restarts services.
- Includes regression tests with simulated HTTP, SQLite and Serve responses.

## v0.3.2-dev — Signed read-only Linux host summaries

- Added bounded strict host-report schema and Ed25519 signature domain.
- Included only host name, OS, CPU count, memory, disk totals and uptime.
- Verified ownership, freshness, timestamps, revocation and replay.
- Shared one durable sequence counter with agent heartbeats.
- Added opt-in `agent.heartbeat --report --config PATH` (one-shot).
- Added owner-only host-health readback in the Servers identity dialog.
- Added tests for signature tampering, extra fields and revocation.
- No remote Docker inventory, Docker writes, SSH keys or inbound agent ports.

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
