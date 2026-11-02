"""Non-executing Compose policy tests: explicitly reject dangerous Docker options."""
import pytest
from fastapi.testclient import TestClient
from panel.api import Settings, create_app
from panel.auth import AuthStore
from panel.compose_policy import validate_compose, ComposePolicyError

IMAGE = "ghcr.io/example/app@sha256:" + "a"*64
GOOD = f"""
services:
  web:
    image: {IMAGE}
    read_only: true
    expose:
      - 8080
"""


def test_restrictive_compose_subset():
    parsed = validate_compose(GOOD)
    assert parsed["valid"] is True
    assert parsed["deployment_enabled"] is False
    assert parsed["services"][0]["internal_ports"] == [8080]
    risky = [
        GOOD.replace("    expose:", "    privileged: true\n    expose:"),
        GOOD.replace("    expose:", "    network_mode: host\n    expose:"),
        GOOD.replace("    expose:", "    volumes:\n      - /var/run/docker.sock:/var/run/docker.sock\n    expose:"),
        GOOD.replace("    expose:", "    ports:\n      - '80:8080'\n    expose:"),
        GOOD.replace("    expose:", "    build: .\n    expose:"),
        GOOD.replace("    expose:", "    environment:\n      SECRET: unsafe\n    expose:"),
        GOOD.replace("    read_only: true", "    read_only: false"),
        GOOD.replace(IMAGE,"nginx:latest"),
        GOOD.replace("      - 8080","      - 0"),
        GOOD.replace("      - 8080","      - 8080\n      - 8080"),
        "services:\n  web: &a\n    image: " + IMAGE + "\n    read_only: true\n    expose: [80]\n  other: *a",
        "services:\n  web: { image: ${IMAGE}, read_only: true, expose: [80] }",
        "networks: {}",
    ]
    for bad in risky:
        with pytest.raises(ComposePolicyError):
            validate_compose(bad)


def test_authenticated_compose_preview_is_noop(tmp_path):
    db=str(tmp_path/"panel.db")
    app=create_app(Settings(db,"http://127.0.0.1:8788","z"*64,
                            "http://127.0.0.1:8086"))
    c=TestClient(app)
    endpoint="/api/validate/compose"
    assert c.post(endpoint,json={"source":GOOD}).status_code == 401
    AuthStore(db).create_admin("admin","Long private testing password 123456")
    c.post("/api/auth/login",json={
        "username":"admin","password":"Long private testing password 123456"},
        headers={"Origin":"http://127.0.0.1:8086"})
    assert c.post(endpoint,json={"source":GOOD}).status_code == 403
    response=c.post(endpoint,json={"source":GOOD},
        headers={"Origin":"http://127.0.0.1:8086"})
    assert response.status_code == 200,response.text
    assert response.json()["data"]["mode"]=="analysis-only"
    assert c.post(endpoint,json={"source":GOOD+"\nprivileged: true"},
        headers={"Origin":"http://127.0.0.1:8086"}).status_code == 422
