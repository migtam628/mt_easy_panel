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
            db.execute("""UPDATE agent_identities SET last_sequence=?,last_seen=?
                          WHERE server_id=?""", (sequence, now, server_id))
        return {"server_id": server_id, "status": "accepted"}
