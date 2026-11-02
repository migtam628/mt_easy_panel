"""Persistent fail-closed anti-replay ledger for local lab write actions.

A signature is not sufficient on its own: each nonce is consumed durably
before any Docker write. Agent restarts cannot repeat an uncertain action.
This DB belongs only to the Docker agent OS account, never the web process.
"""
from __future__ import annotations

from pathlib import Path
import sqlite3
import time


class ActionReplay:
    def __init__(self, path: str):
        self.path = path
        if not Path(path).is_absolute():
            raise ValueError("Lab replay SQLite path must be absolute")
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS local_action_attempts (
                    nonce TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    draft_id TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    started_at INTEGER NOT NULL,
                    result TEXT NOT NULL DEFAULT 'received'
                );
                CREATE INDEX IF NOT EXISTS lab_action_time_idx
                    ON local_action_attempts(started_at);
            """)

    def connect(self):
        connection = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    def consume(self, nonce: str, job_id: str, draft_id: str,
                operation: str, now: int | None = None) -> bool:
        now = int(time.time()) if now is None else now
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            # Retain the replay window for 24h for incident investigation.
            db.execute("DELETE FROM local_action_attempts WHERE started_at < ?",
                       (now - 86400,))
            try:
                db.execute("""INSERT INTO local_action_attempts
                    (nonce,job_id,draft_id,operation,started_at)
                    VALUES (?,?,?,?,?)""", (nonce, job_id, draft_id, operation, now))
            except sqlite3.IntegrityError:
                return False
        return True

    def complete(self, nonce: str, outcome: str) -> None:
        if outcome not in ("healthy", "rolled_back", "lifecycle", "denied", "failed"):
            outcome = "failed"
        with self.connect() as db:
            db.execute("UPDATE local_action_attempts SET result=? WHERE nonce=?",
                       (outcome, nonce))
