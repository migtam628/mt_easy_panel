from fastapi.testclient import TestClient
from agent.api import DemoReader, create_app
from agent.docker import DockerReader, choose_docker_socket

TOKEN = "x" * 64


def test_agent_is_auth_protected_and_read_only():
    client = TestClient(create_app(reader=DemoReader(), token=TOKEN))
    assert client.get("/v1/overview").status_code == 401
    assert client.get("/v1/overview", headers={"Authorization": "Bearer wrong"}).status_code == 401
    headers = {"Authorization": f"Bearer {TOKEN}"}
    ov = client.get("/v1/overview", headers=headers)
    assert ov.status_code == 200
    assert ov.json()["data"]["source"] == "demo"
    assert len(client.get("/v1/containers", headers=headers).json()["data"]) == 3
    assert client.get("/v1/images", headers=headers).status_code == 200
    assert client.get("/v1/networks", headers=headers).status_code == 200
    assert client.get("/v1/volumes", headers=headers).status_code == 200
    assert client.get("/v1/containers/" + "a"*64 + "/logs", headers=headers).status_code == 200
    assert client.get("/v1/containers/bad-id/logs", headers=headers).status_code == 422
    assert client.get("/v1/containers/" + "a"*64 + "/logs?tail=1000", headers=headers).status_code == 422
    assert client.post("/v1/containers", headers=headers).status_code == 405
    assert client.delete("/v1/containers/" + "a"*64, headers=headers).status_code == 404


def test_docker_multiplexed_log_frames():
    class StubDocker(DockerReader):
        def _get(self, path, max_bytes=2_000_000):
            assert path.startswith("/containers/" + "a"*64 + "/logs?")
            a = b"hello\n"
            b = b"stderr\n"
            frames = b"\x01\x00\x00\x00" + len(a).to_bytes(4,"big") + a
            frames += b"\x02\x00\x00\x00" + len(b).to_bytes(4,"big") + b
            return frames, "text/plain"
    assert StubDocker().logs("a"*64, 80) == "hello\nstderr\n"


def test_docker_logs_reject_invalid_ids():
    reader = DockerReader("/path/that/does/not/exist")
    for name in ["/../abc", "A"*64, "c"*65, "bad"]:
        try:
            reader.logs(name, 80)
            assert False, "Expected invalid ID"
        except ValueError:
            pass


def test_docker_socket_discovery_override(monkeypatch):
    monkeypatch.setenv("DOCKER_SOCKET_PATH", "/tmp/example-docker.sock")
    assert choose_docker_socket() == "/tmp/example-docker.sock"
    assert DockerReader().socket_path == "/tmp/example-docker.sock"
    monkeypatch.setenv("DOCKER_SOCKET_PATH", "tcp://localhost:2375")
    try:
        choose_docker_socket()
        assert False, "TCP addresses must be refused"
    except ValueError:
        pass


def test_agent_health_is_not_docker_status():
    client = TestClient(create_app(reader=DemoReader(), token=TOKEN))
    assert client.get("/health").json()["service"] == "mt-panel-agent"
    assert client.get("/v1/overview").status_code == 401
