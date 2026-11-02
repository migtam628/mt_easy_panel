from fastapi.testclient import TestClient
from panel.api import Settings, create_app
from panel.auth import AuthStore

TOKEN = "t" * 64


class FakeAgent:
    def __init__(self):
        self.calls = []

    async def get(self, endpoint):
        self.calls.append(endpoint)
        if endpoint == "overview":
            return {"hostname": "test-host", "source": "test", "cpus": 2}
        if endpoint == "containers":
            return [{"id": "a" * 64, "name": "test", "state": "running"}]
        return []

    async def logs(self, container_id):
        self.calls.append("logs")
        return "safe text"


def setup(tmp_path):
    settings = Settings(str(tmp_path / "test.db"), "http://127.0.0.1:8788", TOKEN,
                        "http://127.0.0.1:8086")
    fake = FakeAgent()
    app = create_app(settings, fake)
    client = TestClient(app)
    return client, fake, settings


def sign_in(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "A totally unique passphrase 2026!"},
                    headers={"Origin": "http://127.0.0.1:8086"})
    assert r.status_code == 200, r.text


def test_requires_offline_bootstrap_and_authentication(tmp_path):
    client, agent, settings = setup(tmp_path)
    assert client.get("/api/setup").json() == {"needs_setup": True}
    assert client.get("/api/server/overview").status_code == 401
    assert client.post("/api/auth/login", json={"username":"admin", "password":"password12345"}).status_code == 503
    assert agent.calls == []
    AuthStore(settings.db_path).create_admin("admin", "A totally unique passphrase 2026!")
    assert client.get("/api/setup").json() == {"needs_setup": False}
    sign_in(client)
    assert client.get("/api/auth/me").json()["role"] == "owner"
    assert client.get("/api/server/overview").json()["data"]["hostname"] == "test-host"
    assert client.get("/api/server/containers").json()["data"][0]["name"] == "test"
    assert client.get("/api/server/images").status_code == 200
    assert client.get("/api/server/networks").status_code == 200
    assert client.get("/api/server/volumes").status_code == 200
    assert client.get("/api/server/containers/" + "a"*64 + "/logs").json()["data"] == "safe text"
    assert client.get("/api/server/containers/invalid/logs").status_code == 422
    assert client.post("/api/server/containers").status_code == 405
    assert client.delete("/api/server/containers/" + "a" * 64).status_code == 404
    assert all(call in {"overview","containers","images","networks","volumes","logs"} for call in agent.calls)
    assert client.post("/api/auth/logout", headers={"Origin":"http://127.0.0.1:8086"}).status_code == 200
    assert client.get("/api/server/overview").status_code == 401


def test_wrong_password_and_cross_origin_rejected(tmp_path):
    client, _, settings = setup(tmp_path)
    AuthStore(settings.db_path).create_admin("admin", "A totally unique passphrase 2026!")
    assert client.post("/api/auth/login", json={"username":"admin", "password":"incorrect password"}).status_code == 401
    assert client.post("/api/auth/login", json={"username":"admin", "password":"A totally unique passphrase 2026!"},
                       headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.get("/api/server/overview").status_code == 401


def test_secure_configuration_enforced(tmp_path):
    base = dict(db_path=str(tmp_path / "db"), agent_token=TOKEN)
    for bad in [
        Settings(agent_url="http://public.example.com:8788", origin="http://127.0.0.1:8086", **base),
        Settings(agent_url="http://127.0.0.1:8788", origin="http://public.example.com", **base),
        Settings(agent_url="http://127.0.0.1:8788", origin="https://panel.example.com", cookie_secure=False, **base),
        Settings(db_path=str(tmp_path / "db"), agent_token="short", agent_url="http://127.0.0.1:8788", origin="http://127.0.0.1:8086"),
    ]:
        try:
            bad.validate()
            assert False, "Expected validation failure"
        except ValueError:
            pass


def test_static_site_and_headers(tmp_path):
    client, _, _ = setup(tmp_path)
    r = client.get("/")
    assert r.status_code == 200
    assert "MT Panel" in r.text
    assert r.headers["X-Frame-Options"] == "DENY"
    assert "script-src 'self'" in r.headers["Content-Security-Policy"]
    assert client.get("/assets/app.js").status_code == 200
