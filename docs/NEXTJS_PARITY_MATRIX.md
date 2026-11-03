# MT Panel — Next.js / Original UI parity checklist

**Baseline:** The original public UI is defined by `web/index.html`, `web/app.js`,
and `web/styles.css`. All Next.js parity claims below refer to this source
baseline, not an independent screenshot evaluation.

**Status:** v0.3.14-dev source-mapped parity. The original dashboard at `/`
remains the live fallback; the Next.js UI remains an operator-enabled preview
at `/next-preview/`.

| Original page or workflow | Next.js mapping | API / action preserved |
|---|---|---|
| Overview | ✓ matching header, four metrics, containers | GET overview + containers |
| Servers | ✓ signed fleet inventory and identity modal | GET fleet, identity, report and history; owner-approved invite/revoke |
| Projects | ✓ list + manage modal | Register project, add environments/drafts, strict Compose validator |
| Containers | ✓ badges, ports, last-80-lines log viewer | GET containers and bound logs only |
| Images | ✓ read-only image inventory | GET images |
| Networks | ✓ read-only network inventory | GET networks |
| Volumes | ✓ named volumes without mount paths | GET volumes |
| Activity | ✓ audit actor/action/result/source table | GET audit events |
| Monitoring | ✓ four metrics + fleet and local diagnostics | GET monitoring overview and diagnostics |
| Deployments | ✓ readiness, static reviews, dry-runs, evidence packets | GET readiness/jobs/review; owner-confirmed metadata-only dry-run |
| Settings | ✓ read-only effective security posture | GET security summary |
| Login/logout | ✓ original card layout and existing owner session | Existing HttpOnly FastAPI cookie |
| Shared visual language | ✓ verbatim original CSS baseline and UI structure | Same dashboard navy, teal, spacing, tables, pills, cards and navigation |
| Security boundary | ✓ original backend authorization preserved | No Next API/Node server, Docker socket, host port or agent secret |

No remote container execution is enabled by the migration. All mutations above
are the same **metadata/enrollment operations** that were already available in
the original dashboard and remain subject to FastAPI session and origin checks.

## Still requiring verification before replacing the original UI

- Real-browser screenshot comparisons at desktop/mobile widths and
  accessibility testing (code/CSS parity is not pixel-perfect proof).
- Authenticated browser regression tests for owner CRUD, Compose rejection,
  CSRF/origin behavior and session expiration.
- Lockfile and reproducible dependency/vulnerability audit; Node is CI-only.
- Operator verification that existing data from the live VPS renders
  equivalently in both frontends.

**Do not promote Next.js to `/` yet.** Deploy to the private opt-in preview
route only, and preserve the current FastAPI dashboard as the fallback.
