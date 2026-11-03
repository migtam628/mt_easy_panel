# Architecture Decision Records

## ADR-001 — Separate control plane and host agent
**Decision:** UI/API cannot open the Docker socket. Docker GET operations run only in host-local agent.
**Why:** Docker socket authority is root-equivalent; exploit of web API must not trivially imply host root access.
**Tradeoff:** Agent remains a sensitive service; secure pairing, access restrictions, patching and later mTLS are mandatory.

## ADR-002 — Zero-write operations in Phase 1
**Decision:** API exposes inventory and log reads only; Docker Engine adapter is a small hard-coded GET allowlist.
**Why:** Existing production container availability takes priority over feature parity. Safely adding writes requires project ownership, authorization, audit, idempotency, health gates, rollback and recovery tests.

## ADR-003 — Python/FastAPI implementation with browser-native frontend for the first runnable milestone
**Decision:** Simple API/agent stack plus HTML/CSS/JS dashboard. React/TypeScript UI planned behind stable API contracts.
**Why:** Fast bootstrapping, low resource footprint, straightforward unit testing and no initial frontend build tooling.
**Tradeoff:** Frontend code must be migrated into reusable React components as the UI grows; do not let Phase 1 become an unstructured long-lived SPA.

## ADR-004 — Private-only first, no reverse-proxy takeover
**Decision:** Default agent and dashboard bind loopback. The current VPS dashboard is accessed using private Tailscale Serve HTTPS on port 8443 only; the host-local Docker agent remains loopback-only. Never enable Funnel or take over public ports.
**Why:** A host with existing Caddy, Web services, and production ports should not be disrupted during bootstrap.

## ADR-005 — SQLite now, PostgreSQL later
**Decision:** SQLite stores the single owner and sessions in Phase 1. PostgreSQL is the intended production multi-tenant metadata DB.
**Why:** Eliminate external state services for test deployment; introduce managed migration on Phase 2.
**Caveat:** SQLite is not a shared clustered session store.

## ADR-006 — No Easypanel proprietary code or assets
**Decision:** Feature behavior may be referenced from public docs, but all source code and UI are original, with independent schemas/routes and branding.
**Why:** Clear provenance, user ownership, freedom to redesign.

## ADR-007 — Lab-only signed local deployment commands through the existing isolated agent

**Status:** Experimental, v0.3.8-dev; **not approved for existing production
VPS execution**. Implements only an isolated, unrouted candidate deployment.

**Context:** Phase 1 deliberately prohibited Docker writes. The desired PaaS
requires carefully scoped deployment operations without giving the FastAPI
control plane the Docker socket, allowing browser-controlled Docker endpoints,
or risking unrelated production workloads.

**Decision:** Preserve the unprivileged FastAPI controller and existing
loopback-only, GET-allowlisted Docker inventory agent. Add a *separate*
allowlist of fixed lab actions: create a **new**, deterministic
`mtpanel-lab-<job_id>` candidate from an immutable image digest, and
start/stop/restart **only** a candidate with matching ownership labels.
The lab writer never accepts a Docker path/URL/command from the caller,
never publishes host ports, never attaches a network or mount, and never
touches an unlabeled or mismatched container.

Local requests require the existing loopback bearer token plus a **separate,
distinct HMAC key** over the exact strict request, a timestamp freshness
window and a durable SQLite nonce consume on the agent. This key **does not
replace** remote Ed25519 enrollment, heartbeats, replay counters or revocation;
remote identities cannot authorize these local writes. The local agent
must be explicitly opted into disposable-host execution by separate
environment gates; the default remains read-only.

Owner-controlled draft -> SQLite DRAFT -> explicitly approved QUEUED ->
exclusively leased RUNNING -> HEALTHY/ROLLED_BACK/NEEDS_REVIEW. The control
plane audits each state transition in its SQLite DB; the agent also
persists accepted signed action nonces and logs operation results. No
unattended runner or automatic retry is installed. An uncertain result
blocks subsequent local host jobs pending an operator reconciliation.
Control plane shutdown does not stop Docker containers.

**Rollback scope:** A failed candidate is stopped after a bounded Docker
image HEALTHCHECK. No service traffic is switched, and the previous
workload/image is never changed. This is candidate rollback only; production
previous-digest rollback still needs a separate service revision and
cutover design.

**Tradeoffs / hard blockers:** A Docker socket remains root-equivalent to
the agent's OS identity; HMAC alone cannot attest the physical host.
The first release does not support remote agent write execution, automatic
crash reconciliation, actual host integration verification, deployment
update cutover, volume recovery, or general Compose. Enabling writes on
the existing production VPS is specifically unsupported without isolated
host tests and a subsequent authorization decision. See
[Phase A execution guide](PHASE_A_LOCAL_EXECUTION.md).

## ADR-008 — No automatic recovery from uncertain Docker writes

**Status:** Experimental, v0.3.9-dev. Production VPS remains read-only.

**Decision:** A controller can inspect a pending lab job only through the
preconfigured loopback agent, not a Docker socket or user-supplied URL. The
agent requires the existing bearer, is lab-gated, inspects exactly one
deterministically named candidate, verifies its immutable image digest and
job/draft ownership labels, and returns only a small canonical observation
(`absent`, `stopped`, `running_healthy`, `running_unhealthy`,
`running_starting`, `running_unknown`). It never returns raw Docker
inspect results or secrets. Remote Ed25519 trust remains separate and cannot
authorize local Docker writes.

The owner-session GET recovery route only reads; a separate same-origin,
explicitly approved `INSPECT_AND_HOLD` POST records the observation and,
when a RUNNING lease has expired, moves it to NEEDS_REVIEW. It is atomic
with the SQLite audit event. It **never** releases the host lease,
automatically retries the Docker action or declares a successful deployment
based on missing or stopped containers. A still-active or absent lease
cannot be arbitrarily invalidated. Identity mismatch and agent errors fail
closed. Future manual resolution must have a stronger audited proof/approval
process and disposable-host validation.

**Consequence:** A lost response or controller crash can block lab
deployments until an operator reviews the candidate externally. This
deliberate availability tradeoff preserves isolation and prevents unintended
replay of root-equivalent Docker operations. Existing production workloads
continue running independently of controller downtime.

## ADR-009 — Real Docker integration uses ephemeral CI, never production

**Status:** Validated disposable-runner experiment, v0.3.10-dev.
Production Docker writes are **not** approved.

**Context:** Fake Docker fixtures are insufficient to prove actual Engine
behavior (especially graceful stop timeouts, health state timing and
digest resolution). A shared production VPS cannot be used to test
root-equivalent Docker write boundaries safely.

**Decision:** Run an additional, explicitly gated Docker Engine test job
on GitHub-hosted `ubuntu-latest` runners only after commits reach main.
The job has read-only repository permissions and no production secrets,
verifies the hosted-runner environment, and refuses machines with an
installed MT Panel private environment file. The test harness repeats
the identity/ephemerality gates, uses a temporary local registry on
`127.0.0.1:15000`, publishes only disposable fixture images, and creates
only random `mtpanel-lab-<uuid>` candidates. Cleanup is confined to
those exact fixture names. The controller and real agent code do **not**
gain Docker CLI, arbitrary command execution or network control.

An observed Docker stop exceeded the original 4-second HTTP timeout;
the write adapter now gives only the exact allowlisted stop request a
bounded longer timeout. Successful rollback requires a subsequent
ownership-verified inspect reporting `Running=false`. Ambiguity raises
an error, allowing the control plane to retain the unresolved job fence.
Control-plane downtime never stops already-running workloads.

**Limits:** This proves the restricted candidate path on a disposable
CI runner, not production host/kernel policy, independently isolated
remote enrollment, service revision traffic cutover, volume recovery,
manual release of unresolved locks, or end-to-end rollback of a
previous live image. The live VPS remains explicitly write-disabled.

## ADR-010 — Immutable review references are not host-release authority

**Status:** v0.3.11-dev, default read-only pilot; no host clearance.

**Context:** The v0.3.9 fail-closed design rightly blocks uncertain Docker
jobs as NEEDS_REVIEW indefinitely, but operators need inspectable evidence
packets and an auditable review history before any future manual release
protocol can be considered.

**Decision:** Create a separate SQLite `local_job_review_evidence`
table. Owner-only review packet GET reads only existing ledger and audit
transitions. It hashes a deterministic canonical representation of the
immutable manifest SHA-256, exact job/draft/server identity, job state,
lease, attempts, update timestamp and recorded transitions. It returns
no secrets or raw Docker inspect. Review POST requires owner session,
strict Origin, explicit RECORD_REVIEW_EVIDENCE header, a current packet
fingerprint, allowlisted reason code, and an operator-supplied 64-hex
SHA-256 evidence reference. The transaction checks state and freshness,
is idempotent for exact duplicates, and atomically audits new references.

**Trust boundary:** The evidence reference is user-supplied metadata,
**not** a signature or independent Docker host attestation. The endpoint
cannot invoke the agent, mutate jobs, clear or alter host leases, approve
remote execution or change traffic. Neither a single reference nor
multiple reviews establish safe-to-retry. Future unlock decisions require
independent attestation/lease fencing and separate implementation/test
approval on a disposable host.

**Consequences:** The operator can inspect a stable, attributable case
record while unresolved host work remains blocked. SQLite/backup data
grows modestly per operator-submitted review; bounded packet events and
small fixed input schemas limit exposure.

## ADR-011 — Migrate the UI to Next.js static export, not the backend

**Status:** Experimental v0.3.12-dev; legacy FastAPI UI remains default.

**Context:** A growing self-hosted PaaS needs maintainable routed
components, TypeScript and more consistent design. However, running
Next.js as a second production server or replacing FastAPI's established
cookie/session and origin authority introduces avoidable complexity and
trust boundaries.

**Decision:** Create a separate Next.js 16 App Router + TypeScript
frontend under `frontend-next/`, statically exported to the fixed
`/next-preview` base path. All runtime data are fetched by client
components from **same-origin** `/api/` after authenticating through
the existing FastAPI HttpOnly, Secure (HTTPS) and SameSite=Strict cookie.
No Next.js API routes, middleware/proxy, server actions, new auth
provider, socket access, secrets or server-side dynamic rendering are
introduced. FastAPI and SQLite remain the sole business logic and
audit systems; Ed25519 enrollment and the local allowlist-only agent
remain untouched.

Static assets are served by the existing FastAPI process only if
`PANEL_NEXT_PREVIEW_ENABLED=true` **and** a nonsymlinked prebuilt
export exists. This changes neither the existing `/` route nor
systemd, Caddy, Tailscale, ports 80/443, or container privileges.
A missing bundle fails closed during enabled startup. CI builds with
Node 22 in a disposable runner and uploads a SHA-labelled,
per-file SHA-256 manifest; an explicit importer validates stage SHA
and content hashes before copying assets into an *unactivated* stage.
The artifact hashes detect corruption and stale bundles but are **not**
independent cryptographic attestation of the artifact publisher.
Operators must download from the trusted GitHub Actions run.

**Tradeoffs/gates:** Static export omits server-only Next features;
users must authenticate and load private data client-side. We avoid a
new Node production service while preserving reliable failover. The
Next UI is an incomplete parallel preview, not a replacement. Before
switching the root route: ensure full feature parity, frozen and
audited dependency lock, authenticated browser/CSRF testing, trusted
artifact provenance, accessibility and controlled fallback/rollback.
