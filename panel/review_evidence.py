"""Owner-scoped, append-only review evidence for unresolved local lab jobs.

Records are *operator-supplied references*, not trusted host attestations.
Review never releases a host lock, starts containers, or changes job state.
A SHA-256 packet fingerprint binds a submission to the exact observed job
state, immutable manifest hash, and already-recorded transition history.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from typing import Literal

from panel.registry import Registry, RegistryError

SHA256 = re.compile(r"[0-9a-f]{64}\Z")
REVIEW_CODES = (
    "candidate_inspected",
    "agent_unreachable",
    "ownership_mismatch",
    "manual_investigation",
)
MAX_EVENTS = 10000


class JobReviewEvidence:
    def __init__(self, db_path: str):
        self.registry = Registry(db_path)
        with self.registry.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS local_job_review_evidence (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL REFERENCES local_deployment_jobs(id),
                    owner TEXT NOT NULL,
                    packet_digest TEXT NOT NULL,
                    reason_code TEXT NOT NULL,
                    evidence_ref TEXT NOT NULL,
                    recorded_at INTEGER NOT NULL,
                    UNIQUE(job_id, owner, packet_digest, reason_code, evidence_ref)
                );
                CREATE INDEX IF NOT EXISTS local_review_owner_job_idx
                    ON local_job_review_evidence(owner, job_id, recorded_at);
            """)

    @staticmethod
    def _snapshot(db, owner: str, job_id: str) -> dict:
        row = db.execute("""
            SELECT id, owner, draft_id, local_server_id, manifest_hash,
                   state, attempt, lease_until, created_at, updated_at
              FROM local_deployment_jobs
             WHERE id=? AND owner=?
        """, (job_id, owner)).fetchone()
        if row is None:
            raise RegistryError("Job not found", 404)
        events = db.execute("""
            SELECT id, state, code, actor, created_at
              FROM local_deployment_events
             WHERE job_id=? ORDER BY id LIMIT ?
        """, (job_id, MAX_EVENTS + 1)).fetchall()
        if len(events) > MAX_EVENTS:
            raise RegistryError("Review packet exceeds event safety limit", 409)
        payload = {
            "job_id": row["id"], "draft_id": row["draft_id"],
            "server_id": row["local_server_id"],
            "manifest_sha256": row["manifest_hash"],
            "state": row["state"], "attempt": row["attempt"],
            "lease_until": row["lease_until"],
            "created_at": row["created_at"], "updated_at": row["updated_at"],
            "events": [dict(event) for event in events],
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return {**payload, "packet_digest": hashlib.sha256(encoded).hexdigest()}

    def packet(self, owner: str, job_id: str) -> dict:
        with self.registry.connect() as db:
            payload = self._snapshot(db, owner, job_id)
            rows = db.execute("""
                SELECT reason_code, evidence_ref, packet_digest, recorded_at
                  FROM local_job_review_evidence
                 WHERE owner=? AND job_id=? ORDER BY id DESC LIMIT 50
            """, (owner, job_id)).fetchall()
        # The packet fingerprint excludes notes, preventing notes themselves
        # from invalidating subsequent review references for the same state.
        # It includes job transition events, so any state change invalidates
        # a stale review attempt.
        return {
            **payload,
            "review_eligible": payload["state"] == "NEEDS_REVIEW",
            "evidence": [dict(row) for row in rows],
            "evidence_trusted": False,
            "host_lock_released": False,
            "safe_to_retry": False,
            "deployment_execution_authorized": False,
            "review_codes": list(REVIEW_CODES),
            "missing_safety_gates": [
                "independent_agent_attestation",
                "manual_host_clearance_not_implemented",
                "production_deployment_not_authorized",
            ],
        }

    def record(self, owner: str, job_id: str, packet_digest: str,
               reason_code: str, evidence_ref: str) -> dict:
        if (not SHA256.fullmatch(packet_digest)
                or not SHA256.fullmatch(evidence_ref)
                or reason_code not in REVIEW_CODES):
            raise RegistryError("Invalid review fingerprint or reason")
        now = int(time.time())
        with self.registry.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            snapshot = self._snapshot(db, owner, job_id)
            if snapshot["state"] != "NEEDS_REVIEW":
                raise RegistryError("Review evidence requires a blocked NEEDS_REVIEW job", 409)
            if snapshot["packet_digest"] != packet_digest:
                raise RegistryError("Review packet is stale; inspect the job again", 409)
            existing = db.execute("""
                SELECT id,recorded_at FROM local_job_review_evidence
                 WHERE owner=? AND job_id=? AND packet_digest=?
                   AND reason_code=? AND evidence_ref=?
            """, (owner, job_id, packet_digest, reason_code, evidence_ref)).fetchone()
            if existing:
                created, duplicate = existing["recorded_at"], True
            else:
                db.execute("""
                    INSERT INTO local_job_review_evidence
                    (job_id,owner,packet_digest,reason_code,evidence_ref,recorded_at)
                    VALUES (?,?,?,?,?,?)
                """, (job_id, owner, packet_digest, reason_code, evidence_ref, now))
                Registry.audit(db, owner, "lab.job.review_evidence_recorded", job_id)
                created, duplicate = now, False
        return {
            "job_id": job_id, "state": "NEEDS_REVIEW",
            "reason_code": reason_code, "evidence_ref": evidence_ref,
            "recorded_at": created, "duplicate": duplicate,
            "trusted_attestation": False, "host_lock_released": False,
            "safe_to_retry": False,
        }
