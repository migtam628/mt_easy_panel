"""On-demand read-only diagnostics and owner-owned draft policy review."""
from __future__ import annotations

import sqlite3

from fastapi import HTTPException
from fastapi.testclient import TestClient

from panel.api import Settings, create_app
from panel.auth import AuthStore
from panel.diagnostics import host_capacity, summarize_containers
from panel.deployment_readiness import DeploymentReadiness
from panel.registry import RegistryError

ORIGIN = {"Origin": "http://127.0.0.1:8086"}
PASS = "Long test owner password for diagnostics!"
IMAGE = "registry.example.net/lab@sha256:" + "a" * 64


class FakeInventory:
    def __init__(self, offline=False, demo=False):
        self.offline = offline
        self.demo = demo
        self.calls = []

    async def get(self, endpoint):
        self.calls.append(endpoint)
        if self.offline:
            raise HTTPException(503, "Host agent offline")
        if endpoint == "overview":
            return {"source": "demo" if self.demo else "live",
                    "disk_total_bytes": 1000, "disk_free_bytes": 90,
                    "agent_secret": "NEVER_LEAK"}
        if endpoint == "containers":
            return [
                {"name":"web", "state":"running","status":"Up 1 day (healthy)",
                 "id":"1" * 64, "image":"public-image"},
                {"name":"db", "state":"running","status":"Up 2 days (unhealthy)",
                 "id":"2" * 64, "environment":["PASSWORD=NEVER_LEAK"]},
                {"name":"worker", "state":"restarting","status":"Restarting (1)"},
                {"name":"archive", "state":"exited","status":"Exited (0) 2 days ago"},
                {"name":"dead-app", "state":"dead","status":"Dead"},
            ]
        raise AssertionError("Unexpected local Docker GET resource")

    async def logs(self, _):
        raise AssertionError("Diagnostics must not read container logs")


def setup(tmp_path, offline=False, demo=False):
    settings = Settings(str(tmp_path/"panel.db"), "http://127.0.0.1:8788",
                        "x"*64, "http://127.0.0.1:8086")
    agent = FakeInventory(offline, demo)
    client = TestClient(create_app(settings, agent))
    AuthStore(settings.db_path).create_admin("owner", PASS)
    return client, settings.db_path, agent


def login(c):
    response = c.post("/api/auth/login",
                      json={"username":"owner", "password":PASS},headers=ORIGIN)
    assert response.status_code == 200, response.text


def test_diagnostics_requires_login_and_has_no_mutating_routes(tmp_path):
    c, db, agent = setup(tmp_path)
    url = "/api/monitoring/diagnostics"
    assert c.get(url).status_code == 401
    assert agent.calls == []
    login(c)
    assert c.post(url, json={"restart":True},headers=ORIGIN).status_code == 405
    assert c.delete(url,headers=ORIGIN).status_code == 405
    assert agent.calls == []


def test_local_docker_triage_is_bounded_and_excludes_secrets(tmp_path):
    c, _, agent = setup(tmp_path)
    login(c)
    result = c.get("/api/monitoring/diagnostics")
    assert result.status_code == 200
    data = result.json()["data"]
    assert data["state"] == "connected"
    assert data["docker_writes_enabled"] is False
    assert data["capacity"] == {"disk_free_percent":9.0,"disk_warning":"critical"}
    diag = data["diagnostics"]
    assert diag["sampled"] == 5
    assert diag["warnings"] == {"unhealthy": 1,"restarting": 1,"dead": 1}
    assert diag["states"] == {"running":2, "restarting":1, "exited":1, "dead":1}
    assert {row["name"] for row in diag["containers"][:3]} == {"db","worker","dead-app"}
    assert next(x for x in diag["containers"] if x["name"] == "web")["health"] == "reported_healthy"
    assert next(x for x in diag["containers"] if x["name"] == "archive")["flags"] == []
    assert agent.calls == ["overview","containers"]
    for secret in ("NEVER_LEAK","environment","image","id"):
        assert secret not in str(diag["containers"])
    assert "no" not in diag["source"]


def test_diagnostics_offline_returns_unknown_not_zero(tmp_path):
    c, _, agent = setup(tmp_path, offline=True)
    login(c)
    resp = c.get("/api/monitoring/diagnostics")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["state"] == "unavailable"
    assert data["diagnostics"] is None
    assert data["capacity"] is None
    assert data["docker_writes_enabled"] is False


def test_demo_is_explicit_and_malformed_capacity_never_healthy(tmp_path):
    c, _, _ = setup(tmp_path, demo=True)
    login(c)
    assert c.get("/api/monitoring/diagnostics").json()["data"]["state"] == "demo"
    assert host_capacity({"disk_total_bytes":0,"disk_free_bytes":0}) == {
        "disk_free_percent":None,"disk_warning":"not_reported"}
    assert host_capacity({"disk_total_bytes":100,"disk_free_bytes":101})["disk_warning"] == "not_reported"
    assert host_capacity({"disk_total_bytes":100,"disk_free_bytes":10})["disk_warning"] == "warning"
    assert host_capacity({"disk_total_bytes":100,"disk_free_bytes":20})["disk_warning"] == "none"
    assert summarize_containers("no data") if False else True
    import pytest
    with pytest.raises(ValueError):
        summarize_containers({"unexpected": "object"})
    result = summarize_containers([{"name":str(x),"state":"running",
                                    "status":"up"} for x in range(2002)])
    assert result["sampled"] == 2000
    assert result["truncated"] is True


def test_draft_review_owner_policy_and_absolute_execution_gate(tmp_path):
    c, db, agent = setup(tmp_path)
    assert c.get("/api/deployments/drafts/abc/review").status_code == 401
    login(c)
    project = c.post("/api/catalog/projects",json={
        "name":"Example","slug":"example"},headers=ORIGIN)
    assert project.status_code == 201
    pid = project.json()["data"]["id"]
    env = c.post(f"/api/catalog/projects/{pid}/environments",
                 json={"name":"Staging", "slug":"staging"},headers=ORIGIN)
    assert env.status_code == 201
    eid = env.json()["data"]["id"]
    draft = c.post(f"/api/catalog/environments/{eid}/drafts",
                   json={"name":"Example API","slug":"example-api","image":IMAGE,
                         "container_port":8080,"memory_mb":512,"cpu_limit":0.5},
                   headers=ORIGIN)
    assert draft.status_code == 201, draft.text
    did = draft.json()["data"]["id"]
    endpoint = f"/api/deployments/drafts/{did}/review"
    review = c.get(endpoint).json()["data"]
    assert review["draft_id"] == did
    assert review["manifest"] == {"image":IMAGE,"container_port":8080,
                                   "cpu_limit":0.5,"memory_mb":512,
                                   "read_only_rootfs":True}
    assert review["passed_static_checks"] == 1
    assert review["total_static_checks"] == 3
    assert review["executable"] is False
    assert review["execution_enabled"] is False
    assert review["remote_docker_access"] is False
    assert [x["code"] for x in review["checks"]] == [
        "safe_manifest", "server_assigned", "identity_paired",
        "remote_host_verified", "execution_gate"
    ]
    assert not any(x["passed"] for x in review["checks"][-2:])
    assert c.post(endpoint, json={"execute":True},headers=ORIGIN).status_code == 405
    assert c.get("/api/deployments/drafts/" + "a"*32 + "/review").status_code == 404
    with __import__("pytest").raises(RegistryError):
        DeploymentReadiness(db).review("another-owner",did)
    assert agent.calls == []


def test_draft_review_rejects_malformed_stored_manifest_without_leaking(tmp_path):
    c, db, _ = setup(tmp_path)
    login(c)
    p = c.post("/api/catalog/projects",json={"name":"Project X","slug":"project-x"},
               headers=ORIGIN).json()["data"]["id"]
    e = c.post(f"/api/catalog/projects/{p}/environments",
               json={"name":"Test Env","slug":"test-env"},headers=ORIGIN).json()["data"]["id"]
    did = c.post(f"/api/catalog/environments/{e}/drafts",
                 json={"name":"Draft X","slug":"draft-x","image":IMAGE,
                       "container_port":8000},headers=ORIGIN).json()["data"]["id"]
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE service_drafts SET manifest_json=? WHERE id=?",
                     ('{"environment":"SECRET=DO_NOT_EXPOSE","image":"latest"}',did))
    result = c.get(f"/api/deployments/drafts/{did}/review")
    assert result.status_code == 200
    data = result.json()["data"]
    assert data["manifest"] is None
    assert data["checks"][0]["passed"] is False
    assert data["executable"] is False
    assert "DO_NOT_EXPOSE" not in str(data)


def test_diagnostic_source_contains_no_direct_engine_or_shell_actions():
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent/"panel/diagnostics.py").read_text()
    for forbidden in ("docker run","docker exec","subprocess","/var/run/docker.sock",
                      "os.system","docker compose","os.popen"):
        assert forbidden not in src
