"""Phase A review evidence is append-only metadata and cannot unlock Docker jobs."""
from __future__ import annotations

import hashlib
import sqlite3
import time

import pytest
from fastapi.testclient import TestClient

from panel.api import Settings, create_app
from panel.auth import AuthStore
from panel.local_jobs import LocalJobs
from panel.manifests import ServiceDraft
from panel.registry import Registry, RegistryError
from panel.review_evidence import JobReviewEvidence

ORIGIN = {"Origin": "http://127.0.0.1:8086"}
APPROVAL = {**ORIGIN, "X-MTPanel-Approval": "RECORD_REVIEW_EVIDENCE"}
PASS = "Review evidence test-only owner password"
IMAGE = "example.test/app@sha256:" + "c" * 64
REFERENCE = hashlib.sha256(b"external operator ticket; no host attestation").hexdigest()


class NoDockerAgent:
    def __init__(self):
        self.calls = []

    async def lab_action(self, *args):
        self.calls.append(("write", args))
        raise AssertionError("Review evidence must never execute an agent action")

    async def lab_candidate(self, *args):
        self.calls.append(("inspect", args))
        raise AssertionError("Review evidence must never inspect an agent")


def seed(db_path: str):
    AuthStore(db_path).create_admin("owner", PASS)
    registry = Registry(db_path)
    server = registry.add_server("owner", "Disposable test only")["id"]
    project = registry.add_project("owner", "Case study", "case-study", server)["id"]
    env = registry.add_environment("owner", project, "Lab", "lab")["id"]
    draft = registry.add_draft("owner", env, ServiceDraft(
        name="Unresolved app", slug="unresolved-app", image=IMAGE,
        container_port=8080))["id"]
    jobs = LocalJobs(db_path)
    job = jobs.create("owner", draft, "unresolved-review-123456789",
                      server, execute=True)
    lease = jobs.claim("owner", job["id"], server)
    jobs.finish("owner", job["id"], lease["token"],
                "NEEDS_REVIEW", "agent_unconfirmed")
    return jobs, server, job["id"]


def login(client):
    resp = client.post("/api/auth/login", headers=ORIGIN,
                       json={"username": "owner", "password": PASS})
    assert resp.status_code == 200, resp.text


def test_review_packet_deterministic_and_safe(tmp_path):
    db = str(tmp_path / "panel.db")
    jobs, server, jid = seed(db)
    reviewer = JobReviewEvidence(db)
    a = reviewer.packet("owner", jid)
    b = JobReviewEvidence(db).packet("owner", jid)
    assert a["packet_digest"] == b["packet_digest"]
    assert len(a["packet_digest"]) == 64
    assert a["state"] == "NEEDS_REVIEW"
    assert a["manifest_sha256"]
    assert a["review_eligible"] is True
    assert a["host_lock_released"] is False
    assert a["safe_to_retry"] is False
    assert a["evidence_trusted"] is False
    assert "manual_host_clearance_not_implemented" in a["missing_safety_gates"]
    assert "manifest_json" not in str(a)
    assert "lease_token" not in str(a)
    assert "agent_unconfirmed" in str(a["events"])
    with pytest.raises(RegistryError):
        reviewer.packet("other-owner", jid)
    with pytest.raises(RegistryError):
        reviewer.packet("owner", "a" * 32)


def test_review_evidence_insert_duplicate_and_host_lock(tmp_path):
    db = str(tmp_path / "panel.db")
    jobs, server, jid = seed(db)
    reviewer = JobReviewEvidence(db)
    digest = reviewer.packet("owner", jid)["packet_digest"]
    a = reviewer.record("owner", jid, digest, "manual_investigation", REFERENCE)
    assert a["duplicate"] is False
    assert a["host_lock_released"] is False
    assert a["safe_to_retry"] is False
    assert a["trusted_attestation"] is False
    b = reviewer.record("owner", jid, digest, "manual_investigation", REFERENCE)
    assert b["duplicate"] is True
    assert reviewer.packet("owner", jid)["packet_digest"] == digest
    assert len(reviewer.packet("owner", jid)["evidence"]) == 1
    assert jobs.details("owner", jid)["state"] == "NEEDS_REVIEW"
    with sqlite3.connect(db) as con:
        assert con.execute(
            "SELECT COUNT(*) FROM audit_events WHERE action='lab.job.review_evidence_recorded'"
        ).fetchone()[0] == 1
        assert con.execute(
            "SELECT COUNT(*) FROM local_job_review_evidence"
        ).fetchone()[0] == 1
    other = jobs.create("owner", jobs.details("owner", jid)["draft_id"],
                        "other-waiting-job-123456", server, execute=True)
    with pytest.raises(RegistryError, match="un-reconciled"):
        jobs.claim("owner", other["id"], server)


def test_reject_stale_packet_and_wrong_owner(tmp_path):
    db = str(tmp_path / "panel.db")
    jobs, server, jid = seed(db)
    reviewer = JobReviewEvidence(db)
    first = reviewer.packet("owner", jid)["packet_digest"]
    with pytest.raises(RegistryError):
        reviewer.record("other-owner", jid, first, "manual_investigation", REFERENCE)
    with pytest.raises(RegistryError):
        reviewer.record("owner", jid, first, "unknown", REFERENCE)
    with pytest.raises(RegistryError):
        reviewer.record("owner", jid, first, "manual_investigation", "bad")
    # Any new state transition / reconciliation invalidates an old packet.
    jobs.record_recovery("owner", jid, server, "stopped")
    assert reviewer.packet("owner", jid)["packet_digest"] != first
    with pytest.raises(RegistryError, match="stale"):
        reviewer.record("owner", jid, first, "candidate_inspected", REFERENCE)


def test_review_rejected_for_non_blocked_jobs(tmp_path):
    db = str(tmp_path / "panel.db")
    jobs, server, jid = seed(db)
    reviewer = JobReviewEvidence(db)
    draft = jobs.details("owner", jid)["draft_id"]
    pending = jobs.create("owner", draft, "dry-job-review-123456789", "", execute=False)
    packet = reviewer.packet("owner", pending["id"])
    assert packet["review_eligible"] is False
    with pytest.raises(RegistryError, match="NEEDS_REVIEW"):
        reviewer.record("owner", pending["id"],
                        packet["packet_digest"], "manual_investigation", REFERENCE)


def test_session_origin_approval_and_no_agent_calls(tmp_path):
    db = str(tmp_path / "panel.db")
    jobs, server, jid = seed(db)
    agent = NoDockerAgent()
    client = TestClient(create_app(Settings(
        db, "http://127.0.0.1:8788", "x" * 64,
        "http://127.0.0.1:8086"), agent))
    path = f"/api/deployments/jobs/{jid}"
    assert client.get(path + "/review-packet").status_code == 401
    assert client.post(path + "/review-evidence", json={}).status_code == 401
    login(client)
    packet_resp = client.get(path + "/review-packet")
    assert packet_resp.status_code == 200, packet_resp.text
    data = packet_resp.json()["data"]
    body = {"packet_digest": data["packet_digest"],
            "reason_code": "agent_unreachable", "evidence_ref": REFERENCE}
    assert client.post(path + "/review-evidence", json=body).status_code == 403
    assert client.post(path + "/review-evidence", json=body,
                       headers=ORIGIN).status_code == 403
    assert client.post(path + "/review-evidence", json=body,
                       headers={**APPROVAL, "Origin": "https://evil.example"}).status_code == 403
    assert client.post(path + "/review-evidence", json={
        **body, "arbitrary_docker_path": "/containers/unrelated/restart"
    }, headers=APPROVAL).status_code == 422
    saved = client.post(path + "/review-evidence", json=body, headers=APPROVAL)
    assert saved.status_code == 201, saved.text
    assert saved.json()["data"]["trusted_attestation"] is False
    assert jobs.details("owner", jid)["state"] == "NEEDS_REVIEW"
    assert client.get(path + "/review-packet").json()["data"]["evidence"][0][
        "reason_code"] == "agent_unreachable"
    assert agent.calls == []


def test_no_new_docker_and_no_secret_leaks_in_module():
    from pathlib import Path
    contents = (Path(__file__).resolve().parent.parent /
                "panel/review_evidence.py").read_text()
    for forbidden in ("docker.sock", "docker exec", "subprocess", "os.system",
                      "HttpClient", "AGENT_TOKEN", "EXECUTION_KEY"):
        assert forbidden not in contents
