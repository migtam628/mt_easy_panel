"""Phase A: dry-run SQLite jobs, authorization and failure safety."""
import sqlite3
import pytest
from fastapi.testclient import TestClient
from panel.api import Settings, create_app
from panel.auth import AuthStore
from panel.local_jobs import LocalJobs
from panel.manifests import ServiceDraft
from panel.registry import Registry, RegistryError

OWNER="owner"
PASSWORD="Lab test integration password 2026!"
ORIGIN={"Origin":"http://127.0.0.1:8086"}
IMAGE="example.test/worker@sha256:" + "b"*64
KEY="dedicated-local-test-key-"+"x"*40

def catalog(db):
    AuthStore(db).create_admin(OWNER,PASSWORD)
    r=Registry(db)
    server=r.add_server(OWNER,"Disposable Linux test")["id"]
    project=r.add_project(OWNER,"Lab project","lab-project",server)["id"]
    env=r.add_environment(OWNER,project,"Test environment","test-environment")["id"]
    draft=r.add_draft(OWNER,env,ServiceDraft(name="Safe candidate",slug="safe-candidate",
                       image=IMAGE,container_port=8080))["id"]
    return server,draft

def test_durable_idempotency_and_draft_queue_run_transitions(tmp_path):
    db=str(tmp_path/"jobs.db")
    server,draft=catalog(db)
    store=LocalJobs(db)
    key="client_request_key_123456"
    pending=store.create(OWNER,draft,key,"",execute=False)
    assert pending["state"]=="DRAFT"
    assert store.create(OWNER,draft,key,"",execute=False)["id"]==pending["id"]
    with pytest.raises(RegistryError):
        store.claim(OWNER,pending["id"],server)
    queued=store.queue(OWNER,pending["id"],server)
    assert queued["state"]=="QUEUED"
    assert store.queue(OWNER,pending["id"],server)["state"]=="QUEUED"
    assert store.create(OWNER,draft,key,"",execute=False)["id"]==pending["id"]
    claimed=store.claim(OWNER,pending["id"],server)
    assert claimed["manifest"].image==IMAGE
    with pytest.raises(RegistryError):
        store.claim(OWNER,pending["id"],server)
    with pytest.raises(RegistryError):
        store.finish(OWNER,pending["id"],"bad","HEALTHY")
    final=store.finish(OWNER,pending["id"],claimed["token"],"HEALTHY","healthy")
    assert final["state"]=="HEALTHY" and final["attempt"]==1
    assert [e["state"] for e in store.details(OWNER,pending["id"])["events"]] == [
        "DRAFT","QUEUED","RUNNING","HEALTHY"]
    with pytest.raises(RegistryError):
        store.finish(OWNER,pending["id"],claimed["token"],"HEALTHY")
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM audit_events WHERE action LIKE 'lab.job.%'").fetchone()[0]==4

def test_ambiguous_result_keeps_host_locked_and_owner_isolated(tmp_path):
    db=str(tmp_path/"jobs.db")
    server,draft=catalog(db)
    store=LocalJobs(db)
    one=store.create(OWNER,draft,"one_key_1234567890",server,execute=True)
    two=store.create(OWNER,draft,"two_key_1234567890",server,execute=True)
    lease=store.claim(OWNER,one["id"],server)
    store.finish(OWNER,one["id"],lease["token"],"NEEDS_REVIEW","agent_unconfirmed")
    with pytest.raises(RegistryError,match="un-reconciled"):
        store.claim(OWNER,two["id"],server)
    assert store.list("another-owner")==[]
    with pytest.raises(RegistryError):
        store.details("another-owner",one["id"])

class FakeAgent:
    def __init__(self, fail=False):
        self.calls=[]
        self.fail=fail
    async def lab_action(self,operation,job_id,draft_id,manifest):
        self.calls.append((operation,job_id,draft_id,manifest.image))
        if self.fail: raise RuntimeError("simulated lost response")
        return {"status":"HEALTHY","traffic_switched":False}

def login(c):
    r=c.post("/api/auth/login",json={"username":OWNER,"password":PASSWORD},headers=ORIGIN)
    assert r.status_code==200,r.text

def test_dryrun_default_refuses_agent_calls(tmp_path):
    db=str(tmp_path/"api.db")
    agent=FakeAgent()
    settings=Settings(db,"http://127.0.0.1:8788","t"*64,"http://127.0.0.1:8086")
    c=TestClient(create_app(settings,agent))
    server,draft=catalog(db)
    url=f"/api/deployments/drafts/{draft}/jobs"
    assert c.post(url,json={"idempotency_key":"hello_test_12345678"}).status_code==401
    login(c)
    assert c.post(url,json={"idempotency_key":"hello_test_12345678"}).status_code==403
    created=c.post(url,json={"idempotency_key":"hello_test_12345678"},headers=ORIGIN)
    assert created.status_code==201,created.text
    job=created.json()["data"]
    assert job["state"]=="DRAFT"
    assert c.post(f"/api/deployments/jobs/{job['id']}/queue",headers=ORIGIN).status_code==403
    assert c.post(f"/api/deployments/jobs/{job['id']}/run",headers=ORIGIN).status_code==403
    assert c.get("/api/deployments/jobs").json()["data"][0]["id"]==job["id"]
    assert c.post(url,json={"idempotency_key":"execute_test_12345678",
                   "execute":True,"confirmation":"DEPLOY_TO_DISPOSABLE_HOST"},
                   headers=ORIGIN).status_code==403
    assert agent.calls==[]

@pytest.mark.parametrize("fails,expected",[(False,"HEALTHY"),(True,"NEEDS_REVIEW")])
def test_explicit_lab_execution_never_silently_retries(tmp_path,monkeypatch,fails,expected):
    monkeypatch.setenv("PANEL_EXECUTION_LAB_ACK","I_ACCEPT_DISPOSABLE_HOST_ONLY")
    db=str(tmp_path/"api.db")
    server,draft=catalog(db)
    agent=FakeAgent(fail=fails)
    settings=Settings(db,"http://127.0.0.1:8788","t"*64,
                      "http://127.0.0.1:8086",False,server,True,KEY)
    c=TestClient(create_app(settings,agent))
    login(c)
    url=f"/api/deployments/drafts/{draft}/jobs"
    data={"idempotency_key":"manual_queue_1234567890"}
    job=c.post(url,json=data,headers=ORIGIN)
    assert job.status_code==201,job.text
    jid=job.json()["data"]["id"]
    queue=f"/api/deployments/jobs/{jid}/queue"
    run=f"/api/deployments/jobs/{jid}/run"
    assert c.post(queue,headers=ORIGIN).status_code==403
    approval={**ORIGIN,"X-MTPanel-Approval":"DEPLOY_TO_DISPOSABLE_HOST"}
    assert c.post(queue,headers=approval).json()["data"]["state"]=="QUEUED"
    assert c.post(run,headers=ORIGIN).status_code==403
    result=c.post(run,headers=approval)
    assert result.status_code==200,result.text
    assert result.json()["data"]["state"]==expected
    assert len(agent.calls)==1
    assert c.post(run,headers=approval).status_code==409
    assert len(agent.calls)==1
