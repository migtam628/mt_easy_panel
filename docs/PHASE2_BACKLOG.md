# Phase 2 Build Backlog — MT Panel v0.2.0

Order matters: host identity and API hardening precede all write actions.

| ID | Priority | Deliverable | Acceptance criterion |
|---|---|---|---|
| MTP-01 | P0 | PostgreSQL schema and migrations | Isolated migration test; non-destructive import of Phase 1 owner data |
| MTP-02 | P0 | Durable audit log | **In progress (v0.1.2):** persistent bootstrap/login/logout audit completed; configuration/job audit, retention, and PostgreSQL migration remain |
| MTP-03 | P0 | Trusted agent enrollment | **Partial v0.3.0-dev:** one-time invitation, Ed25519 possession proof, signed heartbeats and revocation; persistent polling, TLS/host attestation and remote Docker reader binding pending |
| MTP-04 | P0 | Server registry | **Partial v0.3.0-dev:** owner-scoped identities, pairing metadata, manual heartbeat and revocation; remote inventory and offline/stale UI pending |
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
