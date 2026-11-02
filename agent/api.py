"""Local-host Docker read-only agent. Never expose directly on the Internet."""
from __future__ import annotations

import hmac
import os
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from agent.docker import CONTAINER_ID, DockerError, DockerReader


class DemoReader:
    def overview(self):
        return {"hostname": "DEMO — lab-server", "docker_version": "demo",
                "os": "Sample Linux data", "cpus": 4, "memory_bytes": 8_589_934_592,
                "containers_total": 3, "containers_running": 2,
                "images_total": 5, "disk_total_bytes": 107_374_182_400,
                "disk_used_bytes": 42_949_672_960,
                "disk_free_bytes": 64_424_509_440, "source": "demo"}

    def containers(self):
        return [
            {"id": "a"*64, "name": "website", "image": "nginx:stable", "state": "running", "status": "Up 2 days", "created": 0, "ports": [{"private":80,"public":8090,"type":"tcp"}]},
            {"id": "b"*64, "name": "postgres", "image": "postgres:17", "state": "running", "status": "Up 2 days", "created": 0, "ports": []},
            {"id": "c"*64, "name": "worker", "image": "python:3.12-slim", "state": "exited", "status": "Exited (0) 1 hour ago", "created": 0, "ports": []},
        ]

    def images(self):
        return [{"id":"sha256:demo", "tags":["nginx:stable"],"size_bytes":120000000,"created":0}]

    def networks(self):
        return [{"id":"demo-net", "name":"bridge","driver":"bridge","scope":"local"}]

    def volumes(self):
        return [{"name":"demo-pgdata","driver":"local","scope":"local"}]

    def logs(self, container_id, tail):
        return "DEMO OUTPUT — no live container logs were queried.\n"


def create_app(reader=None, token: str | None = None):
    app = FastAPI(title="MT Panel Host Agent", version="0.1.1", docs_url=None,
                  redoc_url=None, openapi_url=None)
    token = token if token is not None else os.environ.get("AGENT_TOKEN", "")
    if len(token) < 32 or token.startswith("REPLACE_"):
        raise RuntimeError("AGENT_TOKEN must be a unique secret of 32+ characters")
    reader = reader or (DemoReader() if os.environ.get("AGENT_DEMO_MODE") == "true"
                        else DockerReader())

    @app.get("/health")
    def health():
        # Liveness only; inventory/status still require the agent token.
        return {"ok": True, "service": "mt-panel-agent", "version": "0.1.1"}

    def authorize(authorization: str | None = Header(default=None)):
        expected = "Bearer " + token
        if not authorization or not hmac.compare_digest(authorization, expected):
            raise HTTPException(401, "Unauthorized", headers={"WWW-Authenticate": "Bearer"})

    def run(operation, *args):
        try:
            return {"data": operation(*args)}
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except DockerError as exc:
            raise HTTPException(503, str(exc)) from exc

    @app.get("/v1/overview", dependencies=[Depends(authorize)])
    def overview():
        return run(reader.overview)

    @app.get("/v1/containers", dependencies=[Depends(authorize)])
    def containers():
        return run(reader.containers)

    @app.get("/v1/images", dependencies=[Depends(authorize)])
    def images():
        return run(reader.images)

    @app.get("/v1/networks", dependencies=[Depends(authorize)])
    def networks():
        return run(reader.networks)

    @app.get("/v1/volumes", dependencies=[Depends(authorize)])
    def volumes():
        return run(reader.volumes)

    @app.get("/v1/containers/{container_id}/logs", dependencies=[Depends(authorize)])
    def logs(container_id: str, tail: int = Query(default=80, ge=1, le=200)):
        if not CONTAINER_ID.fullmatch(container_id):
            raise HTTPException(422, "Invalid container ID")
        return run(reader.logs, container_id, tail)

    return app


# Used by uvicorn; no secrets are stored in the source tree.
def app_factory():
    return create_app()
