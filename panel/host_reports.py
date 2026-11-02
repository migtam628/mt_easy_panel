"""Strict signed host-health ingestion and owner-only readback.

No inbound agent listener, Docker API proxy, remote shell, or service execution.
The body is a fixed schema; signed sequence shares heartbeat replay state.
"""
from __future__ import annotations

import json
import time
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from panel.enrollment import HEX_ID, HEARTBEAT_SKEW, decode_b64
from panel.registry import Registry, RegistryError
from protocol.host_snapshot import HostSnapshot, host_report_message


class HostReports:
    def __init__(self, db_path: str):
        self.registry = Registry(db_path)
        with self.registry.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS host_snapshots(
                    server_id TEXT PRIMARY KEY REFERENCES servers(id),
                    snapshot_json TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    recorded_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS host_report_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    server_id TEXT NOT NULL REFERENCES servers(id),
                    sequence INTEGER NOT NULL,
                    recorded_at INTEGER NOT NULL,
                    disk_free_percent REAL NOT NULL,
                    uptime_seconds INTEGER NOT NULL,
                    UNIQUE(server_id, sequence)
                );
                CREATE INDEX IF NOT EXISTS idx_host_report_history_recent
                    ON host_report_history(server_id, id DESC);
            """)

    def get(self, owner: str, server_id: str) -> dict:
        with self.registry.connect() as db:
            owned = db.execute(
                "SELECT status FROM servers WHERE owner=? AND id=?",
                (owner, server_id)).fetchone()
            if not owned:
                raise RegistryError("Server not found", 404)
            if owned["status"] != "paired":
                return {"server_id": server_id, "state": "not_connected", "snapshot": None}
            row = db.execute("""SELECT snapshot_json, sequence, recorded_at
                FROM host_snapshots WHERE server_id=?""", (server_id,)).fetchone()
            if not row:
                return {"server_id": server_id, "state": "never_seen", "snapshot": None}
            age = max(0, int(time.time()) - row["recorded_at"])
            return {"server_id": server_id, "state": "recent" if age <= 180 else "stale",
                    "received_at": row["recorded_at"], "sequence": row["sequence"],
                    "snapshot": json.loads(row["snapshot_json"])}

    def history(self, owner: str, server_id: str, limit: int = 96) -> dict:
        if not 1 <= limit <= 200:
            raise RegistryError("History limit must be 1-200")
        with self.registry.connect() as db:
            row = db.execute("SELECT status FROM servers WHERE id=? AND owner=?",
                             (server_id, owner)).fetchone()
            if row is None:
                raise RegistryError("Server not found", 404)
            if row["status"] != "paired":
                return {"server_id": server_id, "state": "not_connected", "samples": []}
            records = db.execute("""
                SELECT recorded_at, disk_free_percent, uptime_seconds
                  FROM host_report_history WHERE server_id=?
              ORDER BY id DESC LIMIT ?
            """, (server_id, limit)).fetchall()
        return {"server_id": server_id, "state": "history" if records else "no_samples",
                "samples": [dict(entry) for entry in reversed(records)],
                "metric": "disk_free_percent", "signed_reports_only": True}

    def ingest(self, server_id: str, sequence: int, timestamp: int,
               signature: str, snapshot: HostSnapshot) -> dict:
        if (not HEX_ID.fullmatch(server_id) or not isinstance(sequence, int)
                or isinstance(sequence, bool) or not 1 <= sequence <= 2**63 - 1
                or not isinstance(timestamp, int) or isinstance(timestamp, bool)
                or abs(int(time.time()) - timestamp) > HEARTBEAT_SKEW):
            raise RegistryError("Invalid signed host report", 401)
        sig_data = decode_b64(signature, 64)
        now = int(time.time())
        with self.registry.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("""SELECT a.public_key,a.last_sequence,s.status
                FROM agent_identities a JOIN servers s ON s.id=a.server_id
                WHERE a.server_id=? AND a.revoked_at IS NULL""",
                             (server_id,)).fetchone()
            if not row or row["status"] != "paired" or sequence <= row["last_sequence"]:
                raise RegistryError("Report rejected: revoked, unknown or replayed", 401)
            try:
                Ed25519PublicKey.from_public_bytes(row["public_key"]).verify(
                    sig_data, host_report_message(server_id, sequence, timestamp, snapshot))
            except (InvalidSignature, ValueError) as exc:
                raise RegistryError("Invalid host report signature", 401) from exc
            db.execute("""INSERT INTO host_snapshots(
                    server_id,snapshot_json,sequence,recorded_at) VALUES(?,?,?,?)
                    ON CONFLICT(server_id) DO UPDATE SET
                      snapshot_json=excluded.snapshot_json,
                      sequence=excluded.sequence,recorded_at=excluded.recorded_at""",
                       (server_id, snapshot.model_dump_json(), sequence, now))
            free_percent = round(
                100.0 * snapshot.disk_free_bytes / snapshot.disk_total_bytes, 1
            )
            db.execute("""INSERT INTO host_report_history
                (server_id, sequence, recorded_at, disk_free_percent, uptime_seconds)
                VALUES (?,?,?,?,?)""",
                (server_id, sequence, now, free_percent, snapshot.uptime_seconds))
            # Keep up to 288 most recent signed records per registered server.
            # The bound applies atomically with each validated report.
            db.execute("""DELETE FROM host_report_history
                WHERE server_id=?
                  AND id NOT IN (
                    SELECT id FROM host_report_history WHERE server_id=?
                    ORDER BY id DESC LIMIT 288
                  )""", (server_id, server_id))
            db.execute("""UPDATE agent_identities SET last_sequence=?,last_seen=?
                          WHERE server_id=?""", (sequence, now, server_id))
        return {"server_id": server_id, "status": "accepted"}
