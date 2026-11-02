# Phase 2 Build Backlog — MT Panel v0.3.6-dev

Order matters: host identity and API hardening precede all write actions.

| ID | Priority | Deliverable | Acceptance criterion |
|---|---|---|---|
| MTP-01 | P0 | PostgreSQL schema and migrations | Isolated migration test; non-destructive import of Phase 1 owner data |
| MTP-02 | P0 | Durable audit log | **In progress (v0.1.2):** persistent bootstrap/login/logout audit completed; configuration/job audit, retention, and PostgreSQL migration remain |
| MTP-03 | P0 | Trusted agent enrollment | **Partial v0.3.1-dev:** one-time invitation, Ed25519 proof, durable heartbeat sequence, optional user timer, revocation; remote inventory, host attestation and deploy execution pending |
| MTP-04 | P0 | Server registry | **Partial v0.3.4-dev:** owner-scoped fleet, signed host-health history, on-demand stale/low-disk warnings, revocation cleanup; remote Docker inventory, host attestation and agent-host policy pending |
| MTP-05 | P0 | Project/resource ownership | Partial: owner-scoped project/environment/draft persistence, write audit, API/UI; multi-user pending |
| MTP-06 | P0 | Declarative service manifest | Partial: digest-pinned image drafts, strict resource caps, read-only rootfs; Compose and volume policy pending |
| MTP-07 | P0 | Compose normalization + policy | **Partial:** static restrictive YAML preview with reject rules; real Compose normalization/integration and Docker tests pending |
| MTP-08 | P0 | Queued job runner | Idempotency key, per-host locks, lease expiry, bounded retries, cancellation semantics |
| MTP-09 | P0 | Signed agent job execution | Only approved job type/id and validated manifest; no arbitrary shell/API passthrough |
| MTP-10 | P1 | GitHub repository source | GitHub App/deploy key with minimal scopes; immutable commit checkout; webhook replay validation |
| MTP-11 | P1 | Buildx/image registry | Bounded isolated builds, SBOM, provenance, pinned digest, secret-safe build context |
| MTP-12 | P1 | First controlled test deployment | Staging host deploys an unprivileged stateless sample, health gate passes, rollback tested |
| MTP-13 | P1 | React + TypeScript dashboard | Replace Phase 1 vanilla JS while preserving API contract and accessible UI |
| MTP-14 | P1 | CI/integration test harness | Docker test fixture, agent policy tests, migrations, failure injection and signed releases |

## Hard gate before first write operation

A production write action may not merge unless it has: (1) server-side owner authorization, (2) durable audit events, (3) a bounded declarative manifest, (4) agent-side enforcement, (5) idempotency/locking, (6) health validation, (7) rollback procedure, and (8) tests against a **disposable** Docker host. Existing production containers must remain untouched during development.

## Pilot operational UI — completed v0.3.5-dev

The Monitoring, Deployments, and Settings sidebar screens now offer
non-destructive reads. Monitoring presents existing live local agent
overview and signed fleet signals, not historical Docker metrics or
automated alert delivery. Deployments lists metadata-only draft definitions
and explicit blockers, **never executable jobs**. Settings discloses
owner-visible policy, not secrets or live configuration mutation.

**Still blocked:** remote Docker collection and all container writes require
a separate disposable test host, privilege separation, agent identity
binding and the eight deployment safety criteria above. Monitoring
notifications, MFA, multi-user RBAC and real deployment jobs are not shipped.


## Safe release lifecycle — completed v0.3.6-dev

Staging prints an exact commit-pinned promotion sequence. An operator may
read all staged/installed/source revisions with a no-write release-status
check. The live verifier now distinguishes "staged but not promoted" from
a failed running application. Live container writes and agent remote
management remain excluded until tested on an isolated Docker host.
