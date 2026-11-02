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
