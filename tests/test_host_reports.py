"""Signed outbound host reports: fixed schema, owner scope, replay and revocation."""
from __future__ import annotations
import base64
import json
import sqlite3
import time
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from fastapi.testclient import TestClient
from pydantic import ValidationError

from agent import host_probe
from panel.api import Settings, create_app
from panel.auth import AuthStore
from panel.enrollment import signed_enrollment_message, signed_heartbeat_message
from panel.host_reports import HostReports
from panel.registry import RegistryError
from protocol.host_snapshot import HostSnapshot, host_report_message

ORIGIN = {"Origin": "http://127.0.0.1:8086"}
PASSWORD = "A long private test password 2026 secure"
HOST_REPORT = {
    "hostname": "disposable-vm",
    "system": "Linux 6.17",
    "cpu_count": 2,
    "memory_total_bytes": 8 * 1024**3,
    "disk_total_bytes": 100 * 1024**3,
    "disk_free_bytes": 44 * 1024**3,
    "uptime_seconds": 2500,
}


def b64(data):
    return base64.b64encode(data).decode("ascii")


def setup(tmp_path):
    db = str(tmp_path / "panel.db")
    c = TestClient(create_app(Settings(db, "http://127.0.0.1:8788",
                                       "t" * 64, "http://127.0.0.1:8086")))
    AuthStore(db).create_admin("admin", PASSWORD)
    assert c.post("/api/auth/login", json={"username": "admin", "password": PASSWORD},
                  headers=ORIGIN).status_code == 200
    server_result = c.post("/api/catalog/servers", json={"name": "Sample VM"},
                           headers=ORIGIN)
    assert server_result.status_code == 201
    server = server_result.json()["data"]["id"]
    code = c.post(f"/api/catalog/servers/{server}/invites",
                  headers=ORIGIN).json()["data"]["enrollment_code"]
    key = Ed25519PrivateKey.generate()
    nonce = __import__("secrets").token_urlsafe(32)
    claim = {"server_id": server, "code": code,
             "public_key": b64(key.public_key().public_bytes(
                 serialization.Encoding.Raw, serialization.PublicFormat.Raw)),
             "nonce": nonce,
             "signature": b64(key.sign(signed_enrollment_message(server, nonce)))}
    assert c.post("/api/agents/enroll", json=claim).status_code == 200
    return c, db, server, key


def payload(server, key, sequence=1, timestamp=None, snapshot=None):
    timestamp = int(time.time()) if timestamp is None else timestamp
    snap = HostSnapshot.model_validate(snapshot or HOST_REPORT)
    return {"sequence": sequence, "timestamp": timestamp,
            "snapshot": snap.model_dump(),
            "signature": b64(key.sign(host_report_message(server, sequence, timestamp, snap)))}


def test_authorization_replay_and_revocation(tmp_path):
    c, db, server, key = setup(tmp_path)
    url = f"/api/agents/{server}/host-report"
    read = f"/api/catalog/servers/{server}/host-report"
    assert c.get(read).json()["data"]["state"] == "never_seen"
    first = payload(server, key)
    assert c.post(url, json=first).status_code == 200
    data = c.get(read).json()["data"]
    assert data["state"] == "recent"
    assert data["snapshot"] == HOST_REPORT
    assert "token" not in str(data).lower()
    assert c.post(url, json=first).status_code == 401
    tampered = payload(server, key, 2)
    tampered["snapshot"]["cpu_count"] = 9
    assert c.post(url, json=tampered).status_code == 401
    assert c.post(url, json=payload(server, key, 2,
            timestamp=int(time.time()) - 600)).status_code == 401
    other = Ed25519PrivateKey.generate()
    assert c.post(url, json=payload(server, other, 2)).status_code == 401
    assert c.post(url, json=payload(server, key, 2)).status_code == 200

    # Sequence space is shared with ordinary signed heartbeat traffic.
    heartbeat_ts = int(time.time())
    hb = {"sequence": 3, "timestamp": heartbeat_ts,
          "signature": b64(key.sign(signed_heartbeat_message(server, 3, heartbeat_ts)))}
    assert c.post(f"/api/agents/{server}/heartbeat", json=hb).status_code == 200
    assert c.post(url, json=payload(server, key, 3)).status_code == 401

    with pytest.raises(RegistryError):
        HostReports(db).get("another-owner", server)
    assert c.post(f"/api/catalog/servers/{server}/revoke", headers=ORIGIN).status_code == 200
    assert c.post(url, json=payload(server, key, 4)).status_code == 401
    assert c.get(read).json()["data"]["state"] == "not_connected"


def test_schema_rejects_unexpected_and_impossible_fields(tmp_path):
    c, _, server, key = setup(tmp_path)
    endpoint = f"/api/agents/{server}/host-report"
    assert c.post(endpoint, json={**payload(server, key), "container_command": "restart"}).status_code == 422
    base = payload(server, key)
    for invalid in [
        {**HOST_REPORT, "docker_socket": "/var/run/docker.sock"},
        {**HOST_REPORT, "cpu_count": True},
        {**HOST_REPORT, "hostname": "../escape"},
        {**HOST_REPORT, "disk_free_bytes": HOST_REPORT["disk_total_bytes"] + 1},
        {**HOST_REPORT, "system": "Linux\nsecret"},
    ]:
        with pytest.raises(ValidationError):
            HostSnapshot.model_validate(invalid)
        malformed = {**base, "snapshot": invalid}
        assert c.post(endpoint, json=malformed).status_code == 422


def test_report_staleness_and_database_persistence(tmp_path):
    c, db, server, key = setup(tmp_path)
    assert c.post(f"/api/agents/{server}/host-report",
                  json=payload(server, key)).status_code == 200
    with sqlite3.connect(db) as connection:
        connection.execute("UPDATE host_snapshots SET recorded_at=? WHERE server_id=?",
                           (int(time.time()) - 600, server))
    data = HostReports(db).get("admin", server)
    assert data["state"] == "stale"
    assert data["snapshot"]["hostname"] == "disposable-vm"


def test_agent_outbound_report_signing_without_real_network(tmp_path,monkeypatch):
    c, db, server, key = setup(tmp_path)
    path = tmp_path / "id.pem"
    path.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                 serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    path.chmod(0o600)
    monkeypatch.setattr(host_probe, "collect_host_snapshot",
                        lambda: HostSnapshot.model_validate(HOST_REPORT))

    def fake_request(origin, endpoint, body):
        assert origin == "https://node.tailnet.ts.net:8443"
        assert endpoint == f"/api/agents/{server}/host-report"
        response = c.post(endpoint, json=body)
        assert response.status_code == 200, response.text
        return response.json()["data"]

    monkeypatch.setattr(host_probe, "request", fake_request)
    result = host_probe.submit_report("https://node.tailnet.ts.net:8443", server, path)
    assert result["status"] == "accepted"
    assert c.get(f"/api/catalog/servers/{server}/host-report").json()["data"]["snapshot"] == HOST_REPORT


def test_probe_is_linux_only_and_never_requires_docker(monkeypatch):
    monkeypatch.setattr(host_probe.platform, "system", lambda: "Darwin")
    with pytest.raises(ValueError, match="Linux only"):
        host_probe.collect_host_snapshot()
    source=(Path(__file__).resolve().parent.parent / "agent/host_probe.py").read_text()
    assert "docker" not in source.lower().replace("no docker", "")
    assert "/var/run/docker.sock" not in source
