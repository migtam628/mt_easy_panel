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
**Decision:** Default agent and dashboard bind loopback. Test access via SSH/Tailscale tunnel.
**Why:** A host with existing Caddy, Web services, and production ports should not be disrupted during bootstrap.

## ADR-005 — SQLite now, PostgreSQL later
**Decision:** SQLite stores the single owner and sessions in Phase 1. PostgreSQL is the intended production multi-tenant metadata DB.
**Why:** Eliminate external state services for test deployment; introduce managed migration on Phase 2.
**Caveat:** SQLite is not a shared clustered session store.

## ADR-006 — No Easypanel proprietary code or assets
**Decision:** Feature behavior may be referenced from public docs, but all source code and UI are original, with independent schemas/routes and branding.
**Why:** Clear provenance, user ownership, freedom to redesign.
