"""MT Panel control-plane. Intentionally unprivileged and Docker-socket-free."""
from __future__ import annotations

import os
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from panel.registry import Registry, RegistryError
from panel.manifests import ServiceDraft

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

    @classmethod
    def from_env(cls):
        return cls(
            db_path=os.environ.get("PANEL_DB_PATH", "./state/panel.db"),
            agent_url=os.environ.get("PANEL_AGENT_URL", "http://127.0.0.1:8788"),
            agent_token=os.environ.get("AGENT_TOKEN", ""),
            origin=os.environ.get("PANEL_PUBLIC_ORIGIN", "http://127.0.0.1:8086"),
            cookie_secure=os.environ.get("PANEL_COOKIE_SECURE", "false").lower() == "true",
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


class LoginData(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=1024)


def create_app(settings: Settings | None = None, agent=None):
    settings = settings or Settings.from_env()
    settings.validate()
    store = AuthStore(settings.db_path)
    registry = Registry(settings.db_path)
    agent = agent or AgentClient(settings)
    app = FastAPI(title="MT Panel", version="0.2.0-dev", docs_url=None, redoc_url=None, openapi_url=None)
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
        return {"ok": True, "service": "mt-panel", "version": "0.2.0-dev"}

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

    def registry_action(fn, *args):
        try:
            return {"data": fn(*args)}
        except RegistryError as exc:
            raise HTTPException(exc.status, str(exc)) from exc

    def require_write_origin(request: Request):
        # Every cookie-authenticated mutation requires explicit matching Origin.
        if request.headers.get("Origin") != settings.origin:
            raise HTTPException(403, "Same-origin request required")

    @app.get("/api/catalog/servers")
    def list_servers(user=Depends(current_user)):
        return registry_action(registry.servers, user["username"])

    @app.post("/api/catalog/servers", status_code=201)
    def create_server(data: ServerData, request: Request, user=Depends(current_user)):
        require_write_origin(request)
        return registry_action(registry.add_server, user["username"], data.name, data.notes)

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
