"""Private-Tailscale outbound agent identity bootstrap and signed heartbeat.

This CLI never opens the Docker socket or listens on a network port.
It speaks only verified HTTPS to a *.ts.net host on 8443. Enrollment secret
is entered using getpass (never command-line arguments or log output).
"""
from __future__ import annotations

import argparse
import base64
import getpass
import json
import os
from pathlib import Path
import re
import secrets
import stat
import sys
import time
from urllib.parse import urlsplit

import httpx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

HEX_ID = re.compile(r"^[0-9a-f]{32}$")
TS_HOST = re.compile(r"^[a-z0-9-]+(?:\.[a-z0-9-]+)+\.ts\.net$")


def checked_origin(url: str) -> str:
    parts = urlsplit(url)
    if (parts.scheme != "https" or not TS_HOST.fullmatch(parts.hostname or "")
            or parts.port != 8443 or parts.username or parts.password
            or parts.path not in ("", "/") or parts.query or parts.fragment):
        raise ValueError("Control plane must be an exact https://*.ts.net:8443 origin")
    return "https://" + parts.hostname + ":8443"


def encode(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def identity_path(path: Path, existing: bool) -> Path:
    resolved = path.expanduser().absolute()
    if resolved.is_symlink():
        raise ValueError("Identity must not be a symbolic link")
    if existing:
        if not resolved.is_file() or resolved.stat().st_mode & 0o077:
            raise ValueError("Private key must exist with mode 0600")
    elif resolved.exists():
        raise ValueError("Identity key already exists; refusing to overwrite it")
    if not resolved.parent.is_dir() or resolved.parent.is_symlink():
        raise ValueError("Create a private, non-symlink parent directory first")
    return resolved


def request(origin: str, path: str, payload: dict) -> dict:
    # Refuse HTTP redirects and proxy environment variables.
    with httpx.Client(timeout=12, trust_env=False, follow_redirects=False) as client:
        response = client.post(origin + path, json=payload)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict) or not isinstance(data.get("data"), dict):
            raise ValueError("Control plane returned an invalid response")
        return data["data"]


def enroll(origin: str, server_id: str, path: Path) -> dict:
    origin = checked_origin(origin)
    if not HEX_ID.fullmatch(server_id):
        raise ValueError("Invalid server ID")
    path = identity_path(path, False)
    print("Enrollment code (input hidden):", file=sys.stderr)
    code = getpass.getpass("")
    if len(code) != 43:
        raise ValueError("Enrollment code must be exactly 43 characters")
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw)
    nonce = secrets.token_urlsafe(32)
    message = f"mtpanel-agent-enroll-v1:{server_id}:{nonce}".encode("ascii")
    body = {"server_id": server_id, "code": code, "public_key": encode(public),
            "signature": encode(key.sign(message)), "nonce": nonce}
    # Stage the key privately first, so a successful enrollment can be saved.
    old_umask = os.umask(0o077)
    tmp = path.with_name(path.name + "." + secrets.token_hex(8) + ".pending")
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as output:
            output.write(key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption()))
            output.flush()
            os.fsync(output.fileno())
        try:
            result = request(origin, "/api/agents/enroll", body)
            if result.get("status") != "paired" or result.get("server_id") != server_id:
                raise ValueError("Unexpected enrollment response")
            os.rename(tmp, path)
            return {"server_id": server_id, "status": "paired",
                    "fingerprint": result.get("fingerprint", "")}
        finally:
            tmp.unlink(missing_ok=True)
    finally:
        os.umask(old_umask)


def heartbeat(origin: str, server_id: str, path: Path) -> dict:
    origin = checked_origin(origin)
    if not HEX_ID.fullmatch(server_id):
        raise ValueError("Invalid server ID")
    path = identity_path(path, True)
    key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("Identity key is not Ed25519")
    timestamp = int(time.time())
    # Unix-nanosecond sequences avoid state loss after process restart.
    # Very unusual backward wall-clock jumps may require re-enrollment.
    sequence = time.time_ns()
    message = f"mtpanel-agent-heartbeat-v1:{server_id}:{sequence}:{timestamp}".encode("ascii")
    result = request(origin, "/api/agents/" + server_id + "/heartbeat",
                     {"sequence": sequence, "timestamp": timestamp,
                      "signature": encode(key.sign(message))})
    if result.get("status") != "paired" or result.get("server_id") != server_id:
        raise ValueError("Unexpected heartbeat response")
    return {"ok": True, "server_id": server_id}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--enroll", action="store_true")
    mode.add_argument("--heartbeat", action="store_true")
    parser.add_argument("--control-url", required=True)
    parser.add_argument("--server-id", required=True)
    parser.add_argument("--key-file", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = (enroll(args.control_url, args.server_id, args.key_file) if args.enroll
                  else heartbeat(args.control_url, args.server_id, args.key_file))
        print(json.dumps(result))
    except (ValueError, OSError, httpx.HTTPError) as exc:
        # Do not print the response body: it could disclose credentials.
        print("Enrollment/heartbeat failed:", type(exc).__name__, file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
