"""Outbound-only, key-bound agent enrollment. No Docker commands or remote URLs.

Owner creates one-time invitation. Agent proves Ed25519 private-key possession
and consumes the invitation over private HTTPS. Signed monotonic heartbeats
do not carry Docker data or permit control-plane-initiated agent requests.
"""
from __future__ import annotations

import base64
import hashlib
import re
import secrets
import sqlite3
import time

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from panel.registry import Registry, RegistryError

INVITE_TTL = 600
HEARTBEAT_SKEW = 120
HEX_ID = re.compile(r"^[0-9a-f]{32}$")
TOKEN = re.compile(r"^[a-zA-Z0-9_-]{43}$")


def decode_b64(value: str, length: int) -> bytes:
    if not isinstance(value, str) or len(value) > 200:
        raise RegistryError("Invalid agent identity proof", 401)
    try:
        raw = base64.b64decode(value, altchars=b"-_", validate=True)
    except (ValueError, base64.binascii.Error) as error:
        raise RegistryError("Invalid agent identity proof", 401) from error
    if len(raw) != length:
        raise RegistryError("Invalid agent identity proof", 401)
    return raw


def signed_enrollment_message(server_id: str, nonce: str) -> bytes:
    if not HEX_ID.fullmatch(server_id) or not isinstance(nonce, str) or not TOKEN.fullmatch(nonce):
        raise RegistryError("Invalid enrollment payload", 401)
    return f"mtpanel-agent-enroll-v1:{server_id}:{nonce}".encode("ascii")


def signed_heartbeat_message(server_id: str, seq: int, timestamp: int) -> bytes:
    return f"mtpanel-agent-heartbeat-v1:{server_id}:{seq}:{timestamp}".encode("ascii")


class EnrollmentStore:
    def __init__(self, db_path: str):
        self.registry = Registry(db_path)
        with self.registry.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS enrollment_invites (
                    server_id TEXT PRIMARY KEY REFERENCES servers(id),
                    token_hash TEXT NOT NULL UNIQUE,
                    created_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS agent_identities (
                    server_id TEXT PRIMARY KEY REFERENCES servers(id),
                    public_key BLOB NOT NULL,
                    fingerprint TEXT NOT NULL,
                    enrolled_at INTEGER NOT NULL,
                    revoked_at INTEGER,
                    last_sequence INTEGER NOT NULL DEFAULT 0,
                    last_seen INTEGER
                );
            """)

    @staticmethod
    def _clear_prior_telemetry(db, server_id: str) -> None:
        # An old machine's signed snapshot must never be attributed to a
        # newly enrolled key. The table is optional for older store-only tests.
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='host_snapshots'").fetchone():
            db.execute("DELETE FROM host_snapshots WHERE server_id=?", (server_id,))

    @staticmethod
    def _owned(db, owner: str, server_id: str):
        row = db.execute("SELECT status FROM servers WHERE id=? AND owner=?",
                         (server_id, owner)).fetchone()
        if row is None:
            raise RegistryError("Server not found", 404)
        return row["status"]

    def server_identity(self, owner: str, server_id: str) -> dict:
        with self.registry.connect() as db:
            status = self._owned(db, owner, server_id)
            row = db.execute("""SELECT fingerprint,enrolled_at,revoked_at,last_seen,
                                last_sequence FROM agent_identities WHERE server_id=?""",
                             (server_id,)).fetchone()
            heartbeat_state = "not_enrolled"
            if status == "revoked":
                heartbeat_state = "revoked"
            elif status == "paired" and row:
                seen = row["last_seen"]
                heartbeat_state = ("never_seen" if seen is None else
                                   "recent" if int(time.time()) - seen <= 180 else "stale")
            return {"server_id": server_id, "status": status,
                    "heartbeat_state": heartbeat_state,
                    "identity": dict(row) if row else None}

    def create_invite(self, owner: str, server_id: str) -> dict:
        if not HEX_ID.fullmatch(server_id):
            raise RegistryError("Server not found", 404)
        token = secrets.token_urlsafe(32)
        now = int(time.time())
        with self.registry.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            status = self._owned(db, owner, server_id)
            if status == "paired":
                raise RegistryError("Revoke the existing identity before issuing a replacement", 409)
            db.execute("DELETE FROM enrollment_invites WHERE server_id=?", (server_id,))
            db.execute("""INSERT INTO enrollment_invites(server_id,token_hash,created_at,expires_at)
                          VALUES(?,?,?,?)""",
                       (server_id, hashlib.sha256(token.encode("ascii")).hexdigest(),
                        now, now + INVITE_TTL))
            self.registry.audit(db, owner, "agent.invite.created", server_id)
        # The token is never stored in plaintext or included in list/status responses.
        return {"server_id": server_id, "enrollment_code": token,
                "expires_at": now + INVITE_TTL, "single_use": True}

    def enroll(self, server_id: str, code: str, public_key: str,
               signature: str, nonce: str) -> dict:
        if not HEX_ID.fullmatch(server_id) or not isinstance(code, str) or not TOKEN.fullmatch(code):
            raise RegistryError("Invalid or expired invitation", 401)
        key_data = decode_b64(public_key, 32)
        sig_data = decode_b64(signature, 64)
        message = signed_enrollment_message(server_id, nonce)
        try:
            Ed25519PublicKey.from_public_bytes(key_data).verify(sig_data, message)
        except (InvalidSignature, ValueError) as exc:
            raise RegistryError("Invalid agent identity proof", 401) from exc
        now = int(time.time())
        candidate_hash = hashlib.sha256(code.encode("ascii")).hexdigest()
        with self.registry.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("""
                SELECT i.expires_at,s.owner,s.status
                FROM enrollment_invites i JOIN servers s ON s.id=i.server_id
                WHERE i.server_id=? AND i.token_hash=?
            """, (server_id, candidate_hash)).fetchone()
            if row is None or row["expires_at"] <= now or row["status"] == "paired":
                raise RegistryError("Invalid or expired invitation", 401)
            fingerprint = hashlib.sha256(key_data).hexdigest()
            db.execute("""INSERT INTO agent_identities
                  (server_id, public_key, fingerprint, enrolled_at, revoked_at,
                   last_sequence, last_seen)
                  VALUES (?,?,?,?,NULL,0,NULL)
                  ON CONFLICT(server_id) DO UPDATE SET
                   public_key=excluded.public_key, fingerprint=excluded.fingerprint,
                   enrolled_at=excluded.enrolled_at, revoked_at=NULL,
                   last_sequence=0,last_seen=NULL""",
                       (server_id, key_data, fingerprint, now))
            self._clear_prior_telemetry(db, server_id)
            db.execute("UPDATE servers SET status='paired' WHERE id=?", (server_id,))
            db.execute("DELETE FROM enrollment_invites WHERE server_id=?", (server_id,))
            self.registry.audit(db, row["owner"], "agent.enrolled", server_id)
        return {"server_id": server_id, "status": "paired", "fingerprint": fingerprint}

    def heartbeat(self, server_id: str, sequence: int, timestamp: int,
                  signature: str) -> dict:
        if (not HEX_ID.fullmatch(server_id) or not isinstance(sequence, int)
                or isinstance(sequence, bool) or not 1 <= sequence <= 2**63 - 1
                or not isinstance(timestamp, int) or isinstance(timestamp, bool)
                or abs(int(time.time()) - timestamp) > HEARTBEAT_SKEW):
            raise RegistryError("Invalid signed heartbeat", 401)
        sig_data = decode_b64(signature, 64)
        now = int(time.time())
        with self.registry.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("""SELECT a.public_key,a.last_sequence,s.status FROM agent_identities a
                               JOIN servers s ON s.id=a.server_id
                               WHERE a.server_id=? AND a.revoked_at IS NULL""",
                             (server_id,)).fetchone()
            if row is None or row["status"] != "paired" or sequence <= row["last_sequence"]:
                raise RegistryError("Heartbeat rejected: revoked, unknown or replayed", 401)
            try:
                Ed25519PublicKey.from_public_bytes(row["public_key"]).verify(
                    sig_data, signed_heartbeat_message(server_id, sequence, timestamp))
            except (InvalidSignature, ValueError) as exc:
                raise RegistryError("Invalid signed heartbeat", 401) from exc
            db.execute("""UPDATE agent_identities SET last_sequence=?,last_seen=?
                          WHERE server_id=?""", (sequence, now, server_id))
        return {"ok": True, "server_id": server_id, "status": "paired"}

    def revoke(self, owner: str, server_id: str) -> dict:
        if not HEX_ID.fullmatch(server_id):
            raise RegistryError("Server not found", 404)
        now = int(time.time())
        with self.registry.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            status = self._owned(db, owner, server_id)
            if status == "revoked":
                raise RegistryError("Server identity already revoked", 409)
            db.execute("DELETE FROM enrollment_invites WHERE server_id=?", (server_id,))
            db.execute("UPDATE agent_identities SET revoked_at=? WHERE server_id=?",
                       (now, server_id))
            db.execute("UPDATE servers SET status='revoked' WHERE id=?", (server_id,))
            self._clear_prior_telemetry(db, server_id)
            self.registry.audit(db, owner, "agent.revoked", server_id)
        return {"server_id": server_id, "status": "revoked"}
