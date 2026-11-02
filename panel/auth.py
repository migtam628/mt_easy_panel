"""SQLite-backed single-admin authentication for Phase 1.

Uses scrypt with unique salts, hashed random session tokens, and expiration.
Argon2id, MFA, team membership, and persistent distributed rate-limiting are
planned for the later production hardening milestone.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
import time
from pathlib import Path

SESSION_TTL = 12 * 60 * 60


class AuthStore:
    def __init__(self, db_path: str):
        self.path = Path(db_path)
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with self._db() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  username TEXT NOT NULL UNIQUE,
                  salt TEXT NOT NULL,
                  password_hash TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                  token_hash TEXT PRIMARY KEY,
                  user_id INTEGER NOT NULL REFERENCES users(id),
                  expires_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_sessions_expiry ON sessions(expires_at);
            """)
        # SQLite uses process umask at creation. Protect credentials and session hashes.
        os.chmod(self.path, 0o600)

    def _db(self):
        conn = sqlite3.connect(self.path, timeout=5)
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @staticmethod
    def _hash_password(password: str, salt: bytes) -> str:
        return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1).hex()

    def create_admin(self, username: str, password: str):
        if not (3 <= len(username) <= 64 and username.isascii() and
                all(c.isalnum() or c in "_-" for c in username)):
            raise ValueError("Username must be 3-64 ASCII letters/numbers/_/-")
        if len(password) < 14 or len(password) > 1024:
            raise ValueError("Password must be 14-1024 characters")
        salt = os.urandom(16)
        with self._db() as conn:
            conn.execute("INSERT INTO users(username, salt, password_hash) VALUES (?, ?, ?)",
                         (username, salt.hex(), self._hash_password(password, salt)))

    def is_setup(self) -> bool:
        with self._db() as conn:
            return conn.execute("SELECT 1 FROM users LIMIT 1").fetchone() is not None

    def login(self, username: str, password: str) -> str | None:
        with self._db() as conn:
            row = conn.execute("SELECT id,salt,password_hash FROM users WHERE username=?", (username,)).fetchone()
            # Always perform a scrypt operation to reduce username enumeration timing differences.
            salt = bytes.fromhex(row[1]) if row else b"\x00" * 16
            candidate = self._hash_password(password, salt)
            if not row or not hmac.compare_digest(candidate, row[2]):
                return None
            token = secrets.token_urlsafe(48)
            conn.execute("DELETE FROM sessions WHERE expires_at < ?", (int(time.time()),))
            conn.execute("INSERT INTO sessions(token_hash, user_id, expires_at) VALUES (?,?,?)",
                         (self._token_hash(token), row[0], int(time.time()) + SESSION_TTL))
            return token

    @staticmethod
    def _token_hash(token: str):
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def user_for(self, token: str | None) -> dict | None:
        if not token or len(token) > 200:
            return None
        with self._db() as conn:
            row = conn.execute("""SELECT users.username, sessions.expires_at
                                  FROM sessions JOIN users ON users.id=sessions.user_id
                                  WHERE sessions.token_hash=?""", (self._token_hash(token),)).fetchone()
            if not row or row[1] <= int(time.time()):
                return None
            return {"username": row[0], "role": "owner"}

    def logout(self, token: str | None):
        if not token:
            return
        with self._db() as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash=?", (self._token_hash(token),))
