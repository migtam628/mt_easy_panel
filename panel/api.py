"""MT Panel control-plane. Intentionally unprivileged and Docker-socket-free."""
from __future__ import annotations

import os
import secrets
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from panel.registry import Registry, RegistryError
from panel.enrollment import EnrollmentStore
from panel.host_reports import HostReports
from panel.fleet import FleetStore
from panel.deployment_readiness import DeploymentReadiness
from panel.local_jobs import LocalJobs
from protocol.local_action import LocalAction, sign_action
from panel.diagnostics import summarize_containers, host_capacity
from protocol.host_snapshot import HostSnapshot
from panel.manifests import ServiceDraft
from panel.compose_policy import ComposePolicyError, validate_compose

from panel.auth import AuthStore

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
COOKIE = "mtpanel_session"


@dataclass(frozen=True)
class Settings:
    db_path: str
    agent_url: str
    agent_token: str
    origin: str
    cookie_secure: bool = False
    lab_server_id: str = ""
    lab_execution_enabled: bool = False
    lab_execution_key: str = ""

    @classmethod
    def from_env(cls):
        return cls(
            db_path=os.environ.get("PANEL_DB_PATH", "./state/panel.db"),
            agent_url=os.environ.get("PANEL_AGENT_URL", "http://127.0.0.1:8788"),
            agent_token=os.environ.get("AGENT_TOKEN", ""),
            origin=os.environ.get("PANEL_PUBLIC_ORIGIN", "http://127.0.0.1:8086"),
            cookie_secure=os.environ.get("PANEL_COOKIE_SECURE", "false").lower() == "true",
            lab_server_id=os.environ.get("PANEL_LOCAL_SERVER_ID", ""),
            lab_execution_enabled=os.environ.get("PANEL_LOCAL_EXECUTION_ENABLED") == "true",
            lab_execution_key=os.environ.get("AGENT_EXECUTION_KEY", ""),
        )

    def validate(self):
        if len(self.agent_token) < 32 or self.agent_token.startswith("REPLACE_"):
            raise ValueError("Set a unique AGENT_TOKEN (at least 32 characters)")
        parsed = urlparse(self.agent_url)
        if parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "localhost", "::1") or parsed.path not in ("", "/") or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Phase 1 agent URL must be a loopback HTTP endpoint (use an SSH tunnel for remote hosts)")
        origin = urlparse(self.origin)
        if origin.scheme not in ("http", "https") or not origin.netloc or origin.path not in ("", "/") or origin.query or origin.fragment or origin.username or origin.password:
            raise ValueError("PANEL_PUBLIC_ORIGIN must be a complete http(s) origin, without a path")
        if origin.scheme != "https" and origin.hostname not in ("localhost", "127.0.0.1", "::1"):
            raise ValueError("External access requires HTTPS")
        if origin.scheme == "https" and not self.cookie_secure:
            raise ValueError("PANEL_COOKIE_SECURE must be true for an HTTPS origin")
        if self.lab_execution_enabled:
            if (os.environ.get("PANEL_EXECUTION_LAB_ACK") != "I_ACCEPT_DISPOSABLE_HOST_ONLY"
                    or len(self.lab_execution_key) < 32
                    or self.lab_execution_key == self.agent_token
                    or len(self.lab_server_id) != 32
                    or any(x not in "0123456789abcdef" for x in self.lab_server_id)):
                raise ValueError("Local execution requires disposable-host acknowledgement, "
                                 "dedicated key, and explicit 32-hex local server ID")


class AgentClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def get(self, endpoint: str) -> object:
        # Explicit allowlist; no user-controlled host, port, or arbitrary paths.
        if endpoint not in ("overview", "containers", "images", "networks", "volumes"):
            raise ValueError("Unknown agent resource")
        return await self._request(f"/v1/{endpoint}")

    async def logs(self, container_id: str):
        if len(container_id) not in range(12, 65) or any(c not in "0123456789abcdef" for c in container_id):
            raise ValueError("Invalid container ID")
        return await self._request(f"/v1/containers/{container_id}/logs?tail=80")

    async def lab_candidate(self, job_id: str, draft_id: str,
                            image_digest: str) -> dict:
        """GET one strict lab-owned candidate; no raw Engine inspect is returned."""
        if not self.settings.lab_execution_enabled:
            raise HTTPException(403, "Local deployment execution disabled")
        for value in (job_id, draft_id):
            if len(value) != 32 or any(c not in "0123456789abcdef" for c in value):
                raise HTTPException(422, "Invalid lab identifier")
        path = f"/v1/lab/candidates/{job_id}"
        try:
            async with httpx.AsyncClient(timeout=6, trust_env=False) as client:
                response = await client.get(
                    self.settings.agent_url.rstrip("/") + path,
                    params={"draft_id": draft_id, "image_digest": image_digest},
                    headers={"Authorization": f"Bearer {self.settings.agent_token}"},
                )
                response.raise_for_status()
                result = response.json()["data"]
                allowed = {"absent", "stopped", "running_healthy",
                           "running_unhealthy", "running_starting", "running_unknown"}
                if (not isinstance(result, dict)
                        or result.get("observation") not in allowed
                        or not isinstance(result.get("present"), bool)
                        or result.get("safe_to_retry") is not False
                        or result.get("traffic_switched") is not False):
                    raise ValueError("Unexpected lab candidate observation")
                return {"observation": result["observation"],
                        "present": result["present"],
                        "safe_to_retry": False,
                        "traffic_switched": False}
        except (httpx.RequestError, httpx.HTTPStatusError, ValueError, KeyError) as exc:
            raise HTTPException(503, "Local candidate inspection unavailable; job remains blocked") from exc

    async def lab_action(self, operation: str, job_id: str, draft_id: str,
                         manifest: ServiceDraft | None = None) -> dict:
        if not self.settings.lab_execution_enabled:
            raise HTTPException(403, "Local deployment execution disabled")
        action = LocalAction(
            operation=operation, job_id=job_id, draft_id=draft_id,
            issued_at=int(time.time()), nonce=secrets.token_hex(16),
            manifest=manifest,
        )
        url = self.settings.agent_url.rstrip("/") + "/v1/lab/actions"
        headers = {
            "Authorization": f"Bearer {self.settings.agent_token}",
            "X-MTPanel-Signature": sign_action(self.settings.lab_execution_key, action),
        }
        try:
            async with httpx.AsyncClient(timeout=35, trust_env=False) as client:
                response = await client.post(url, json=action.model_dump(mode="json"),
                                             headers=headers)
                response.raise_for_status()
                result = response.json()["data"]
                if not isinstance(result, dict) or result.get("status") not in (
                        "HEALTHY", "ROLLED_BACK"):
                    raise ValueError("Unexpected agent deployment result")
                return result
        except (httpx.RequestError, httpx.HTTPStatusError, ValueError, KeyError) as exc:
            # Do not leak signed requests, the bearer token, daemon paths or
            # raw Docker messages into the browser.
            raise HTTPException(503, "Local lab deployment agent failed; job requires review") from exc

    async def _request(self, path: str):
        try:
            async with httpx.AsyncClient(timeout=6, trust_env=False) as client:
                response = await client.get(self.settings.agent_url.rstrip("/") + path,
                    headers={"Authorization": f"Bearer {self.settings.agent_token}"})
                response.raise_for_status()
                return response.json()["data"]
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 401:
                detail = "Host agent rejected the shared token. Restart both services using the same .env."
            elif status == 503:
                detail = "Host agent is online, but Docker is unavailable. Start Docker or check DOCKER_SOCKET_PATH."
            else:
                detail = f"Host agent returned HTTP {status}; check the agent process logs."
            raise HTTPException(503, detail) from exc
        except httpx.RequestError as exc:
            raise HTTPException(503, "Cannot reach host agent. Verify that the agent is running on the configured loopback port.") from exc
        except (ValueError, KeyError) as exc:
            raise HTTPException(503, "Host agent sent an invalid response. Check both service versions.") from exc


class ComposePreview(BaseModel):
    source: str = Field(min_length=1, max_length=32768)

class ServerData(BaseModel):
    name: str = Field(min_length=2, max_length=72)
    notes: str = Field(default="", max_length=500)


class ProjectData(BaseModel):
    name: str = Field(min_length=2, max_length=72)
    slug: str = Field(min_length=2, max_length=48)
    server_id: str | None = None


class EnvironmentData(BaseModel):
    name: str = Field(min_length=2, max_length=72)
    slug: str = Field(min_length=2, max_length=48)


class EnrollmentProof(BaseModel):
    server_id: str = Field(min_length=32, max_length=32)
    code: str = Field(min_length=43, max_length=43)
    public_key: str = Field(min_length=40, max_length=60)
    signature: str = Field(min_length=80, max_length=120)
    nonce: str = Field(min_length=43, max_length=43)


class AgentHeartbeat(BaseModel):
    sequence: int = Field(ge=1, le=2**63 - 1)
    timestamp: int = Field(ge=1)
    signature: str = Field(min_length=80, max_length=120)


class SignedHostReport(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    sequence: int = Field(ge=1, le=2**63 - 1)
    timestamp: int = Field(ge=1)
    signature: str = Field(min_length=80, max_length=120)
    snapshot: HostSnapshot


class LocalJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    idempotency_key: str = Field(min_length=16, max_length=96)
    execute: bool = False
    confirmation: str = ""


class LoginData(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=1024)


def create_app(settings: Settings | None = None, agent=None):
    settings = settings or Settings.from_env()
    settings.validate()
    store = AuthStore(settings.db_path)
    registry = Registry(settings.db_path)
    enrollment = EnrollmentStore(settings.db_path)
    reports = HostReports(settings.db_path)
    fleet = FleetStore(settings.db_path)
    deployments = DeploymentReadiness(settings.db_path)
    jobs = LocalJobs(settings.db_path)
    agent = agent or AgentClient(settings)
    app = FastAPI(title="MT Panel", version="0.3.10-dev", docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/assets", StaticFiles(directory=str(WEB_DIR)), name="assets")
    # In-memory login throttling is a Phase 1 local guard only; production needs
    # persistent, multi-instance throttling plus MFA and reverse-proxy controls.
    login_attempts: dict[str, deque] = defaultdict(deque)

    @app.middleware("http")
    async def headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        )
        return response

    def current_user(request: Request):
        user = store.user_for(request.cookies.get(COOKIE))
        if not user:
            raise HTTPException(401, "Please sign in")
        return user

    def verify_origin(request: Request):
        origin = request.headers.get("Origin")
        if origin is not None and origin != settings.origin:
            raise HTTPException(403, "Origin mismatch")
        # SameSite=Strict, JSON-only requests and no CORS provide further CSRF
        # barriers; no state-changing Docker APIs exist in Phase 1.

    @app.get("/")
    def homepage():
        return FileResponse(str(WEB_DIR / "index.html"))

    @app.get("/api/health")
    def health():
        return {"ok": True, "service": "mt-panel", "version": "0.3.10-dev",
                "lab_execution_enabled": settings.lab_execution_enabled}

    @app.get("/api/setup")
    def setup():
        return {"needs_setup": not store.is_setup()}

    @app.post("/api/auth/login")
    def login(data: LoginData, request: Request, response: Response):
        verify_origin(request)
        if not store.is_setup():
            raise HTTPException(503, "Run the local create-admin command before signing in")
        client_id = request.client.host if request.client else "unknown"
        now = time.monotonic()
        recent = login_attempts[client_id]
        while recent and now - recent[0] >= 300:
            recent.popleft()
        if len(recent) >= 10:
            raise HTTPException(429, "Too many attempts; try later")
        recent.append(now)
        token = store.login(data.username, data.password, client_id)
        if token is None:
            raise HTTPException(401, "Invalid credentials")
        recent.clear()
        response.set_cookie(COOKIE, token, httponly=True, secure=settings.cookie_secure,
                            samesite="strict", max_age=43200, path="/")
        return {"username": data.username, "role": "owner"}

    @app.post("/api/auth/logout")
    def logout(request: Request, response: Response, user=Depends(current_user)):
        verify_origin(request)
        store.logout(request.cookies.get(COOKIE), user["username"],
                     request.client.host if request.client else "unknown")
        response.delete_cookie(COOKIE, path="/", secure=settings.cookie_secure, samesite="strict")
        return {"ok": True}

    @app.get("/api/auth/me")
    def me(user=Depends(current_user)):
        return user

    @app.get("/api/audit/events")
    def audit_events(limit: int = Query(default=50, ge=1, le=100), user=Depends(current_user)):
        return {"data": store.list_audit_events(limit)}

    def registry_action(fn, *args, **kwargs):
        try:
            return {"data": fn(*args, **kwargs)}
        except RegistryError as exc:
            raise HTTPException(exc.status, str(exc)) from exc

    def require_write_origin(request: Request):
        # Every cookie-authenticated mutation requires explicit matching Origin.
        if request.headers.get("Origin") != settings.origin:
            raise HTTPException(403, "Same-origin request required")

    @app.get("/api/fleet/summary")
    def fleet_summary(user=Depends(current_user)):
        # Local owner-scoped SQLite reads only. This is NOT remote Docker.
        return {"data": fleet.summary(user["username"])}

    @app.get("/api/monitoring/overview")
    async def monitoring_overview(user=Depends(current_user)):
        # Fleet summaries are signed self-reported identity telemetry.
        # The local Docker overview remains separately loopback-token scoped.
        snapshot = fleet.summary(user["username"])
        local = None
        local_state = "unavailable"
        try:
            overview = await agent.get("overview")
            if isinstance(overview, dict):
                local = {
                    "hostname": str(overview.get("hostname", ""))[:100],
                    "containers_total": overview.get("containers_total"),
                    "containers_running": overview.get("containers_running"),
                    "cpus": overview.get("cpus"),
                    "memory_bytes": overview.get("memory_bytes"),
                    "disk_total_bytes": overview.get("disk_total_bytes"),
                    "disk_used_bytes": overview.get("disk_used_bytes"),
                    "source": overview.get("source"),
                }
                local_state = "connected" if overview.get("source") != "demo" else "demo"
        except (HTTPException, ValueError, TypeError):
            # Do not convert local Docker reachability failures into fake
            # healthy values or suppress the fleet summary.
            pass
        return {"data": {
            "fleet": snapshot, "local_host": local,
            "local_state": local_state, "remote_docker_access": False,
            "notifications_enabled": False, "polling_enabled": False,
        }}

    @app.get("/api/monitoring/diagnostics")
    async def local_container_diagnostics(user=Depends(current_user)):
        # Uses ONLY the existing constrained local agent's GET inventory.
        # No arbitrary Engine paths, container actions or persisted data.
        try:
            overview = await agent.get("overview")
            containers = await agent.get("containers")
            if not isinstance(overview, dict):
                raise ValueError("Malformed local agent overview")
            diagnostics = summarize_containers(containers)
            capacity = host_capacity(overview)
        except (HTTPException, ValueError, TypeError):
            return {"data": {
                "state": "unavailable", "source": None,
                "capacity": None, "diagnostics": None,
                "message": "Local Docker inventory unavailable; no health claim made",
                "docker_writes_enabled": False,
            }}
        return {"data": {
            "state": "demo" if overview.get("source") == "demo" else "connected",
            "source": overview.get("source"),
            "capacity": capacity, "diagnostics": diagnostics,
            "message": "On-demand local inventory; not continuous monitoring",
            "docker_writes_enabled": False,
        }}

    @app.get("/api/deployments/readiness")
    def deployment_readiness(user=Depends(current_user)):
        return {"data": deployments.list_drafts(user["username"])}

    @app.get("/api/deployments/drafts/{draft_id}/review")
    def review_deployment_draft(draft_id: str, user=Depends(current_user)):
        return registry_action(deployments.review, user["username"], draft_id)

    @app.get("/api/deployments/jobs")
    def list_local_jobs(limit: int = Query(default=50, ge=1, le=100),
                        user=Depends(current_user)):
        return {"data": jobs.list(user["username"], limit)}

    @app.get("/api/deployments/jobs/{job_id}")
    def local_job_details(job_id: str, user=Depends(current_user)):
        return registry_action(jobs.details, user["username"], job_id)

    @app.post("/api/deployments/drafts/{draft_id}/jobs", status_code=201)
    def create_local_job(draft_id: str, data: LocalJobRequest, request: Request,
                         user=Depends(current_user)):
        require_write_origin(request)
        if data.execute:
            raise HTTPException(403, "Create a DRAFT first, then approve QUEUED separately")
        if data.confirmation:
            raise HTTPException(422, "Dry-run jobs do not accept execution confirmation")
        return registry_action(jobs.create, user["username"], draft_id,
                               data.idempotency_key, settings.lab_server_id,
                               execute=data.execute)

    @app.post("/api/deployments/jobs/{job_id}/queue")
    def queue_local_job(job_id: str, request: Request, user=Depends(current_user)):
        require_write_origin(request)
        if not settings.lab_execution_enabled or request.headers.get(
                "X-MTPanel-Approval") != "DEPLOY_TO_DISPOSABLE_HOST":
            raise HTTPException(403, "Isolated-host deployment approval required")
        return registry_action(jobs.queue, user["username"],
                               job_id, settings.lab_server_id)

    @app.post("/api/deployments/jobs/{job_id}/run")
    async def run_local_job(job_id: str, request: Request, user=Depends(current_user)):
        require_write_origin(request)
        if not settings.lab_execution_enabled or request.headers.get(
                "X-MTPanel-Approval") != "DEPLOY_TO_DISPOSABLE_HOST":
            raise HTTPException(403, "Local deployment execution is disabled")
        try:
            claimed = jobs.claim(user["username"], job_id, settings.lab_server_id)
        except RegistryError as exc:
            raise HTTPException(exc.status, str(exc)) from exc
        result = None
        try:
            result = await agent.lab_action("deploy", claimed["job_id"],
                                            claimed["draft_id"], claimed["manifest"])
            terminal = result["status"]
            code = "healthy" if terminal == "HEALTHY" else "candidate_stopped"
        except Exception:
            # The operation may have reached Docker. Never automatically
            # retry it after an uncertain network/application failure.
            terminal, code = "NEEDS_REVIEW", "agent_unconfirmed"
        try:
            record = jobs.finish(user["username"], job_id, claimed["token"],
                                 terminal, code)
        except RegistryError as exc:
            raise HTTPException(exc.status, str(exc)) from exc
        return {"data": record}

    @app.get("/api/deployments/jobs/{job_id}/recovery")
    async def inspect_local_job_recovery(job_id: str, user=Depends(current_user)):
        if not settings.lab_execution_enabled:
            row = registry_action(jobs.details, user["username"], job_id)["data"]
            return {"data": {"job_id": job_id, "job_state": row["state"],
                             "observation": "disabled", "safe_to_retry": False,
                             "host_lock_released": False}}
        target = registry_action(jobs.recovery_target, user["username"],
                                 job_id, settings.lab_server_id)["data"]
        if target["state"] not in ("RUNNING", "NEEDS_REVIEW"):
            return {"data": {**target, "observation": "not_applicable",
                             "safe_to_retry": False, "host_lock_released": False}}
        try:
            observation = await agent.lab_candidate(
                target["job_id"], target["draft_id"], target["image_digest"])
        except Exception as exc:
            raise HTTPException(503, "Lab candidate status unavailable; host remains locked") from exc
        return {"data": {**target, **observation,
                         "host_lock_released": False}}

    @app.post("/api/deployments/jobs/{job_id}/reconcile")
    async def reconcile_local_job(job_id: str, request: Request,
                                  user=Depends(current_user)):
        require_write_origin(request)
        if (not settings.lab_execution_enabled or request.headers.get(
                "X-MTPanel-Approval") != "INSPECT_AND_HOLD"):
            raise HTTPException(403, "Explicit isolated-host reconciliation approval required")
        target = registry_action(jobs.recovery_target, user["username"],
                                 job_id, settings.lab_server_id)["data"]
        if target["state"] not in ("RUNNING", "NEEDS_REVIEW"):
            raise HTTPException(409, "Job is not unresolved")
        if target["state"] == "RUNNING" and not target["lease_expired"]:
            raise HTTPException(409, "Active job lease cannot be reconciled")
        try:
            observation = await agent.lab_candidate(
                target["job_id"], target["draft_id"], target["image_digest"])
        except Exception as exc:
            raise HTTPException(503, "Lab candidate status unavailable; host remains locked") from exc
        return registry_action(jobs.record_recovery, user["username"], job_id,
                               settings.lab_server_id, observation["observation"])

    @app.get("/api/settings/security")
    def security_posture(user=Depends(current_user)):
        # Fixed allowlisted facts only; never expose AGENT_TOKEN, DB paths,
        # private agent keys, environment contents or cookie values.
        return {"data": {
            "owner": user["username"], "app_version": "0.3.10-dev",
            "public_origin": settings.origin,
            "secure_cookies": settings.cookie_secure,
            "session_cookie_http_only": True,
            "session_cookie_same_site": "Strict",
            "agent_connection": "loopback_only",
            "local_docker_inventory": "read_only",
            "remote_docker_access": False,
            "container_writes": False,
            "deployment_execution": settings.lab_execution_enabled,
            "lab_execution_enabled": settings.lab_execution_enabled,
            "multi_user_roles": False,
            "multi_factor_auth": False,
            "security_audit": "local_sqlite",
            "background_alerts": False,
        }}

    @app.get("/api/catalog/servers")
    def list_servers(user=Depends(current_user)):
        return registry_action(registry.servers, user["username"])

    @app.post("/api/catalog/servers", status_code=201)
    def create_server(data: ServerData, request: Request, user=Depends(current_user)):
        require_write_origin(request)
        return registry_action(registry.add_server, user["username"], data.name, data.notes)

    @app.get("/api/catalog/servers/{server_id}/identity")
    def server_identity(server_id: str, user=Depends(current_user)):
        return registry_action(enrollment.server_identity, user["username"], server_id)

    @app.post("/api/catalog/servers/{server_id}/invites", status_code=201)
    def generate_agent_invite(server_id: str, request: Request, user=Depends(current_user)):
        require_write_origin(request)
        return registry_action(enrollment.create_invite, user["username"], server_id)

    @app.post("/api/catalog/servers/{server_id}/revoke")
    def revoke_agent(server_id: str, request: Request, user=Depends(current_user)):
        require_write_origin(request)
        return registry_action(enrollment.revoke, user["username"], server_id)

    @app.post("/api/agents/enroll")
    def register_agent(proof: EnrollmentProof):
        # Code is short-lived, random and single-use, with a proof of possession.
        # No remote URL or Docker call is accepted on this endpoint.
        return registry_action(enrollment.enroll, proof.server_id, proof.code,
                               proof.public_key, proof.signature, proof.nonce)

    @app.post("/api/agents/{server_id}/heartbeat")
    def signed_heartbeat(server_id: str, payload: AgentHeartbeat):
        # Signed monotonic sequence prevents replay, even in the clock-skew window.
        return registry_action(enrollment.heartbeat, server_id, payload.sequence,
                               payload.timestamp, payload.signature)

    @app.get("/api/catalog/servers/{server_id}/host-report")
    def read_host_report(server_id: str, user=Depends(current_user)):
        return registry_action(reports.get, user["username"], server_id)

    @app.get("/api/catalog/servers/{server_id}/host-history")
    def read_host_history(server_id: str, limit: int = Query(default=96, ge=1, le=200),
                          user=Depends(current_user)):
        # Local SQLite reads only, never requests anything from the remote host.
        return registry_action(reports.history, user["username"], server_id, limit)

    @app.post("/api/agents/{server_id}/host-report")
    def accept_host_report(server_id: str, payload: SignedHostReport):
        return registry_action(reports.ingest, server_id, payload.sequence,
                               payload.timestamp, payload.signature, payload.snapshot)

    @app.get("/api/catalog/projects")
    def list_projects(user=Depends(current_user)):
        return registry_action(registry.projects, user["username"])

    @app.post("/api/catalog/projects", status_code=201)
    def create_project(data: ProjectData, request: Request, user=Depends(current_user)):
        require_write_origin(request)
        return registry_action(registry.add_project, user["username"], data.name, data.slug, data.server_id)

    @app.get("/api/catalog/projects/{project_id}/environments")
    def list_environments(project_id: str, user=Depends(current_user)):
        return registry_action(registry.environments, user["username"], project_id)

    @app.post("/api/catalog/projects/{project_id}/environments", status_code=201)
    def create_environment(project_id: str, data: EnvironmentData, request: Request,
                           user=Depends(current_user)):
        require_write_origin(request)
        return registry_action(registry.add_environment, user["username"], project_id, data.name, data.slug)

    @app.get("/api/catalog/environments/{environment_id}/drafts")
    def list_service_drafts(environment_id: str, user=Depends(current_user)):
        return registry_action(registry.drafts, user["username"], environment_id)

    @app.post("/api/catalog/environments/{environment_id}/drafts", status_code=201)
    def create_service_draft(environment_id: str, manifest: ServiceDraft, request: Request,
                             user=Depends(current_user)):
        require_write_origin(request)
        return registry_action(registry.add_draft, user["username"], environment_id, manifest)

    @app.post("/api/validate/compose")
    def compose_preview(data: ComposePreview, request: Request, user=Depends(current_user)):
        require_write_origin(request)
        try:
            return {"data": validate_compose(data.source)}
        except ComposePolicyError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/api/server/overview")
    async def overview(user=Depends(current_user)):
        return {"data": await agent.get("overview")}

    @app.get("/api/server/containers")
    async def containers(user=Depends(current_user)):
        return {"data": await agent.get("containers")}

    @app.get("/api/server/images")
    async def images(user=Depends(current_user)):
        return {"data": await agent.get("images")}

    @app.get("/api/server/networks")
    async def networks(user=Depends(current_user)):
        return {"data": await agent.get("networks")}

    @app.get("/api/server/volumes")
    async def volumes(user=Depends(current_user)):
        return {"data": await agent.get("volumes")}

    @app.get("/api/server/containers/{container_id}/logs")
    async def logs(container_id: str, user=Depends(current_user)):
        if len(container_id) not in range(12, 65) or any(c not in "0123456789abcdef" for c in container_id):
            raise HTTPException(422, "Invalid container ID")
        return {"data": await agent.logs(container_id)}

    return app


def app_factory():
    return create_app()
