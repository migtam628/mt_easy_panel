"""Phase A isolated local-agent write path: tests use only fake Docker engines."""
import sqlite3
import time

import pytest
from fastapi.testclient import TestClient

from agent.api import create_app, DemoReader
from agent.local_execution import ActionDenied, LocalDockerWriter
from agent.docker import DockerError
from agent.action_replay import ActionReplay
from panel.manifests import ServiceDraft
from protocol.local_action import LocalAction, sign_action

TOKEN = "z" * 64
KEY = "dedicated-lab-signing-key-" + "x" * 40
JID = "a" * 32
DID = "b" * 32
IMAGE = "example.test/app@sha256:" + "1" * 64
MANIFEST = ServiceDraft(name="Lab test", slug="lab-test",
                        image=IMAGE, container_port=8080)


class FakeWriter:
    def __init__(self):
        self.calls = []
    def deploy(self, job_id, draft_id, manifest):
        self.calls.append(("deploy",job_id,draft_id,manifest.image))
        return {"status":"HEALTHY", "traffic_switched":False}
    def lifecycle(self, job_id, draft_id, operation):
        self.calls.append((operation,job_id,draft_id))
        return {"status":"lifecycle", "operation":operation}


def test_lab_action_fail_closed_default(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENT_LOCAL_EXECUTION_ENABLED", raising=False)
    c = TestClient(create_app(reader=DemoReader(), token=TOKEN))
    action = LocalAction(job_id=JID,draft_id=DID,operation="deploy",
                         issued_at=int(time.time()), nonce="c"*32,
                         manifest=MANIFEST)
    headers = {"Authorization": "Bearer " + TOKEN}
    assert c.post("/v1/lab/actions", json=action.model_dump(mode="json"),
                  headers=headers).status_code == 403
    assert c.post("/v1/lab/actions", json=action.model_dump(mode="json")).status_code == 401
    assert c.get("/v1/overview", headers=headers).status_code == 200
    assert c.post("/v1/containers", headers=headers).status_code == 405


def test_agent_signed_actions_and_sqlite_nonce_survive_restart(tmp_path,monkeypatch):
    monkeypatch.setenv("AGENT_EXECUTION_LAB_ACK","I_ACCEPT_DISPOSABLE_HOST_ONLY")
    replay_path = str(tmp_path / "actions.db")
    writer = FakeWriter()
    c = TestClient(create_app(reader=DemoReader(), token=TOKEN, writer=writer,
                  enable_local_writes=True, execution_key=KEY,
                  replay=ActionReplay(replay_path)))
    action = LocalAction(job_id=JID,draft_id=DID,operation="deploy",
                        issued_at=int(time.time()), nonce="c"*32,
                        manifest=MANIFEST)
    payload = action.model_dump(mode="json")
    headers = {"Authorization":"Bearer "+TOKEN,
               "X-MTPanel-Signature":sign_action(KEY,action)}
    assert c.post("/v1/lab/actions",json=payload,headers={
        **headers, "X-MTPanel-Signature":"0"*64}).status_code == 401
    assert c.post("/v1/lab/actions",json={**payload,"operation":"restart"},
                  headers=headers).status_code == 422
    assert c.post("/v1/lab/actions",json=payload,headers=headers).status_code == 200
    assert len(writer.calls) == 1
    assert c.post("/v1/lab/actions",json=payload,headers=headers).status_code == 409
    # A new application instance must still reject the same signed action.
    other = TestClient(create_app(reader=DemoReader(),token=TOKEN,writer=writer,
                       enable_local_writes=True,execution_key=KEY,
                       replay=ActionReplay(replay_path)))
    assert other.post("/v1/lab/actions",json=payload,headers=headers).status_code == 409
    assert len(writer.calls) == 1
    with sqlite3.connect(replay_path) as db:
        assert db.execute("SELECT result FROM local_action_attempts").fetchone()[0] == "healthy"


def test_agent_rejects_expired_signature_and_wrong_key(tmp_path,monkeypatch):
    monkeypatch.setenv("AGENT_EXECUTION_LAB_ACK","I_ACCEPT_DISPOSABLE_HOST_ONLY")
    writer = FakeWriter()
    c = TestClient(create_app(reader=DemoReader(),token=TOKEN,writer=writer,
                   enable_local_writes=True,execution_key=KEY,
                   replay=ActionReplay(str(tmp_path/"nonce.db"))))
    old = LocalAction(job_id=JID,draft_id=DID,operation="deploy",
                      issued_at=int(time.time())-100,nonce="d"*32,
                      manifest=MANIFEST)
    assert c.post("/v1/lab/actions",json=old.model_dump(mode="json"),
                  headers={"Authorization":"Bearer "+TOKEN,
                           "X-MTPanel-Signature":sign_action(KEY,old)}).status_code == 401
    fresh = old.model_copy(update={"issued_at":int(time.time()),"nonce":"e"*32})
    assert c.post("/v1/lab/actions",json=fresh.model_dump(mode="json"),
                  headers={"Authorization":"Bearer "+TOKEN,
                           "X-MTPanel-Signature":sign_action("wrong-"+"y"*40,fresh)}).status_code == 401
    assert writer.calls == []


class DockerFixture(LocalDockerWriter):
    def __init__(self, *, unhealthy=False):
        super().__init__("/fake/socket",checks=2,poll_delay=0)
        self.requests=[]
        self.container=None
        self.unhealthy=unhealthy

    def _call(self, method,path,body=None,*,missing=False):
        self.requests.append((method,path,body))
        if path.startswith("/images/"):
            return {"Config":{"Healthcheck":{"Test":["CMD","true"]}}}
        if path.startswith("/containers/create?"):
            assert method == "POST"
            assert body["HostConfig"]["NetworkMode"] == "none"
            assert body["HostConfig"]["ReadonlyRootfs"] is True
            assert body["HostConfig"]["Privileged"] is False
            assert body["HostConfig"]["PortBindings"] == {}
            assert body["HostConfig"]["Binds"] == []
            assert body["HostConfig"]["CapDrop"] == ["ALL"]
            assert body["User"] == "65534:65534"
            self.container = {
                "Name":"/mtpanel-lab-"+JID,
                "Config":{"Labels":body["Labels"],"Image":body["Image"]},
                "State":{"Running":False, "Health":{"Status":"starting"}}
            }
            return {"Id":"1"*64}
        if path.endswith("/json"):
            return self.container
        if path.endswith("/start"):
            self.container["State"]={"Running":True,"Health":{
                "Status":"unhealthy" if self.unhealthy else "healthy"}}
            return {}
        if path.endswith("/stop"):
            self.container["State"]["Running"]=False
            return {}
        raise AssertionError("Unexpected Docker operation "+path)


def test_lab_writer_health_gate_and_no_host_traffic():
    docker = DockerFixture()
    result = docker.deploy(JID,DID,MANIFEST)
    assert result == {"status":"HEALTHY","container":"mtpanel-lab-"+JID,
                      "traffic_switched":False}
    assert docker.container["Config"]["Labels"]["io.mtpanel.lab.draft"] == DID
    assert all(not path.endswith("/stop") for _,path,_ in docker.requests)
    assert all("80:80" not in path and "443" not in path for _,path,_ in docker.requests)
    assert docker.deploy(JID,DID,MANIFEST)["status"] == "HEALTHY"
    assert sum(x[1].startswith("/containers/create?") for x in docker.requests) == 1


def test_failed_health_check_stops_only_matching_candidate():
    docker = DockerFixture(unhealthy=True)
    result = docker.deploy(JID,DID,MANIFEST)
    assert result["status"] == "ROLLED_BACK"
    assert result["traffic_switched"] is False
    assert docker.container["State"]["Running"] is False
    assert sum(x[1].endswith("/stop") for x in docker.requests) == 1
    docker.container["Config"]["Labels"]["io.mtpanel.lab.job"] = "f"*32
    with pytest.raises(ActionDenied):
        docker.lifecycle(JID,DID,"restart")
    assert sum(x[1].endswith("/restart") for x in docker.requests) == 0
    with pytest.raises(ActionDenied):
        docker.lifecycle(JID,DID,"remove")


def test_existing_unmanaged_container_cannot_be_adopted():
    docker = DockerFixture()
    docker.container = {"Name":"/mtpanel-lab-"+JID,
                        "Config":{"Labels":{"foreign":"true"},"Image":IMAGE},
                        "State":{"Running":True}}
    with pytest.raises(ActionDenied):
        docker.create_candidate(JID,DID,MANIFEST)
    assert not any(x[1].startswith("/containers/create?") for x in docker.requests)


def test_unconfirmed_stop_never_claims_rollback():
    class UnconfirmedStopFixture(DockerFixture):
        def _call(self, method, path, body=None, *, missing=False):
            if method == "POST" and path.endswith("/stop"):
                self.requests.append((method, path, body))
                # Docker acknowledges stop, but inspect still says running.
                return {}
            return super()._call(method, path, body, missing=missing)

    docker = UnconfirmedStopFixture(unhealthy=True)
    with pytest.raises(DockerError, match="unconfirmed"):
        docker.deploy(JID, DID, MANIFEST)
    assert docker.container["State"]["Running"] is True
    assert any(path.endswith("/stop") for _, path, _ in docker.requests)


def test_missing_candidate_after_stop_never_claims_rollback():
    class MissingAfterStopFixture(DockerFixture):
        def _call(self, method, path, body=None, *, missing=False):
            if method == "POST" and path.endswith("/stop"):
                self.requests.append((method, path, body))
                self.container = None
                return {}
            return super()._call(method, path, body, missing=missing)

    docker = MissingAfterStopFixture(unhealthy=True)
    with pytest.raises(DockerError, match="could not be verified"):
        docker.deploy(JID, DID, MANIFEST)
