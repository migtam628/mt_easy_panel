# Phase A: local deployment executor — LAB PILOT ONLY

Version: **0.3.8-dev**. This document concerns the **disposable-host pilot**
only, not production execution. The production MT Panel VPS remains a
read-only Docker control plane unless an operator **separately** provisions
an isolated test host and explicitly enables the lab execution gates.

## Trust boundaries

| Boundary | Verification | Explicitly not allowed |
|---|---|---|
| Browser -> FastAPI | Existing owner session + exact Origin, separate explicit queue/run approval | Unauthenticated/CSRF requests; arbitrary host URLs |
| FastAPI -> local agent | Loopback-only configured target, existing bearer **plus distinct HMAC-SHA256 job signing key**; signed fixed-schema action, timestamp +/-30 seconds, persistent nonce consume | Generic Docker proxy, arbitrary CLI, remote SSH, browser access to agent key |
| Local agent -> Docker socket | Small allowlist only; strict Pydantic draft; 32-hex job/draft IDs; new lab-owned container name and ownership labels | Touching foreign containers, raw Docker API paths, host mounts, published ports, networks, exec, shell, image pull, privileged mode |
| Owner SQLite -> execution | Transactionally audited owner-scoped job; single active/unresolved host lease; immutable manifest snapshot | Reusing idempotency keys for different requests; automatic replay after uncertain outcome |
| Remote identities | Existing Ed25519 enrollment, monotonic sequence and revocation **unchanged** | Remote Docker execution or conflating signed host health with execution approval |

## Safety model

The default remains **off**:
`PANEL_LOCAL_EXECUTION_ENABLED` and `AGENT_LOCAL_EXECUTION_ENABLED`
are unset/false. These are **separate gates**; simply upgrading the production
control plane never enables Docker writes.

An operator preparing a **disposable isolated host** must independently
provision the local agent's persistent replay DB directory under
`/var/lib/mt-panel-agent` owned only by the agent OS user; configure both
services with *distinct* `AGENT_TOKEN` and `AGENT_EXECUTION_KEY` (32+
characters); explicitly set both lab enable flags; set
`PANEL_LOCAL_SERVER_ID` to the ID of a local server record owned by the
logged-in owner; and set the acknowledgement variables
`PANEL_EXECUTION_LAB_ACK` and `AGENT_EXECUTION_LAB_ACK` to
`I_ACCEPT_DISPOSABLE_HOST_ONLY`. **Do not apply these settings to
mttech-vps, which hosts production applications.** No installer or upgrade
script sets these flags, creates the agent replay directory or modifies
systemd, Docker networks, Caddy or ports 80/443 automatically.

The disposable-host agent is still a privileged trust component because
the Docker socket is root-equivalent. Signed HMAC requests are scoped to
local operations and are **not** the Ed25519 remote-host identity protocol.
The agent consumes each signed nonce to its private SQLite DB *before* any
Docker write. Invalid signatures, expired timestamps, replayed nonces
(including after agent restart) and replay DB failures prevent execution.

The first write-capable adapter creates only
`mtpanel-lab-<job_uuid>` candidates: digest-pinned image **already present
locally**, mandatory baked-in Docker HEALTHCHECK, non-root UID 65534,
read-only root filesystem, no capabilities, no-new-privileges, bounded
CPU/RAM/PIDs, network **none**, zero published host ports, no mounts or
secrets. All create/start/stop/restart operations are hard-coded and only
target a container carrying matching MT Panel lab job/draft labels.
There are no delete, inspect-secret, image-build or general-purpose shell
commands exposed.

The first health gate watches Docker's baked-in image health status for
a bounded period. If the candidate becomes healthy, the job reaches
`HEALTHY`, but **no traffic is switched**. If it fails, the agent
stops only the new labeled candidate and marks `ROLLED_BACK`; the prior
healthy application and its digest were never modified. This is **candidate
rollback**, not yet rollback of a deployed service revision or volume state.
If the stop cannot be confirmed, the job is `NEEDS_REVIEW`; it must not
claim rollback success.

## SQLite state flow

- Owner creates a job from a saved validated draft:
  `POST /api/deployments/drafts/{draft_id}/jobs` with an idempotency key.
  This creates `DRAFT` only and works even when execution is disabled.
- Explicitly queue an existing DRAFT:
  `POST /api/deployments/jobs/{job_id}/queue` with authenticated session,
  matching Origin, and `X-MTPanel-Approval: DEPLOY_TO_DISPOSABLE_HOST`.
  Requires server binding to the configured lab host and execution enabled.
- Explicitly run it:
  `POST /api/deployments/jobs/{job_id}/run` with the same approval and
  same-origin session. This claims a single SQLite lease, then makes one
  signed local agent call. No scheduled auto-run worker is installed.
- Read status/events:
  `GET /api/deployments/jobs` and `GET /api/deployments/jobs/{job_id}`.
  The Deployments UI shows a bounded read-only recent job table, without
  actions to approve or execute jobs. Responses omit agent bearer tokens,
  HMAC keys, lease tokens and raw Docker inspect or environment records.
- State path:
  `DRAFT -> QUEUED -> RUNNING -> HEALTHY | ROLLED_BACK | NEEDS_REVIEW`.
  SQLite commits each transition and audit event atomically. Idempotency
  keys bind to owner/draft/manifest/server and original mode.
- A lost agent response or process crash may leave a candidate in Docker:
  **do not retry automatically**. The job is `NEEDS_REVIEW` or remains
  `RUNNING` with an expired lease; either condition blocks subsequent host
  jobs pending explicit inspection. Lease expiry is **not** automatic
  permission to retry.

## Validation

CI exercises:
- API authentication and strict Origin/approval gates.
- Draft-only default, replay-safe idempotency, SQLite audits and exclusive
  host leases.
- Persisted HMAC nonces and rejected signatures/tampered actions.
- Fake Docker operations asserting no published ports/mounts/capabilities,
  non-root execution, exact ownership-label checks, healthy candidate and
  stopped failed candidate.
- Failure uncertainty and refusal to act on foreign containers.

**Not verified:** Docker Engine integration on a real disposable host,
resume/reconcile after a crash, reliable health for arbitrary images,
registry import/pull, cutover to production network/routing, actual
previous-digest rollback, persistent volume handling, multi-server
deployment, privileged-container security evaluation, a security audit
or production release approval.

## Next implementation gates

1. Add explicit reconciliation API for `NEEDS_REVIEW` and expired leases,
   inspecting only exact owned container names and labels; make reconciliation
   auditable and fail-closed.
2. Run failure-injection Docker integration tests against a separate,
   throwaway Tailscale-enrolled Linux VM; verify the agent systemd sandbox
   and container isolation before any live execution approval.
3. Build the real service revision/cutover model: previous pinned digest,
   staging health, atomic routing handoff and tested reverse rollback,
   without touching existing Caddy unless an operator opts into a
   dedicated adapter.

No Git/Buildx/Compose, database templates, domain/TLS changes or
multi-server writes are part of this release.

## v0.3.9 recovery: observation is not permission to retry

A lab agent may serve authenticated `GET /v1/lab/candidates/{job_id}`
with `draft_id` and the immutable `image_digest` from the saved job.
Its allowlist inspects one deterministic lab candidate name, validates
exact ownership labels and image, and returns only a bounded state enum
with `safe_to_retry=false` and `traffic_switched=false`. It never
reveals image metadata, mounts, secrets or raw Docker inspect JSON.

Owner `GET /api/deployments/jobs/{id}/recovery` is purely observational.
The explicit `POST .../reconcile` requires session, exact Origin, lab
enablement, configured local host binding and
`X-MTPanel-Approval: INSPECT_AND_HOLD`. An expired RUNNING job or an
existing NEEDS_REVIEW job receives a durable observation audit; the
result remains NEEDS_REVIEW. A current RUNNING lease is not interrupted.
Neither a missing candidate nor a healthy candidate clears the host lock
or authorizes another execution. Failed inspection returns unavailable,
not a healthy or absent guess.

For safely keeping the *production dashboard* current for testing, run
`bash scripts/vps-test-sync.sh --check` or
`bash scripts/vps-test-sync.sh --stage` on the installed VPS. Stage mode
only fast-forwards the Git checkout and builds/reuses a tested stage;
a human still approves exact SHA-pinned activation separately. Never
set lab execution flags on the production VPS.

## v0.3.10 — Real Engine integration (ephemeral runner)

The dedicated GitHub Actions job `ephemeral-docker-lab` on GitHub-hosted
Ubuntu runs `tests/integration/test_real_docker_lab.py` only on
reviewed-main pushes. The test fails closed unless GitHub reports an
ephemeral hosted Linux runner and the dedicated one-time lab test
environment flag is present. It does **not** run from normal VPS
`pytest` or from the panel service.

The harness builds two tiny BusyBox fixtures with baked-in HEALTHCHECKs,
pushes them to an ephemeral registry exposed solely at
`127.0.0.1:15000`, pins the resulting immutable registry digest,
then invokes the real local Unix-socket Docker adapter. Healthy, failed
and foreign candidate flows are tested, plus signed agent action/replay.
No existing VPS data, reverse proxies, ports 80/443, or Tailscale
configuration is used.

A real Docker failure exposed a stop-timeout issue; the lab adapter
now allows a longer, bounded wait on only STOP, without relaxing the
GET-only inventory timeout. The agent independently inspects and
validates ownership/Running=false before marking candidate rollback.
An unconfirmed stop still requires manual operator review: never retry
automatically, mark healthy, unlock the host or re-route live traffic.

**Still open:** prove same guarantees on a separately provisioned
throwaway Tailscale VM with restrictive systemd services; audit complete
host ownership/fencing on real host failures; design service revisions
and true previous-image cutover/rollback. The current VPS stays
read-only.
