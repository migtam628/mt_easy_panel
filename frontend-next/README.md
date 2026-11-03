# MT Panel Next.js frontend — migration preview

This is an independent, strictly static Next.js 16 App Router frontend
prototype. It does **not** replace the installed FastAPI dashboard.

- Source path: `frontend-next/`
- Public preview route prefix when built/deployed: `/next-preview/`
- Build: `npm install --no-audit --no-fund && npm run build`
- Output: `frontend-next/out/` (no Node.js process is required to serve it)
- Node.js 22 or later for development/building; **not required for the live FastAPI/SQLite services**
- Existing secure cookie and `/api/` are the only authentication/data route;
  no Next.js API routes, SSR backend, server actions, proxy, Docker socket,
  agent token, or new session system

**Not yet live:** The output is CI-tested only and is not bundled into the
production stage. A future opt-in preview promotion will serve built files
under the already private Tailscale FastAPI origin. Do not use `next dev`
as a public server or change existing ports/reverse proxies for a preview.

The preview implements: login/logout using existing cookie APIs, read-only
overview, containers, monitoring, servers, projects, activity, settings,
and a draft/job list with an explicitly confirmed **Save dry-run** action.
It is not feature-complete with the legacy UI, especially detailed server
identity actions, Compose, diagnostics, and enrollment.

## Trust boundary

The FastAPI server retains all authorization, session validation, CSRF
origin rules, data filtering, audit and job policy. UI rendering never
authorizes a Docker action. Client-side API paths are hardcoded to same-origin
`/api/`, never user-supplied URLs, and `fetch` sends only the browser's
HttpOnly same-origin cookie. The browser has no HMAC, agent, SSH, Docker,
or other host-level credential. Static HTML pages cannot render
user-specific data at build time; they fetch it only after authenticating.

## Migration gates

1. Confirm CI Next.js static export/typecheck with a frozen dependency lock.
2. Build an opt-in **same-origin** static preview that does not change `/`,
   systemd or Tailscale and cannot expose a backend on an additional port.
3. Reach functional parity for owner projects, deployment evidence and logs.
4. Run session/CSRF/XSS/security tests and browser smoke tests before
   replacing any existing dashboard route.

All production Docker write gates stay disabled.

## Preview deployment on the existing private VPS (explicit only)

The preview is optional and stays **disabled by default**. The new
`PANEL_NEXT_PREVIEW_ENABLED` option requires prebuilt assets under
`frontend-next/out/` in the installed release; no runtime Node
process or new public port is created.

For each green GitHub Actions run, download its `mt-panel-next-static`
artifact (built from that exact Git commit) with the GitHub web UI or:

```bash
gh run download <RUN_ID> -R migtam628/mt_easy_panel \
  -n mt-panel-next-static -D /tmp/mt-panel-next-preview
```

After safely staging the **same** exact commit on the VPS, run the
add-only `scripts/install-next-preview-stage.py --check`, then the
explicitly confirmed `--install` to attach assets only to the stage.
See [step-by-step runbook](../docs/EXISTING_VPS_UPGRADE.md).
Only after pinned promotion and read-only verification should the
operator add `PANEL_NEXT_PREVIEW_ENABLED=true` and restart only the
MT Panel service. The same private Tailscale origin then serves:

- Existing dashboard: `/` (unchanged)
- Next.js preview: `/next-preview/` (opt-in)
- Existing API: `/api/` (same session/CSRF protections)

The CI SHA-256 file list detects bundle corruption but does not itself
prove publisher authenticity. Download only the corresponding artifact
from the reviewed GitHub Actions run. A frozen npm lockfile and complete
UI parity are still required before replacing the legacy dashboard.
