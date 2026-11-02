"""Local-host Docker read-only agent. Never expose directly on the Internet."""
from __future__ import annotations

import hmac
import logging
import os
import time
import sqlite3
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from agent.local_execution import ActionDenied, LocalDockerWriter
from agent.action_replay import ActionReplay
from protocol.local_action import LocalAction, verify_action
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


def create_app(reader=None, token: str | None = None, *,
               writer=None, enable_local_writes: bool | None = None,
               execution_key: str | None = None, replay=None):
    app = FastAPI(title="MT Panel Host Agent", version="0.1.1", docs_url=None,
                  redoc_url=None, openapi_url=None)
    token = token if token is not None else os.environ.get("AGENT_TOKEN", "")
    if len(token) < 32 or token.startswith("REPLACE_"):
        raise RuntimeError("AGENT_TOKEN must be a unique secret of 32+ characters")
    reader = reader or (DemoReader() if os.environ.get("AGENT_DEMO_MODE") == "true"
                        else DockerReader())
    lab_enabled = (os.environ.get("AGENT_LOCAL_EXECUTION_ENABLED") == "true"
                   if enable_local_writes is None else enable_local_writes)
    lab_ack = os.environ.get("AGENT_EXECUTION_LAB_ACK", "")
    execution_key = (execution_key if execution_key is not None
                     else os.environ.get("AGENT_EXECUTION_KEY", ""))
    if lab_enabled and (lab_ack != "I_ACCEPT_DISPOSABLE_HOST_ONLY"
                        or len(execution_key) < 32
                        or execution_key == token
                        or os.environ.get("AGENT_DEMO_MODE") == "true"):
        raise RuntimeError("Lab Docker writes require explicit isolated-host acknowledgement, "
                           "a dedicated 32+ character key, and no demo mode")
    if lab_enabled and writer is None:
        writer = LocalDockerWriter(DockerReader().socket_path)
    agent_log = logging.getLogger("mtpanel.agent.lab")
    if lab_enabled and replay is None:
        replay = ActionReplay(os.environ.get(
            "AGENT_EXECUTION_REPLAY_DB", "/var/lib/mt-panel-agent/lab-actions.db"))


    @app.get("/health")
    def health():
        # Liveness only; inventory/status still require the agent token.
        return {"ok": True, "service": "mt-panel-agent", "version": "0.1.1",
                "lab_execution_enabled": lab_enabled}

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

    @app.post("/v1/lab/actions", dependencies=[Depends(authorize)])
    def local_action(action: LocalAction,
                     x_mtpanel_signature: str | None = Header(default=None)):
        # Installed production agents never enable this route by default.
        if not lab_enabled:
            raise HTTPException(403, "Local execution disabled")
        now = int(time.time())
        if (abs(now - action.issued_at) > 30 or not x_mtpanel_signature
                or not verify_action(execution_key, action, x_mtpanel_signature)):
            agent_log.warning("local_action_rejected job=%s reason=auth", action.job_id)
            raise HTTPException(401, "Invalid or expired signed local action")
        # Consume signed nonce in the agent's own durable SQLite ledger
        # BEFORE any Docker action. Database failure must fail closed.
        try:
            accepted = replay.consume(
                action.nonce, action.job_id, action.draft_id, action.operation, now)
        except sqlite3.Error as exc:
            raise HTTPException(503, "Local action audit store unavailable") from exc
        if not accepted:
            agent_log.warning("local_action_rejected job=%s reason=replay", action.job_id)
            raise HTTPException(409, "Local action replay")
        agent_log.info("local_action_requested job=%s draft=%s operation=%s",
                       action.job_id, action.draft_id, action.operation)
        try:
            if action.operation == "deploy":
                result = writer.deploy(action.job_id, action.draft_id, action.manifest)
            else:
                result = writer.lifecycle(action.job_id, action.draft_id,
                                          action.operation)
            agent_log.info("local_action_finished job=%s status=%s",
                           action.job_id, result.get("status", "complete"))
            replay.complete(action.nonce, result.get("status", "lifecycle").lower())
            return {"data": result}
        except ActionDenied as exc:
            replay.complete(action.nonce, "denied")
            agent_log.warning("local_action_denied job=%s reason=policy", action.job_id)
            raise HTTPException(409, str(exc)) from exc
        except DockerError as exc:
            replay.complete(action.nonce, "failed")
            agent_log.error("local_action_failed job=%s reason=docker", action.job_id)
            raise HTTPException(503, "Local lab Docker operation failed") from exc

    return app


# Used by uvicorn; no secrets are stored in the source tree.
def app_factory():
    return create_app()
