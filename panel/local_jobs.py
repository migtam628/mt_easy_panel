"""Durable owner-scoped SQLite lab job ledger; no direct Docker access.

The job queue is deliberately *manually advanced* (no background worker on
the production VPS). One leased job per local lab host at a time. Every
transition and request is committed alongside an audit event. A restarted
controller never autonomously replays an uncertain Docker write.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import time
import uuid

from panel.manifests import ServiceDraft
from panel.registry import Registry, RegistryError

KEY = re.compile(r"[A-Za-z0-9_-]{16,96}\Z")
HEX = re.compile(r"[0-9a-f]{32}\Z")
STATES = ("DRAFT", "QUEUED", "RUNNING", "HEALTHY", "FAILED", "ROLLED_BACK", "NEEDS_REVIEW")


class LocalJobs:
    def __init__(self, db_path: str):
        self.registry = Registry(db_path)
        with self.registry.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS local_deployment_jobs (
                    id TEXT PRIMARY KEY,
                    owner TEXT NOT NULL,
                    draft_id TEXT NOT NULL REFERENCES service_drafts(id),
                    local_server_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    manifest_json TEXT NOT NULL,
                    manifest_hash TEXT NOT NULL,
                    state TEXT NOT NULL,
                    requested_execute INTEGER NOT NULL DEFAULT 0,
                    attempt INTEGER NOT NULL DEFAULT 0,
                    lease_token TEXT,
                    lease_until INTEGER,
                    error_code TEXT,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    UNIQUE(owner, idempotency_key)
                );
                CREATE INDEX IF NOT EXISTS local_jobs_owner_idx
                    ON local_deployment_jobs(owner, created_at DESC);
                CREATE INDEX IF NOT EXISTS local_jobs_leases_idx
                    ON local_deployment_jobs(local_server_id, state, lease_until);
                CREATE TABLE IF NOT EXISTS local_deployment_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL REFERENCES local_deployment_jobs(id),
                    actor TEXT NOT NULL,
                    state TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    code TEXT NOT NULL
                );
            """)

    @staticmethod
    def _event(db, job_id: str, owner: str, state: str, code: str, now: int) -> None:
        db.execute("""INSERT INTO local_deployment_events
            (job_id,actor,state,created_at,code) VALUES (?,?,?,?,?)""",
            (job_id, owner, state, now, code))
        # Atomic with state mutation; no sensitive manifest or tokens in audit.
        Registry.audit(db, owner, "lab.job." + code, job_id)

    @staticmethod
    def _public(row) -> dict:
        return {
            "id": row["id"], "draft_id": row["draft_id"],
            "state": row["state"], "attempt": row["attempt"],
            "created_at": row["created_at"], "updated_at": row["updated_at"],
            "error_code": row["error_code"], "execution_mode": "lab_manual",
        }

    def create(self, owner: str, draft_id: str, key: str, local_server_id: str,
               *, execute: bool = False) -> dict:
        if not KEY.fullmatch(key):
            raise RegistryError("Idempotency key must be 16-96 safe characters")
        if execute and not HEX.fullmatch(local_server_id):
            raise RegistryError("Explicit local server ID must be configured", 503)
        now = int(time.time())
        with self.registry.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("""
                SELECT d.id, d.manifest_json, p.server_id
                  FROM service_drafts d
                  JOIN environments e ON e.id=d.environment_id
                  JOIN projects p ON p.id=e.project_id
                 WHERE d.id=? AND p.owner=?
            """, (draft_id, owner)).fetchone()
            if row is None:
                raise RegistryError("Draft not found", 404)
            if execute and row["server_id"] != local_server_id:
                raise RegistryError("Draft must be assigned to the explicitly configured local server", 409)
            # Dry-run mode works for an unassigned draft even when the lab
            # execution service is disabled; it can never be claimed until
            # an actual local host has been explicitly configured.
            bound_server = row["server_id"] or "0" * 32
            try:
                manifest = ServiceDraft.model_validate_json(row["manifest_json"])
            except ValueError as exc:
                raise RegistryError("Saved draft fails current strict manifest validation", 409) from exc
            manifest_json = manifest.model_dump_json()
            digest = hashlib.sha256(manifest_json.encode()).hexdigest()
            state = "QUEUED" if execute else "DRAFT"
            existing = db.execute("""
                SELECT * FROM local_deployment_jobs WHERE owner=? AND idempotency_key=?
            """, (owner, key)).fetchone()
            if existing is not None:
                if (existing["draft_id"] != draft_id
                        or existing["manifest_hash"] != digest
                        or existing["local_server_id"] != bound_server
                        or bool(existing["requested_execute"]) != bool(execute)):
                    # Never reuse an idempotency key for a different request.
                    raise RegistryError("Idempotency key already used for a different request", 409)
                return self._public(existing)
            job_id = uuid.uuid4().hex
            db.execute("""INSERT INTO local_deployment_jobs
                (id,owner,draft_id,local_server_id,idempotency_key,
                 manifest_json,manifest_hash,state,requested_execute,attempt,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,0,?,?)""",
                (job_id, owner, draft_id, bound_server, key,
                 manifest_json, digest, state, int(execute), now, now))
            self._event(db, job_id, owner, state, "requested_" + state.lower(), now)
            return self._public(db.execute(
                "SELECT * FROM local_deployment_jobs WHERE id=?", (job_id,)).fetchone())

    def list(self, owner: str, limit: int = 50) -> list[dict]:
        if not 1 <= limit <= 100:
            raise RegistryError("Limit must be 1-100")
        with self.registry.connect() as db:
            rows = db.execute("""SELECT * FROM local_deployment_jobs
                WHERE owner=? ORDER BY created_at DESC,id DESC LIMIT ?""",
                (owner, limit)).fetchall()
        return [self._public(row) for row in rows]

    def details(self, owner: str, job_id: str) -> dict:
        with self.registry.connect() as db:
            row = db.execute("SELECT * FROM local_deployment_jobs WHERE id=? AND owner=?",
                             (job_id, owner)).fetchone()
            if row is None:
                raise RegistryError("Job not found", 404)
            events = db.execute("""SELECT state,created_at,code FROM local_deployment_events
                WHERE job_id=? ORDER BY id""", (job_id,)).fetchall()
            return {**self._public(row), "events": [dict(e) for e in events]}

    def queue(self, owner: str, job_id: str, local_server_id: str) -> dict:
        """Explicitly authorize a previously drafted lab job.

        A queuing acknowledgement does not run Docker. No job can be
        queued for any server other than the configured local lab host.
        """
        now = int(time.time())
        with self.registry.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("""SELECT * FROM local_deployment_jobs
                WHERE id=? AND owner=? AND local_server_id=?""",
                (job_id, owner, local_server_id)).fetchone()
            if row is None:
                raise RegistryError("Job not found", 404)
            if row["state"] == "QUEUED":
                return self._public(row)
            if row["state"] != "DRAFT":
                raise RegistryError("Only DRAFT jobs can enter the queue", 409)
            db.execute("""UPDATE local_deployment_jobs SET state='QUEUED',
                updated_at=? WHERE id=?""", (now, job_id))
            self._event(db, job_id, owner, "QUEUED", "approved_queued", now)
            return self._public(db.execute(
                "SELECT * FROM local_deployment_jobs WHERE id=?", (job_id,)).fetchone())

    def claim(self, owner: str, job_id: str, local_server_id: str):
        now = int(time.time())
        with self.registry.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("""SELECT * FROM local_deployment_jobs
                WHERE id=? AND owner=? AND local_server_id=?""",
                (job_id, owner, local_server_id)).fetchone()
            if row is None:
                raise RegistryError("Job not found", 404)
            if row["state"] != "QUEUED":
                raise RegistryError("Only QUEUED lab jobs can be executed", 409)
            busy = db.execute("""SELECT 1 FROM local_deployment_jobs
                WHERE local_server_id=? AND state IN ('RUNNING','NEEDS_REVIEW')
                LIMIT 1""", (local_server_id,)).fetchone()
            if busy:
                # Even expired leases require manual reconciliation; never
                # replay Docker operations after uncertain partial success.
                raise RegistryError("Local host has a running or un-reconciled job", 409)
            token = secrets.token_hex(16)
            db.execute("""UPDATE local_deployment_jobs SET
                state='RUNNING',attempt=attempt+1,lease_token=?,
                lease_until=?,updated_at=? WHERE id=?""",
                (token, now + 120, now, job_id))
            self._event(db, job_id, owner, "RUNNING", "claimed", now)
            return {
                "token": token, "job_id": job_id, "draft_id": row["draft_id"],
                "manifest": ServiceDraft.model_validate_json(row["manifest_json"]),
            }

    def recovery_target(self, owner: str, job_id: str,
                        local_server_id: str) -> dict:
        """Return a scoped target without releasing a lease or inspecting Docker."""
        with self.registry.connect() as db:
            row = db.execute("""SELECT id,draft_id,state,local_server_id,lease_until,manifest_json
                FROM local_deployment_jobs WHERE id=? AND owner=?""",
                (job_id, owner)).fetchone()
        if row is None:
            raise RegistryError("Job not found", 404)
        if row["local_server_id"] != local_server_id:
            raise RegistryError("Job is not bound to the configured local lab host", 409)
        try:
            digest_image = ServiceDraft.model_validate_json(row["manifest_json"]).image
        except ValueError as exc:
            raise RegistryError("Saved lab manifest is invalid", 409) from exc
        return {"job_id": row["id"], "draft_id": row["draft_id"],
                "image_digest": digest_image, "state": row["state"],
                "lease_expired": (row["state"] == "RUNNING"
                                  and row["lease_until"] is not None
                                  and row["lease_until"] < int(time.time()))}

    def record_recovery(self, owner: str, job_id: str, local_server_id: str,
                        observation: str) -> dict:
        """Persist one explicit observation but NEVER unlock or re-run a host.

        A missing/stopped candidate, including its labels, does not prove
        an older write never happened. Review remains operator-blocking.
        """
        valid = {"absent", "stopped", "running_healthy", "running_unhealthy",
                 "running_starting", "running_unknown"}
        if observation not in valid:
            raise RegistryError("Unsupported reconciliation observation")
        now = int(time.time())
        with self.registry.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("""SELECT * FROM local_deployment_jobs
                WHERE id=? AND owner=? AND local_server_id=?""",
                (job_id, owner, local_server_id)).fetchone()
            if row is None:
                raise RegistryError("Job not found", 404)
            if row["state"] not in ("RUNNING", "NEEDS_REVIEW"):
                raise RegistryError("Only running/unresolved lab jobs can be reconciled", 409)
            if (row["state"] == "RUNNING"
                    and (row["lease_until"] is None or row["lease_until"] >= now)):
                raise RegistryError("Job lease still active; concurrent reconciliation denied", 409)
            db.execute("""UPDATE local_deployment_jobs SET state='NEEDS_REVIEW',
                lease_token=NULL,lease_until=NULL,error_code='operator_review_required',
                updated_at=? WHERE id=?""", (now, job_id))
            self._event(db, job_id, owner, "NEEDS_REVIEW",
                        "reconcile_" + observation, now)
            return self._public(db.execute(
                "SELECT * FROM local_deployment_jobs WHERE id=?", (job_id,)).fetchone())

    def finish(self, owner: str, job_id: str, token: str, state: str,
               code: str = "completed") -> dict:
        if state not in ("HEALTHY", "ROLLED_BACK", "FAILED", "NEEDS_REVIEW"):
            raise RegistryError("Invalid terminal job state")
        if not re.fullmatch(r"[a-z_]{1,48}", code):
            code = "invalid_result"
        now = int(time.time())
        with self.registry.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("""SELECT * FROM local_deployment_jobs
                WHERE id=? AND owner=?""", (job_id, owner)).fetchone()
            if row is None:
                raise RegistryError("Job not found", 404)
            if row["state"] != "RUNNING" or row["lease_token"] != token:
                raise RegistryError("Job lease mismatch or already completed", 409)
            db.execute("""UPDATE local_deployment_jobs SET state=?,
                lease_token=NULL,lease_until=NULL,error_code=?,updated_at=?
                WHERE id=?""", (state, None if state == "HEALTHY" else code, now, job_id))
            self._event(db, job_id, owner, state, code, now)
            return self._public(db.execute(
                "SELECT * FROM local_deployment_jobs WHERE id=?", (job_id,)).fetchone())
