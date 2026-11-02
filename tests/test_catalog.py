"""Persistent, owner-scoped configuration records. No Docker or network side effects."""
import pytest
from fastapi.testclient import TestClient

from panel.api import Settings, create_app
from panel.auth import AuthStore
from panel.registry import Registry, RegistryError

ORIGIN = {"Origin": "http://127.0.0.1:8086"}
PASSWORD = "A totally unique passphrase 2026!"


def client_for(tmp_path):
    settings = Settings(str(tmp_path / "panel.db"), "http://127.0.0.1:8788",
                        "t" * 64, "http://127.0.0.1:8086")
    app = create_app(settings)
    client = TestClient(app)
    AuthStore(settings.db_path).create_admin("admin", PASSWORD)
    return client, settings


def login(client):
    result = client.post("/api/auth/login",
        json={"username": "admin", "password": PASSWORD}, headers=ORIGIN)
    assert result.status_code == 200, result.text


def test_requires_authentication_and_origin(tmp_path):
    c, _ = client_for(tmp_path)
    assert c.get("/api/catalog/servers").status_code == 401
    assert c.post("/api/catalog/servers", json={"name": "Lab"}).status_code == 401
    login(c)
    assert c.post("/api/catalog/servers", json={"name":"Lab"}).status_code == 403
    assert c.post("/api/catalog/servers", json={"name":"Lab"},
                  headers={"Origin": "https://invalid.example"}).status_code == 403
    assert c.get("/api/catalog/servers").json() == {"data": []}


def test_registry_persists_and_enforces_integrity(tmp_path):
    c, settings = client_for(tmp_path)
    login(c)
    server = c.post("/api/catalog/servers", json={"name":"Test VPS", "notes":"Private only"},
                    headers=ORIGIN)
    assert server.status_code == 201, server.text
    s = server.json()["data"]
    assert s["status"] == "unpaired"
    assert "token" not in s and "address" not in s
    assert c.post("/api/catalog/servers", json={"name":"Test VPS"}, headers=ORIGIN).status_code == 409
    assert c.post("/api/catalog/projects", json={
        "name":"App", "slug":"app-one", "server_id":"missing"}, headers=ORIGIN).status_code == 404
    project = c.post("/api/catalog/projects",
        json={"name":"App", "slug":"app-one", "server_id":s["id"]}, headers=ORIGIN)
    assert project.status_code == 201, project.text
    p = project.json()["data"]
    assert c.post("/api/catalog/projects",
        json={"name":"Duplicate","slug":"app-one"},headers=ORIGIN).status_code == 409
    assert c.post("/api/catalog/projects",
        json={"name":"Bad slug","slug":"../escape"},headers=ORIGIN).status_code == 422
    env = c.post(f'/api/catalog/projects/{p["id"]}/environments',
        json={"name":"Staging","slug":"staging"},headers=ORIGIN)
    assert env.status_code == 201,env.text
    assert c.post(f'/api/catalog/projects/{p["id"]}/environments',
        json={"name":"Staging","slug":"staging"},headers=ORIGIN).status_code == 409
    assert c.get("/api/catalog/projects").json()["data"][0]["environment_count"] == 1
    assert c.get("/api/catalog/projects/missing/environments").status_code == 404
    after = Registry(settings.db_path)
    assert len(after.servers("admin")) == 1
    assert len(after.projects("admin")) == 1
    assert after.servers("other-owner") == []
    assert after.projects("other-owner") == []
    with pytest.raises(RegistryError):
        after.environments("other-owner", p["id"])
    events = c.get("/api/audit/events").json()["data"]
    assert events[0]["action"] == "catalog.environment.created"
    assert events[1]["action"] == "catalog.project.created"
    assert events[2]["action"] == "catalog.server.created"


def test_registry_never_creates_docker_mutations(tmp_path):
    c, _ = client_for(tmp_path)
    login(c)
    assert c.post("/api/server/containers",json={},headers=ORIGIN).status_code == 405
    assert c.post("/api/server/restart",json={},headers=ORIGIN).status_code == 404
