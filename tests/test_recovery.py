"""Fail-closed recovery: exact Docker identity, read-only observation and audit."""
import sqlite3
import time

import pytest
from fastapi.testclient import TestClient

from agent.api import DemoReader, create_app as create_agent
from agent.local_execution import ActionDenied, LocalDockerWriter
from agent.action_replay import ActionReplay
from panel.api import Settings, create_app as create_panel
from panel.auth import AuthStore
from panel.local_jobs import LocalJobs
from panel.manifests import ServiceDraft
from panel.registry import Registry, RegistryError
JID = "a" * 32
DID = "b" * 32
IMAGE = "example.test/app@sha256:" + "1" * 64
MANIFEST = ServiceDraft(name="Lab test", slug="lab-test",
                        image=IMAGE, container_port=8080)

class DockerFixture(LocalDockerWriter):
    def __init__(self):
        super().__init__("/unused-lab-socket", poll_delay=0, checks=2)
        self.container = None
        self.requests = []

    def _call(self, method, path, body=None, *, missing=False):
        self.requests.append((method, path, body))
        if path.startswith("/images/"):
            return {"Config": {"Healthcheck": {"Test": ["CMD", "true"]}}}
        if path.startswith("/containers/create?"):
            self.container = {
                "Name": "/mtpanel-lab-" + JID,
                "Config": {"Labels": body["Labels"], "Image": body["Image"]},
                "State": {"Running": False, "Health": {"Status": "starting"}},
            }
            return {"Id": "1" * 64}
        if path.endswith("/json"):
            return self.container
        if path.endswith("/start"):
            self.container["State"] = {"Running": True,
                "Health": {"Status": "healthy"}}
            return {}
        raise AssertionError("Unexpected Docker endpoint")

TOKEN = "s" * 64
KEY = "test-dedicated-lab-hmac-" + "w" * 40
ORIGIN = {"Origin": "http://127.0.0.1:8086"}
PASS = "Recovery test owner's password 2026!"
IMAGE2 = "example.test/second@sha256:" + "a" * 64


def catalog(db):
    AuthStore(db).create_admin("owner", PASS)
    registry = Registry(db)
    server = registry.add_server("owner", "Isolated lab host")["id"]
    project = registry.add_project("owner", "Lab recovery", "lab-recovery", server)["id"]
    environment = registry.add_environment("owner", project, "Test", "test")["id"]
    draft = registry.add_draft("owner", environment, ServiceDraft(
        name="Recovery app", slug="recovery-app", image=IMAGE,
        container_port=8080))["id"]
    return server, draft


def login(client):
    response = client.post("/api/auth/login",
                           json={"username": "owner", "password": PASS},
                           headers=ORIGIN)
    assert response.status_code == 200, response.text


class ReadOnlyRecoveryAgent:
    def __init__(self, status="running_healthy", failure=False):
        self.status = status
        self.failure = failure
        self.calls = []

    async def lab_candidate(self, job_id, draft_id, image_digest):
        self.calls.append((job_id, draft_id, image_digest))
        if self.failure:
            raise RuntimeError("Simulated agent outage")
        return {"observation": self.status, "present": self.status != "absent",
                "traffic_switched": False, "safe_to_retry": False}


def test_docker_candidate_observation_never_mutates_and_checks_image():
    docker = DockerFixture()
    assert docker.candidate_status(JID, DID, IMAGE)["observation"] == "absent"
    assert all(method == "GET" for method, _, _ in docker.requests)
    docker.create_candidate(JID, DID, MANIFEST)
    docker.lifecycle(JID, DID, "start")
    before = len(docker.requests)
    seen = docker.candidate_status(JID, DID, IMAGE)
    assert seen == {"observation": "running_healthy", "present": True,
                    "safe_to_retry": False, "traffic_switched": False}
    assert all(method == "GET" for method, _, _ in docker.requests[before:])
    with pytest.raises(ActionDenied, match="immutable"):
        docker.candidate_status(JID, DID, IMAGE2)
    with pytest.raises(ActionDenied, match="not owned"):
        docker.candidate_status(JID, "c"*32, IMAGE)


def test_agent_inspection_is_allowlisted_and_disabled_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENT_LOCAL_EXECUTION_ENABLED", raising=False)
    c = TestClient(create_agent(reader=DemoReader(), token=TOKEN))
    url = f"/v1/lab/candidates/{JID}"
    params = {"draft_id": DID, "image_digest": IMAGE}
    assert c.get(url, params=params).status_code == 401
    assert c.get(url, params=params,
                 headers={"Authorization": "Bearer " + TOKEN}).status_code == 403
    assert c.get("/health").json()["lab_execution_enabled"] is False


def test_agent_inspection_limited_to_exact_immutable_job(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_EXECUTION_LAB_ACK", "I_ACCEPT_DISPOSABLE_HOST_ONLY")
    docker = DockerFixture()
    docker.create_candidate(JID, DID, MANIFEST)
    c = TestClient(create_agent(reader=DemoReader(), token=TOKEN, writer=docker,
                 enable_local_writes=True, execution_key=KEY,
                 replay=ActionReplay(str(tmp_path / "actions.db"))))
    url = f"/v1/lab/candidates/{JID}"
    # Test client uses agent defaults but a temp replay DB for startup.
    headers = {"Authorization": "Bearer " + TOKEN}
    assert c.get(url, params={"draft_id": DID, "image_digest": IMAGE},
                 headers=headers).json()["data"]["observation"] == "stopped"
    assert c.get(url, params={"draft_id": "c"*32, "image_digest": IMAGE},
                 headers=headers).status_code == 409
    assert c.get(url, params={"draft_id": DID, "image_digest": IMAGE2},
                 headers=headers).status_code == 409
    assert c.get("/v1/lab/candidates/not-a-job", params={
        "draft_id": DID, "image_digest": IMAGE},headers=headers).status_code == 409


def test_expired_lease_recovery_observes_and_keeps_host_locked(tmp_path, monkeypatch):
    monkeypatch.setenv("PANEL_EXECUTION_LAB_ACK", "I_ACCEPT_DISPOSABLE_HOST_ONLY")
    db = str(tmp_path / "panel.db")
    server, draft = catalog(db)
    jobs = LocalJobs(db)
    first = jobs.create("owner", draft, "recovery_job_one_12345", server, execute=True)
    second = jobs.create("owner", draft, "recovery_job_two_12345", server, execute=True)
    claim = jobs.claim("owner", first["id"], server)
    agent = ReadOnlyRecoveryAgent()
    settings = Settings(db, "http://127.0.0.1:8788", TOKEN,
                        "http://127.0.0.1:8086", False, server, True, KEY)
    client = TestClient(create_panel(settings, agent))
    login(client)
    path = f"/api/deployments/jobs/{first['id']}"
    assert client.get(path + "/recovery").json()["data"]["observation"] == "running_healthy"
    assert client.post(path + "/reconcile", headers=ORIGIN).status_code == 403
    approval = {**ORIGIN, "X-MTPanel-Approval": "INSPECT_AND_HOLD"}
    assert client.post(path + "/reconcile", headers=approval).status_code == 409
    with sqlite3.connect(db) as con:
        con.execute("UPDATE local_deployment_jobs SET lease_until=? WHERE id=?",
                    (int(time.time()) - 10, first["id"]))
    reviewed = client.post(path + "/reconcile", headers=approval)
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["data"]["state"] == "NEEDS_REVIEW"
    assert jobs.details("owner", first["id"])["events"][-1]["code"] == "reconcile_running_healthy"
    assert jobs.details("owner", first["id"])["error_code"] == "operator_review_required"
    with pytest.raises(RegistryError, match="un-reconciled"):
        jobs.claim("owner", second["id"], server)
    with pytest.raises(RegistryError):
        jobs.finish("owner", first["id"], claim["token"], "HEALTHY")
    assert agent.calls and all(entry[2] == IMAGE for entry in agent.calls)


def test_unknown_and_absent_candidates_never_release_host(tmp_path, monkeypatch):
    monkeypatch.setenv("PANEL_EXECUTION_LAB_ACK", "I_ACCEPT_DISPOSABLE_HOST_ONLY")
    db = str(tmp_path / "panel.db")
    server, draft = catalog(db)
    jobs = LocalJobs(db)
    job = jobs.create("owner", draft, "recovery_absent_job_12345", server, execute=True)
    token = jobs.claim("owner", job["id"], server)["token"]
    jobs.finish("owner", job["id"], token, "NEEDS_REVIEW", "agent_unconfirmed")
    agent = ReadOnlyRecoveryAgent(status="absent")
    client = TestClient(create_panel(Settings(
        db, "http://127.0.0.1:8788", TOKEN,
        "http://127.0.0.1:8086", False, server, True, KEY), agent))
    login(client)
    path = f"/api/deployments/jobs/{job['id']}"
    assert client.get(path + "/recovery").json()["data"]["safe_to_retry"] is False
    approved = {**ORIGIN, "X-MTPanel-Approval": "INSPECT_AND_HOLD"}
    assert client.post(path + "/reconcile", headers=approved).status_code == 200
    assert jobs.details("owner", job["id"])["state"] == "NEEDS_REVIEW"
    agent.failure = True
    assert client.get(path + "/recovery").status_code == 503
    # Error responses never permit writes or unlock the host.
    assert jobs.details("owner", job["id"])["state"] == "NEEDS_REVIEW"


def test_read_only_production_panel_never_inspects_lab_docker(tmp_path):
    db = str(tmp_path / "panel.db")
    _, draft = catalog(db)
    agent = ReadOnlyRecoveryAgent()
    client = TestClient(create_panel(Settings(db, "http://127.0.0.1:8788",
        TOKEN, "http://127.0.0.1:8086"), agent))
    login(client)
    job = client.post(f"/api/deployments/drafts/{draft}/jobs",
                      headers=ORIGIN, json={"idempotency_key":"disabled_draft_12345"})
    assert job.status_code == 201, job.text
    path = f"/api/deployments/jobs/{job.json()['data']['id']}"
    recovery = client.get(path + "/recovery")
    assert recovery.status_code == 200
    assert recovery.json()["data"]["observation"] == "disabled"
    assert client.post(path + "/reconcile", headers={
        **ORIGIN,"X-MTPanel-Approval":"INSPECT_AND_HOLD"}).status_code == 403
    assert agent.calls == []
