"""Safe Monitoring, Deployments and Settings pages: API contracts only.

All tests use fake local Docker reads; no Docker socket, subprocess, or VPS.
"""
from __future__ import annotations

import sqlite3
import time
from fastapi import HTTPException
from fastapi.testclient import TestClient

from panel.api import Settings, create_app
from panel.auth import AuthStore
from panel.deployment_readiness import DeploymentReadiness

ORIGIN = {"Origin": "http://127.0.0.1:8086"}
PASSWORD = "Read-only phase 2 owner password for tests"
PINNED = "registry.example.com/sample@sha256:" + "a" * 64


class LocalAgent:
    def __init__(self, available=True):
        self.available = available
        self.calls = []

    async def get(self, endpoint):
        self.calls.append(endpoint)
        if endpoint != "overview":
            raise AssertionError("Only overview is needed by this page")
        if not self.available:
            raise HTTPException(503, "offline")
        return {"hostname": "fixture-local", "source": "live", "cpus": 4,
                "memory_bytes": 1024**3, "disk_total_bytes": 1000,
                "disk_used_bytes": 200, "containers_total": 8,
                "containers_running": 7, "agent_token": "NEVER_EXPOSE"}

    async def logs(self, container_id):
        raise AssertionError("Monitoring may never request logs")


def setup(tmp_path, available=True):
    db = str(tmp_path / "operations.db")
    agent = LocalAgent(available)
    settings = Settings(db, "http://127.0.0.1:8788", "z" * 64,
                        "http://127.0.0.1:8086")
    client = TestClient(create_app(settings, agent))
    AuthStore(db).create_admin("owner", PASSWORD)
    return client, db, agent


def login(client):
    r = client.post("/api/auth/login", json={"username": "owner", "password": PASSWORD},
                    headers=ORIGIN)
    assert r.status_code == 200, r.text


def test_pages_are_owner_only_and_do_not_expose_tokens(tmp_path):
    c, db, agent = setup(tmp_path)
    urls = ("/api/monitoring/overview", "/api/deployments/readiness", "/api/settings/security")
    for url in urls:
        assert c.get(url).status_code == 401
    assert agent.calls == []
    login(c)
    monitoring = c.get(urls[0])
    assert monitoring.status_code == 200
    data = monitoring.json()["data"]
    assert data["local_host"]["hostname"] == "fixture-local"
    assert data["local_host"]["containers_total"] == 8
    assert data["local_state"] == "connected"
    assert data["remote_docker_access"] is False
    assert data["notifications_enabled"] is False
    assert data["polling_enabled"] is False
    assert "agent_token" not in str(data)
    assert "NEVER_EXPOSE" not in str(data)
    assert agent.calls == ["overview"]

    deployment = c.get(urls[1]).json()["data"]
    assert deployment["drafts"] == []
    assert deployment["execution_enabled"] is False
    assert deployment["jobs_created"] is False
    assert deployment["docker_writes_enabled"] is False

    posture = c.get(urls[2]).json()["data"]
    assert posture["app_version"] == "0.3.14-dev"
    assert posture["owner"] == "owner"
    assert posture["container_writes"] is False
    assert posture["deployment_execution"] is False
    assert posture["remote_docker_access"] is False
    assert posture["multi_factor_auth"] is False
    for forbidden in ("AGENT_TOKEN", "z" * 64, "password_hash", "private_key", "cookie_value"):
        assert forbidden not in str(posture)
    assert agent.calls == ["overview"]


def test_monitoring_survives_local_agent_offline(tmp_path):
    c, db, agent = setup(tmp_path, available=False)
    login(c)
    result = c.get("/api/monitoring/overview")
    assert result.status_code == 200
    data = result.json()["data"]
    assert data["local_state"] == "unavailable"
    assert data["local_host"] is None
    assert data["fleet"]["servers"] == []
    assert data["remote_docker_access"] is False
    assert agent.calls == ["overview"]


def test_drafts_are_owner_scoped_and_never_executable(tmp_path):
    c, db, agent = setup(tmp_path)
    login(c)
    project = c.post("/api/catalog/projects", json={"name":"Demo Project","slug":"demo-project"},
                     headers=ORIGIN)
    assert project.status_code == 201, project.text
    pid = project.json()["data"]["id"]
    env = c.post(f"/api/catalog/projects/{pid}/environments",
                 json={"name":"Staging","slug":"staging"}, headers=ORIGIN)
    assert env.status_code == 201, env.text
    eid = env.json()["data"]["id"]
    draft = c.post(f"/api/catalog/environments/{eid}/drafts",
                   json={"name":"API Preview","slug":"api-preview", "image":PINNED,
                         "container_port":8080}, headers=ORIGIN)
    assert draft.status_code == 201, draft.text
    data = c.get("/api/deployments/readiness").json()["data"]
    assert data["total_returned"] == 1
    row = data["drafts"][0]
    assert row["name"] == "API Preview"
    assert row["project"] == "Demo Project"
    assert row["environment"] == "Staging"
    assert row["image"] == PINNED
    assert row["status"] == "draft_only"
    assert row["executable"] is False
    assert row["blockers"] == ["execution_not_implemented", "server_not_assigned"]
    assert "manifest_json" not in str(data)
    assert agent.calls == []

    # Seed a different owner's project through SQL, without using the
    # authenticated owner API to prove the join enforces ownership.
    with sqlite3.connect(db) as connection:
        connection.execute("INSERT INTO projects VALUES (?,?,?,?,?,?)",
                           ("b" * 32,"another-owner","Private","private",None,int(time.time())))
        connection.execute("INSERT INTO environments VALUES (?,?,?,?,?)",
                           ("c" * 32,"b" * 32,"Private","private",int(time.time())))
        connection.execute("INSERT INTO service_drafts VALUES (?,?,?,?,?,?)",
                           ("d" * 32,"c" * 32,"Secret name","private",
                            '{"image":"secret-image-private"}',int(time.time())))
    data = c.get("/api/deployments/readiness").json()["data"]
    assert data["total_returned"] == 1
    assert "Secret name" not in str(data)
    assert "secret-image-private" not in str(data)
    assert DeploymentReadiness(db).list_drafts("another-owner")["total_returned"] == 1
    assert DeploymentReadiness(db).list_drafts("nobody")["drafts"] == []


def test_no_mutating_deployments_monitoring_or_settings_routes(tmp_path):
    c, _, agent = setup(tmp_path)
    login(c)
    for url in ("/api/deployments/readiness", "/api/monitoring/overview",
                "/api/settings/security"):
        assert c.post(url, json={"execute":True},headers=ORIGIN).status_code == 405
        assert c.delete(url, headers=ORIGIN).status_code == 405
    assert agent.calls == []


def test_page_navigation_is_active_and_read_only():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    html = (root / "web/index.html").read_text()
    js = (root / "web/app.js").read_text()
    for key in ("monitoring", "deployments", "settings"):
        assert f'data-view="{key}"' in html
    assert "/api/monitoring/overview" in js
    assert "/api/deployments/readiness" in js
    assert "/api/settings/security" in js
    assert "/api/deployments/jobs?limit=50" in js
    assert "no UI execution buttons" in js
    assert "showDraftReview(d)" in js
    assert "saveDraftJob(d, dryRun)" in js
    assert "execute: false" in js
    assert "No container will be created or changed" in js


def test_evidence_packet_ui_never_exposes_clear_or_execute_button():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    html = (root / "web/index.html").read_text()
    js = (root / "web/app.js").read_text()
    assert 'id="job-review-dialog"' in html
    assert "showJobReviewPacket(j)" in js
    assert "/review-packet" in js
    assert "Host lock released: NO" in js
    assert "Independent host attestation: NOT VERIFIED" in js
    assert "/review-evidence" not in js  # Backend API is operator-only for now.
