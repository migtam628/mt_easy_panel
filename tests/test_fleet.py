"""Owner-scoped read-only fleet monitoring and safe credential lifecycle."""
from __future__ import annotations

import base64
import secrets
import sqlite3
import time

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from fastapi.testclient import TestClient

from panel.api import Settings, create_app
from panel.auth import AuthStore
from panel.enrollment import signed_enrollment_message, signed_heartbeat_message
from panel.fleet import FleetStore
from protocol.host_snapshot import HostSnapshot, host_report_message

ORIGIN = {"Origin": "http://127.0.0.1:8086"}
PASS = "Private secure admin passphrase for test 2026"
SAMPLE = {
    "hostname": "vm-01", "system": "Linux 6.17", "cpu_count": 4,
    "memory_total_bytes": 8589934592,
    "disk_total_bytes": 100000000000,
    "disk_free_bytes": 30000000000,
    "uptime_seconds": 2000,
}


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def setup(tmp_path):
    db = str(tmp_path / "fleet.db")
    app = create_app(Settings(db, "http://127.0.0.1:8788",
                              "x" * 64, "http://127.0.0.1:8086"))
    c = TestClient(app)
    AuthStore(db).create_admin("owner", PASS)
    assert c.post("/api/auth/login", json={"username": "owner", "password": PASS},
                  headers=ORIGIN).status_code == 200
    return c, db


def create_server(client, name="Test remote"):
    r = client.post("/api/catalog/servers", json={"name": name}, headers=ORIGIN)
    assert r.status_code == 201, r.text
    return r.json()["data"]["id"]


def enroll(client, server_id, key=None):
    code = client.post(f"/api/catalog/servers/{server_id}/invites",
                       headers=ORIGIN).json()["data"]["enrollment_code"]
    key = key or Ed25519PrivateKey.generate()
    nonce = secrets.token_urlsafe(32)
    body = {
        "server_id": server_id, "code": code,
        "nonce": nonce,
        "public_key": b64(key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw)),
        "signature": b64(key.sign(signed_enrollment_message(server_id, nonce))),
    }
    response = client.post("/api/agents/enroll", json=body)
    assert response.status_code == 200, response.text
    return key


def heartbeat(client, server, key, seq):
    when = int(time.time())
    body = {"sequence": seq, "timestamp": when,
            "signature": b64(key.sign(signed_heartbeat_message(server, seq, when)))}
    return client.post(f"/api/agents/{server}/heartbeat", json=body)


def host_report(client, server, key, seq):
    when = int(time.time())
    snap = HostSnapshot.model_validate(SAMPLE)
    body = {"sequence": seq, "timestamp": when, "snapshot": snap.model_dump(),
            "signature": b64(key.sign(host_report_message(server, seq, when, snap)))}
    return client.post(f"/api/agents/{server}/host-report", json=body)


def test_fleet_owner_only_and_lifecycle(tmp_path):
    client, db = setup(tmp_path)
    endpoint = "/api/fleet/summary"
    anonymous = TestClient(create_app(Settings(db, "http://127.0.0.1:8788",
                                               "x" * 64, "http://127.0.0.1:8086")))
    assert anonymous.get(endpoint).status_code == 401
    sid = create_server(client)
    response = client.get(endpoint)
    assert response.status_code == 200
    fleet = response.json()["data"]
    assert fleet["remote_docker_access"] is False
    assert fleet["counts"]["unpaired"] == 1
    assert fleet["servers"][0]["heartbeat_state"] == "unpaired"
    assert fleet["servers"][0]["health"] is None
    assert not any("token" in str(k).lower() for k in fleet["servers"][0])

    key = enroll(client, sid)
    fleet = client.get(endpoint).json()["data"]
    assert fleet["servers"][0]["heartbeat_state"] == "never_seen"
    assert heartbeat(client, sid, key, 1).status_code == 200
    assert host_report(client, sid, key, 2).status_code == 200
    fleet = client.get(endpoint).json()["data"]
    assert fleet["counts"]["paired"] == 1
    assert fleet["counts"]["heartbeat_recent"] == 1
    assert fleet["counts"]["report_recent"] == 1
    assert fleet["servers"][0]["health"]["disk_free_percent"] == 30.0
    assert fleet["servers"][0]["health"]["hostname"] == "vm-01"
    assert "snapshot_json" not in str(fleet)
    assert "public_key" not in str(fleet)

    # Timestamp aging must be computed on each owner request.
    with sqlite3.connect(db) as dbconn:
        dbconn.execute("UPDATE agent_identities SET last_seen=? WHERE server_id=?",
                       (int(time.time()) - 600, sid))
        dbconn.execute("UPDATE host_snapshots SET recorded_at=? WHERE server_id=?",
                       (int(time.time()) - 600, sid))
    fleet = client.get(endpoint).json()["data"]
    assert fleet["servers"][0]["heartbeat_state"] == "stale"
    assert fleet["servers"][0]["report_state"] == "stale"

    # Revoking an identity must clear its prior report, not just hide it.
    assert client.post(f"/api/catalog/servers/{sid}/revoke",
                       headers=ORIGIN).status_code == 200
    with sqlite3.connect(db) as dbconn:
        assert dbconn.execute("SELECT COUNT(*) FROM host_snapshots").fetchone()[0] == 0
    fleet = client.get(endpoint).json()["data"]
    assert fleet["counts"]["revoked"] == 1
    assert fleet["servers"][0]["health"] is None
    assert fleet["servers"][0]["last_report"] is None

    # A new key cannot inherit telemetry attributed to the revoked key.
    other = enroll(client, sid)
    assert other is not key
    fleet = client.get(endpoint).json()["data"]
    assert fleet["counts"]["paired"] == 1
    assert fleet["servers"][0]["report_state"] == "never_seen"
    assert fleet["servers"][0]["health"] is None
    assert heartbeat(client, sid, key, 3).status_code == 401


def test_fleet_scope_does_not_expose_other_owners(tmp_path):
    client, db = setup(tmp_path)
    s1 = create_server(client, "Primary")
    fleet = FleetStore(db)
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO servers VALUES (?,?,?,?,?,?)",
                     ("b" * 32, "another-owner", "Other VM", "Private", "unpaired", int(time.time())))
    assert [x["id"] for x in fleet.summary("owner")["servers"]] == [s1]
    assert [x["id"] for x in fleet.summary("another-owner")["servers"]] == ["b" * 32]
    assert fleet.summary("not-an-owner")["servers"] == []


def test_fleet_response_limit_and_no_remote_actions(tmp_path):
    _, db = setup(tmp_path)
    with sqlite3.connect(db) as conn:
        conn.executemany("INSERT INTO servers VALUES (?,?,?,?,?,?)", [
            (f"{n:032x}", "owner", f"Agent {n:03d}", "", "unpaired", 1)
            for n in range(510)
        ])
    result = FleetStore(db).summary("owner")
    assert len(result["servers"]) == 500
    assert result["truncated"] is True
    assert result["counts"]["unpaired"] == 500
