"""Draft deployment API validates and stores safe *non-executable* manifests."""
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from panel.api import Settings, create_app
from panel.auth import AuthStore
from panel.manifests import ServiceDraft
from panel.registry import Registry

ORIGIN = {"Origin":"http://127.0.0.1:8086"}
PASSWORD = "Unique test password that is long enough 2026"
IMAGE = "docker.io/library/nginx@sha256:" + "a"*64


def test_manifest_policy():
    safe = {"name":"Example app","slug":"example-app","image":IMAGE,
            "container_port":8080}
    data = ServiceDraft.model_validate(safe)
    assert data.read_only_rootfs
    for bad in [
        {**safe,"image":"nginx:latest"},
        {**safe,"privileged":True},
        {**safe,"network_mode":"host"},
        {**safe,"volumes":["/var/run/docker.sock:/var/run/docker.sock"]},
        {**safe,"published_port":80},
        {**safe,"environment":{"SECRET":"not safe"}},
        {**safe,"read_only_rootfs":False},
        {**safe,"memory_mb":20},
        {**safe,"cpu_limit":100.0},
        {**safe,"container_port":0},
        {**safe,"slug":"../bad"},
    ]:
        with pytest.raises(ValidationError):
            ServiceDraft.model_validate(bad)


def test_draft_requires_environment_ownership_and_origin(tmp_path):
    db = str(tmp_path / "app.db")
    settings = Settings(db, "http://127.0.0.1:8788",
                        "x"*64,"http://127.0.0.1:8086")
    c = TestClient(create_app(settings))
    body={"name":"Test app","slug":"test-app","image":IMAGE,"container_port":8080}
    path="/api/catalog/environments/missing/drafts"
    assert c.get(path).status_code == 401
    assert c.post(path,json=body).status_code == 401
    AuthStore(db).create_admin("admin",PASSWORD)
    assert c.post("/api/auth/login",
            json={"username":"admin","password":PASSWORD},headers=ORIGIN).status_code == 200
    assert c.post(path,json=body,headers=ORIGIN).status_code == 404
    reg=Registry(db)
    p=reg.add_project("admin","Test project","test-project")
    e=reg.add_environment("admin",p["id"],"Development","development")
    path=f'/api/catalog/environments/{e["id"]}/drafts'
    assert c.post(path,json=body).status_code == 403
    assert c.post(path,json={**body,"privileged":True},headers=ORIGIN).status_code == 422
    result=c.post(path,json=body,headers=ORIGIN)
    assert result.status_code == 201,result.text
    assert result.json()["data"]["status"]=="draft"
    assert c.post(path,json=body,headers=ORIGIN).status_code == 409
    assert c.get(path).json()["data"][0]["manifest"]["image"]==IMAGE
    assert Registry(db).drafts("admin",e["id"])[0]["status"]=="draft"
    assert Registry(db).drafts("admin",e["id"])==reg.drafts("admin",e["id"])
    assert c.get("/api/audit/events").json()["data"][0]["action"]=="catalog.service_draft.created"
