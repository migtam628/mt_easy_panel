"""Ephemeral runner Docker integration: NEVER run on a production VPS.

This is the first test of the actual Docker Unix-socket adapter (as opposed
to mock HTTP). Only GitHub-hosted runners with a hard-coded approval flag,
or a manually isolated test VM using a separately reviewed harness, may
ever run Docker writes. The agent and control plane NEVER execute a shell.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from agent.api import create_app
from agent.action_replay import ActionReplay
from agent.docker import DockerReader
from agent.local_execution import ActionDenied, LocalDockerWriter
from panel.manifests import ServiceDraft
from protocol.local_action import LocalAction, sign_action

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "integration"
REGISTRY = "127.0.0.1:15000"
TOKEN = "t" * 64
EXEC_KEY = "integration-only-hmac-" + "x" * 48
APPROVAL = "YES_DISPOSABLE_GITHUB_HOSTED_RUNNER_ONLY"


def docker(*args: str, timeout: int = 90) -> str:
    cmd = ["docker", *args]
    done = subprocess.run(
        cmd, check=True, capture_output=True, text=True, timeout=timeout
    )
    return done.stdout.strip()


def _environment_allowed() -> bool:
    return (
        os.environ.get("MT_PANEL_EPHEMERAL_DOCKER_TEST") == APPROVAL
        and os.environ.get("GITHUB_ACTIONS") == "true"
        and os.environ.get("RUNNER_ENVIRONMENT") == "github-hosted"
        and os.environ.get("RUNNER_OS") == "Linux"
    )


@pytest.fixture(scope="module")
def images():
    if not _environment_allowed():
        pytest.skip("Real Docker integration requires disposable GitHub-hosted runner")
    if shutil.which("docker") is None:
        pytest.skip("Docker CLI unavailable on runner")
    # Absolutely no host data is read, and the fixture registry is bound only
    # to loopback on a disposable runner. Never touch ports 80 or 443.
    docker("info", timeout=20)
    registry_id = uuid.uuid4().hex[:12]
    registry_name = "mtpanel-ci-registry-" + registry_id
    docker("run", "-d", "--name", registry_name,
           "-p", "127.0.0.1:15000:5000", "registry:2", timeout=120)
    created_images = []
    try:
        # Wait for Docker's disposable loopback registry, no public endpoints.
        import http.client
        for _ in range(30):
            conn = http.client.HTTPConnection("127.0.0.1", 15000, timeout=1)
            try:
                conn.request("GET", "/v2/")
                if conn.getresponse().status == 200:
                    break
            except OSError:
                time.sleep(0.2)
            finally:
                conn.close()
        else:
            raise AssertionError("Ephemeral local image registry not ready")

        built = {}
        for kind in ("healthy", "unhealthy"):
            tag = f"{REGISTRY}/mtpanel-fixture-{registry_id}-{kind}:ci"
            docker("build", "--pull", "--no-cache", "-f",
                   str(FIXTURES / f"lab_{kind}.Dockerfile"),
                   "-t", tag, str(FIXTURES), timeout=180)
            docker("push", tag, timeout=120)
            # Exact digest is supplied by the registry, never guessed from a
            # mutable tag. Pull by the immutable RepoDigest before deployment.
            digests = docker("image", "inspect", tag,
                             "--format", "{{json .RepoDigests}}")
            import json
            matches = [
                x for x in json.loads(digests)
                if x.startswith(f"{REGISTRY}/mtpanel-fixture-{registry_id}-{kind}@sha256:")
            ]
            assert len(matches) == 1, "Registry did not confirm immutable digest"
            digest_ref = matches[0]
            assert re.fullmatch(r"[a-z0-9][a-z0-9._:/-]*@sha256:[0-9a-f]{64}", digest_ref)
            docker("pull", digest_ref, timeout=120)
            created_images.append(tag)
            built[kind] = digest_ref
        yield built
    finally:
        # Only the fixture registry with a random exact name is removed. Test
        # candidate containers are cleaned up by their own test fixture.
        subprocess.run(["docker", "rm", "-f", registry_name],
                       capture_output=True, timeout=20, check=False)


@pytest.fixture()
def owned_names():
    names = []
    yield names
    for name in names:
        # Cleanup is not part of agent/API functionality; it is an explicit
        # disposable-runner harness operation for OUR randomized fixtures only.
        subprocess.run(["docker", "rm", "-f", name], capture_output=True,
                       timeout=20, check=False)


def _manifest(image: str) -> ServiceDraft:
    return ServiceDraft(
        name="Disposable CI fixture", slug="ci-fixture", image=image,
        container_port=8080, cpu_limit=0.2, memory_mb=64,
    )


def _assert_isolated(name: str):
    import json
    details = json.loads(docker("inspect", name))[0]
    host = details["HostConfig"]
    assert host["NetworkMode"] == "none"
    assert host["Privileged"] is False
    assert host["ReadonlyRootfs"] is True
    assert not host["Binds"]
    assert not host["PortBindings"]
    assert host["CapDrop"] == ["ALL"]
    assert details["Config"]["User"] == "65534:65534"
    assert details["NetworkSettings"]["Ports"] in ({}, None, {"8080/tcp": None})
    assert details["Config"]["Labels"]["io.mtpanel.lab.managed"] == "v1"


def test_live_docker_health_and_failed_candidate_stops_only_self(images, owned_names):
    writer = LocalDockerWriter(DockerReader().socket_path, checks=15, poll_delay=1.0)
    draft_id = uuid.uuid4().hex
    healthy_id = uuid.uuid4().hex
    unhealthy_id = uuid.uuid4().hex
    healthy_name = "mtpanel-lab-" + healthy_id
    unhealthy_name = "mtpanel-lab-" + unhealthy_id
    owned_names.extend([healthy_name, unhealthy_name])
    response = writer.deploy(healthy_id, draft_id, _manifest(images["healthy"]))
    assert response["status"] == "HEALTHY"
    assert response["traffic_switched"] is False
    _assert_isolated(healthy_name)
    assert writer.candidate_status(healthy_id, draft_id, images["healthy"])["observation"] == "running_healthy"

    response2 = writer.deploy(unhealthy_id, draft_id, _manifest(images["unhealthy"]))
    assert response2["status"] == "ROLLED_BACK"
    assert response2["traffic_switched"] is False
    _assert_isolated(unhealthy_name)
    assert writer.candidate_status(unhealthy_id, draft_id, images["unhealthy"])["observation"] == "stopped"
    # Failed candidate must never stop or update the already healthy job.
    assert writer.candidate_status(healthy_id, draft_id, images["healthy"])["observation"] == "running_healthy"


def test_live_docker_foreign_container_refused_and_untouched(images, owned_names):
    writer = LocalDockerWriter(DockerReader().socket_path, checks=10)
    job_id, draft_id = uuid.uuid4().hex, uuid.uuid4().hex
    name = "mtpanel-lab-" + job_id
    owned_names.append(name)
    # Create a same-name foreign candidate. It has NO MT Panel labels.
    docker("create", "--name", name, "--network", "none", images["healthy"])
    with pytest.raises(ActionDenied, match="not owned"):
        writer.deploy(job_id, draft_id, _manifest(images["healthy"]))
    with pytest.raises(ActionDenied, match="not owned"):
        writer.lifecycle(job_id, draft_id, "start")
    assert docker("inspect", "-f", "{{.State.Running}}", name) == "false"


def test_real_docker_agent_signed_action_with_persisted_nonce(images, tmp_path, monkeypatch, owned_names):
    monkeypatch.setenv("AGENT_EXECUTION_LAB_ACK", "I_ACCEPT_DISPOSABLE_HOST_ONLY")
    writer = LocalDockerWriter(DockerReader().socket_path, checks=15, poll_delay=1)
    job_id, draft_id = uuid.uuid4().hex, uuid.uuid4().hex
    name = "mtpanel-lab-" + job_id
    owned_names.append(name)
    client = TestClient(create_app(
        reader=DockerReader(), token=TOKEN, writer=writer,
        enable_local_writes=True, execution_key=EXEC_KEY,
        replay=ActionReplay(str(tmp_path / "actions.sqlite")),
    ))
    action = LocalAction(
        job_id=job_id, draft_id=draft_id, operation="deploy",
        issued_at=int(time.time()), nonce=uuid.uuid4().hex,
        manifest=_manifest(images["healthy"]),
    )
    headers = {
        "Authorization": "Bearer " + TOKEN,
        "X-MTPanel-Signature": sign_action(EXEC_KEY, action),
    }
    route = "/v1/lab/actions"
    response = client.post(route, json=action.model_dump(mode="json"),
                           headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == "HEALTHY"
    assert client.post(route, json=action.model_dump(mode="json"),
                       headers=headers).status_code == 409
    # The same nonce is refused even when the agent process is recreated.
    restarted = TestClient(create_app(
        reader=DockerReader(), token=TOKEN, writer=writer,
        enable_local_writes=True, execution_key=EXEC_KEY,
        replay=ActionReplay(str(tmp_path / "actions.sqlite")),
    ))
    assert restarted.post(route, json=action.model_dump(mode="json"),
                          headers=headers).status_code == 409
    inspect = restarted.get(f"/v1/lab/candidates/{job_id}", params={
        "draft_id": draft_id, "image_digest": images["healthy"],
    }, headers={"Authorization": "Bearer " + TOKEN})
    assert inspect.status_code == 200
    assert inspect.json()["data"]["observation"] == "running_healthy"
    _assert_isolated(name)
