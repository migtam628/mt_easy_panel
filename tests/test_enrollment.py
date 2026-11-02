"""Ed25519 identity enrollment, single-use codes, replay defense and revocation."""
from __future__ import annotations
import base64
import sqlite3
import time

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from fastapi.testclient import TestClient

from panel.api import Settings, create_app
from panel.auth import AuthStore
from panel.enrollment import EnrollmentStore, signed_enrollment_message, signed_heartbeat_message
from panel.registry import Registry
from agent.enroll import checked_origin

ORIGIN = {"Origin": "http://127.0.0.1:8086"}
PASSWORD = "A totally unique passphrase 2026!"


def b64(x: bytes) -> str:
    return base64.b64encode(x).decode("ascii")


def setup(tmp_path):
    path = str(tmp_path / "panel.db")
    app = create_app(Settings(path, "http://127.0.0.1:8788",
                              "t" * 64, "http://127.0.0.1:8086"))
    client = TestClient(app)
    AuthStore(path).create_admin("admin", PASSWORD)
    result = client.post("/api/auth/login", json={"username": "admin", "password": PASSWORD},
                         headers=ORIGIN)
    assert result.status_code == 200, result.text
    server = client.post("/api/catalog/servers",
                         json={"name": "Remote test VPS"}, headers=ORIGIN)
    assert server.status_code == 201, server.text
    return client, path, server.json()["data"]["id"]


def signed_claim(server_id, code, key=None):
    key = key or Ed25519PrivateKey.generate()
    nonce = __import__("secrets").token_urlsafe(32)
    return key, {
        "server_id": server_id, "code": code,
        "public_key": b64(key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw)),
        "signature": b64(key.sign(signed_enrollment_message(server_id, nonce))),
        "nonce": nonce
    }


def signed_ping(server_id, key, seq=1, timestamp=None):
    timestamp = int(time.time()) if timestamp is None else timestamp
    return {"sequence": seq, "timestamp": timestamp,
            "signature": b64(key.sign(signed_heartbeat_message(server_id, seq, timestamp)))}


def test_owner_origin_and_one_time_enrollment(tmp_path):
    c, path, server = setup(tmp_path)
    invite = "/api/catalog/servers/" + server + "/invites"
    assert c.post(invite).status_code == 403
    assert c.post(invite, headers={"Origin": "https://evil.example"}).status_code == 403
    result = c.post(invite, headers=ORIGIN)
    assert result.status_code == 201, result.text
    code = result.json()["data"]["enrollment_code"]
    assert len(code) == 43
    assert code not in str(c.get("/api/catalog/servers").json())
    assert code not in str(c.get("/api/catalog/servers/" + server + "/identity").json())
    with sqlite3.connect(path) as db:
        assert code not in str(db.execute("SELECT * FROM enrollment_invites").fetchall())

    key, claim = signed_claim(server, code)
    assert c.post("/api/agents/enroll", json={**claim, "signature": b64(b"bad")}).status_code == 401
    assert c.post("/api/agents/enroll", json={**claim, "code": "A" * 43}).status_code == 401
    accepted = c.post("/api/agents/enroll", json=claim)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["data"]["status"] == "paired"
    assert c.post("/api/agents/enroll", json=claim).status_code == 401
    assert c.post(invite, headers=ORIGIN).status_code == 409

    ping = "/api/agents/" + server + "/heartbeat"
    heartbeat = signed_ping(server, key)
    assert c.post(ping, json=heartbeat).status_code == 200
    assert c.post(ping, json=heartbeat).status_code == 401
    assert c.post(ping, json=signed_ping(server, key, 2, int(time.time()) - 500)).status_code == 401
    other_key = Ed25519PrivateKey.generate()
    assert c.post(ping, json=signed_ping(server, other_key, 2)).status_code == 401
    assert c.post(ping, json=signed_ping(server, key, 2)).status_code == 200
    state = c.get("/api/catalog/servers/" + server + "/identity").json()["data"]
    assert state["identity"]["last_sequence"] == 2
    assert state["identity"]["last_seen"] is not None
    assert "public_key" not in str(state)
    assert "enrollment_code" not in str(state)

    revoke = c.post("/api/catalog/servers/" + server + "/revoke", headers=ORIGIN)
    assert revoke.status_code == 200
    assert revoke.json()["data"]["status"] == "revoked"
    assert c.post(ping, json=signed_ping(server, key, 3)).status_code == 401
    replacement = c.post(invite, headers=ORIGIN)
    assert replacement.status_code == 201
    new_key, new_claim = signed_claim(server, replacement.json()["data"]["enrollment_code"])
    assert c.post("/api/agents/enroll", json=new_claim).status_code == 200
    assert c.post(ping, json=signed_ping(server, key, 4)).status_code == 401
    assert c.post(ping, json=signed_ping(server, new_key, 1)).status_code == 200

    audit = [event["action"] for event in c.get("/api/audit/events").json()["data"]]
    assert "agent.invite.created" in audit
    assert "agent.enrolled" in audit
    assert "agent.revoked" in audit


def test_invite_is_replaced_and_expires(tmp_path):
    c, path, server = setup(tmp_path)
    url = "/api/catalog/servers/" + server + "/invites"
    code1 = c.post(url, headers=ORIGIN).json()["data"]["enrollment_code"]
    code2 = c.post(url, headers=ORIGIN).json()["data"]["enrollment_code"]
    assert code1 != code2
    _, claim1 = signed_claim(server, code1)
    assert c.post("/api/agents/enroll", json=claim1).status_code == 401
    with sqlite3.connect(path) as db:
        db.execute("UPDATE enrollment_invites SET expires_at=0 WHERE server_id=?", (server,))
    _, claim2 = signed_claim(server, code2)
    assert c.post("/api/agents/enroll", json=claim2).status_code == 401


def test_owner_isolation_and_revoke_before_pairing(tmp_path):
    c, path, server = setup(tmp_path)
    registry = EnrollmentStore(path)
    from panel.registry import RegistryError
    with pytest.raises(RegistryError):
        registry.create_invite("different-owner", server)
    with pytest.raises(RegistryError):
        registry.server_identity("different-owner", server)
    with pytest.raises(RegistryError):
        registry.revoke("different-owner", server)
    code = c.post("/api/catalog/servers/" + server + "/invites",
                  headers=ORIGIN).json()["data"]["enrollment_code"]
    assert c.post("/api/catalog/servers/" + server + "/revoke", headers=ORIGIN).status_code == 200
    _, claim = signed_claim(server, code)
    assert c.post("/api/agents/enroll", json=claim).status_code == 401


def test_heartbeat_fails_if_no_signature_or_no_key(tmp_path):
    c, _, server = setup(tmp_path)
    path = "/api/agents/" + server + "/heartbeat"
    data = {"sequence": 1, "timestamp": int(time.time()), "signature": b64(b"x" * 64)}
    assert c.post(path, json=data).status_code == 401
    assert c.post(path, json={**data, "sequence": 0}).status_code == 422
    assert c.post(path, json={**data, "signature": "not base64" * 10}).status_code in (401, 422)


@pytest.mark.parametrize("url", [
    "http://host.ts.net:8443", "https://host.ts.net:443", "https://evil.example:8443",
    "https://host.ts.net:8443/secret", "https://user:pass@host.ts.net:8443",
    "https://host.ts.net:8443?q=1", "https://host.ts.net:8443#fragment",
])
def test_agent_cli_rejects_unsafe_urls(url):
    with pytest.raises(ValueError):
        checked_origin(url)


def test_agent_cli_accepts_tailscale_https():
    assert checked_origin("https://moobee-stream-vps.tail08e9d7.ts.net:8443") == (
        "https://moobee-stream-vps.tail08e9d7.ts.net:8443")
