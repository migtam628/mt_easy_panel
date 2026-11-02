"""No live VPS required: private-key/heartbeat loop and in-process handshake."""
from __future__ import annotations
import json
import os
import stat
import time
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent import enroll as cli
from agent import heartbeat as runner
from agent.sequence import next_sequence
from panel.api import Settings, create_app
from panel.auth import AuthStore
from panel.enrollment import EnrollmentStore

ORIGIN = "http://127.0.0.1:8086"
CONTROL = "https://node.tailnet.ts.net:8443"


def setup_control(tmp_path):
    db = str(tmp_path / "panel.db")
    app = create_app(Settings(db,"http://127.0.0.1:8788","t"*64,ORIGIN))
    client = TestClient(app)
    AuthStore(db).create_admin("admin","Long enough private test passphrase for admin")
    login = client.post("/api/auth/login",
                        json={"username":"admin",
                              "password":"Long enough private test passphrase for admin"},
                        headers={"Origin":ORIGIN})
    assert login.status_code == 200
    result = client.post("/api/catalog/servers",
                         json={"name":"Disposable agent"},
                         headers={"Origin":ORIGIN})
    assert result.status_code == 201
    return client, db, result.json()["data"]["id"]


def make_mock_transport(client):
    def request(origin, path, payload):
        assert origin == CONTROL
        assert path.startswith("/api/agents/")
        result = client.post(path,json=payload)
        result.raise_for_status()
        return result.json()["data"]
    return request


def test_end_to_end_identity_agent_and_revoke(tmp_path,monkeypatch):
    client, db, server = setup_control(tmp_path)
    invitation = client.post(
        f"/api/catalog/servers/{server}/invites",
        headers={"Origin": ORIGIN})
    assert invitation.status_code == 201
    code = invitation.json()["data"]["enrollment_code"]
    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    key = home / "private-key.pem"
    monkeypatch.setattr(cli.getpass,"getpass", lambda *_: code)
    monkeypatch.setattr(cli,"request",make_mock_transport(client))

    result = cli.enroll(CONTROL,server,key)
    assert result["status"]=="paired"
    assert key.stat().st_mode & 0o077 == 0
    assert cli.heartbeat(CONTROL,server,key)["ok"]
    previous = int((home/"private-key.pem.sequence").read_text())

    # Simulate a severe clock correction: the sequence still increases.
    from agent import sequence as seq
    monkeypatch.setattr(seq.time,"time_ns",lambda: 100)
    assert cli.heartbeat(CONTROL,server,key)["ok"]
    assert int((home/"private-key.pem.sequence").read_text())==previous+1

    status=client.get(f"/api/catalog/servers/{server}/identity").json()["data"]
    assert status["heartbeat_state"]=="recent"
    assert status["identity"]["last_sequence"]==previous+1
    assert "public_key" not in status["identity"]
    revoke=client.post(f"/api/catalog/servers/{server}/revoke",
                       headers={"Origin":ORIGIN})
    assert revoke.status_code==200
    with pytest.raises(Exception):
        cli.heartbeat(CONTROL,server,key)
    assert client.get(f"/api/catalog/servers/{server}/identity").json()["data"]["heartbeat_state"]=="revoked"


def test_config_validate_and_no_network_in_check(tmp_path,monkeypatch,capsys):
    home=tmp_path/"private"
    home.mkdir(mode=0o700)
    key=home/"id.pem"
    key.write_text("local fake key")
    key.chmod(0o600)
    config=home/"heartbeat.json"
    config.write_text(json.dumps({"control_url":CONTROL,"server_id":"a"*32,
                                  "key_file":str(key)}))
    config.chmod(0o600)
    data=runner.read_config(config)
    assert data["server_id"]=="a"*32
    assert data["key_file"]==key
    monkeypatch.setattr(runner,"heartbeat",lambda **kwargs: (_ for _ in ()).throw(AssertionError("network call")))
    monkeypatch.setattr("sys.argv",["agent.heartbeat","--check","--config",str(config)])
    runner.main()
    assert "PASS:" in capsys.readouterr().out
    config.chmod(0o644)
    with pytest.raises(ValueError,match="private"):
        runner.read_config(config)
    config.chmod(0o600)
    bad=home/"symlink.json"
    bad.symlink_to(config)
    with pytest.raises(ValueError):
        runner.read_config(bad)
    config.write_text(json.dumps({"control_url":"https://example.org:8443",
                                   "server_id":"a"*32,"key_file":str(key)}))
    with pytest.raises(ValueError):
        runner.read_config(config)


def test_sequence_ownership_mode_corruption_and_symlink(tmp_path,monkeypatch):
    key=tmp_path/"id.pem"
    key.write_text("placeholder")
    s1=next_sequence(key)
    assert s1>0
    counter=tmp_path/"id.pem.sequence"
    assert counter.stat().st_mode & 0o077 == 0
    assert next_sequence(key)>s1
    counter.write_text("not-a-number")
    with pytest.raises(ValueError,match="corrupt"):
        next_sequence(key)
    counter.unlink()
    counter.symlink_to(key)
    with pytest.raises(ValueError,match="symlink"):
        next_sequence(key)
    counter.unlink()
    counter.write_text("7")
    counter.chmod(0o644)
    with pytest.raises(ValueError,match="private"):
        next_sequence(key)


def test_systemd_user_timer_does_not_get_docker_access():
    root=Path(__file__).resolve().parent.parent
    service=(root/"deployment/systemd-user/mt-panel-heartbeat.service").read_text()
    timer=(root/"deployment/systemd-user/mt-panel-heartbeat.timer").read_text()
    assert "Type=oneshot" in service
    assert "--once" in service
    assert "--config" in service
    assert "NoNewPrivileges=true" in service
    assert "SupplementaryGroups=docker" not in service
    assert "docker" not in service.lower().replace("no docker","")
    assert "OnUnitInactiveSec=60s" in timer
    assert "WantedBy=timers.target" in timer
