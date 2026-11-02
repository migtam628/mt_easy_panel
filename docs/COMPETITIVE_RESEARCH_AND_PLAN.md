# MT Panel competitive review and implementation action plan

**Research date:** 2026-11-01. Independent implementation; no proprietary Easypanel code or assets.

## Product references (official documentation)

| Product | Documented capability | MT Panel adaptation |
|---|---|---|
| [Easypanel](https://easypanel.io/docs/services/compose) | App and Compose deployments, domains, templates, backups, deployment triggers; detects conflicting fixed names and host ports | Guided app deployment, strict Compose policy and conflict checks |
| [Coolify](https://coolify.io/docs/core/how-coolify-works) | Dashboard separate from remote SSH-managed Docker hosts, projects/environments, job queues, workloads survive controller outage | Separate control/data paths, durable job state, independent workloads |
| [Dokploy](https://docs.dokploy.com/docs/core/deployment-options) | Independent remote Docker hosts versus actual Swarm clusters; optional dedicated build hosts | Standalone VPS management first; cluster orchestration later |
| [Portainer](https://docs.portainer.io/admin/environments/add/docker) | Agents, edge agents, local sockets, Docker environments | Minimal-privilege host-specific agent identity and revocation |
| [CapRover](https://caprover.com/docs/get-started) | Fast application deployment, Docker Swarm, nginx, automatic HTTPS | Simple workflows and one-click templates, without overriding an existing Caddy server |
| [Dokku](https://dokku.com/docs/deployment/application-deployment/) | Git push deployment, Dockerfile/buildpacks, terminal-first operation | Later reproducible CLI, immutable Git source and transparent build logs |

## Architecture principles

- A crashed or upgraded MT Panel control plane must not stop deployed workloads.
- Do not implicitly assume port 80/443, overwrite existing Caddy/Traefik configs, or modify unrelated Docker workloads.
- Differentiate **saved server identity** from **paired/connected server**; a registry record must not accept a user-supplied management URL until there is a dedicated secure enrollment workflow.
- Projects own environments; services belong to an environment and execute only on an explicitly authorized host.
- Agent access is a root-equivalent trust boundary. No arbitrary command relay or generic Docker API passthrough.
- All writes need ownership, origin/CSRF controls, atomic durable audit, validated declarative input, and eventual idempotency/locks.
- Backups are complete only after successful restore tests to disposable workloads.

## Milestones and release gates

1. **Foundation:** Bootstrap login, audit, authenticated API, read-only local Docker inspection. Completed in 0.1.x.
2. **Catalog:** Owner-scoped saved server identities, projects and environments with metadata-only APIs; UI and persistence tests. Implementing 0.2.0-dev.
3. **Declarative resources:** Strict schema for service definitions; validate names, images, ports, mounts, resource ceilings, security context. Dry-run only.
4. **Remote trust:** Server enrollment with per-host rotateable credentials, expiring grants, private network transport, host identity, and revocation.
5. **Deployment safety:** Durable queue, locks, immutable Git revision, build isolation, audit of all transitions, health checks, rollback and reconciliation.
6. **Usability:** GitHub integration, service lifecycle UI, database templates, domain/HTTPS management preserving existing proxies.
7. **Operations:** Logs, metrics, notifications, offsite backups and recovery verification.
8. **Release:** systemd installer, upgrade/rollback scripts, signed release artifacts, security review and real disposable-VPS testing.

## Stop conditions needing the owner's input

- Choose the *disposable* VPS and secure access arrangement before enabling a live job executor.
- Confirm whether deployment should integrate with the existing Caddy reverse proxy or manage Traefik on a new isolated host.
- Approve remote agent enrollment and any restart/redeploy of pre-existing containers.
- Supply DNS/domain and hosting access only when enabling public TLS endpoints.

**No live deployment is permitted solely because a server/project metadata record exists.**
