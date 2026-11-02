#!/usr/bin/env python3
"""Read-only post-promotion checks for MT Panel on a Tailscale-only VPS.

This utility never authenticates as the owner, never logs a secret,
never changes any database, and never touches Docker or systemd state.
"""
from __future__ import annotations

import argparse
import http.client
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import sys

DB_PATH = Path("/var/lib/mt-panel/panel.db")
INSTALL = Path("/opt/mt-panel")
TABLES = {
    "users": {"username", "password_hash"},
    "sessions": {"token_hash", "expires_at"},
    "audit_events": {"actor", "action", "result"},
    "servers": {"id", "owner", "status"},
    "projects": {"id", "owner", "server_id"},
    "environments": {"id", "project_id"},
    "service_drafts": {"id", "environment_id"},
    "agent_identities": {"server_id", "public_key", "last_sequence"},
    "enrollment_invites": {"server_id", "token_hash", "expires_at"},
    "host_snapshots": {"server_id", "snapshot_json", "sequence"},
    "host_report_history": {"server_id", "sequence", "recorded_at", "disk_free_percent"},
}
SERVE_ROUTE = re.compile(
    r"^https://[a-z0-9-]+(?:\.[a-z0-9-]+)+\.ts\.net:8443 "
    r"\(tailnet only\)\s*\n\|-- / proxy http://127\.0\.0\.1:8086(?:\s|$)",
    re.MULTILINE,
)


def get_local(port: int, path: str) -> tuple[int, object]:
    if path not in (
        "/health", "/api/health", "/api/auth/me",
        "/api/catalog/servers", "/api/server/overview",
        "/api/monitoring/overview", "/api/deployments/readiness",
        "/api/settings/security",
    ):
        raise ValueError("Unrecognized read-only health probe")
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    try:
        conn.request("GET", path, headers={"Accept": "application/json"})
        response = conn.getresponse()
        body = response.read(4096)
        if response.getheader("Content-Length") and int(response.getheader("Content-Length")) > 4096:
            raise ValueError("Oversized response")
        try:
            payload = json.loads(body)
        except (ValueError, UnicodeDecodeError):
            payload = None
        return response.status, payload
    finally:
        conn.close()


def check_http(expected_version: str) -> list[str]:
    errors = []
    for port, route, service in (
        (8086, "/api/health", "mt-panel"),
        (8788, "/health", "mt-panel-agent"),
    ):
        try:
            code, payload = get_local(port, route)
        except (OSError, ValueError, TimeoutError):
            errors.append(f"Local {service} health request failed")
            continue
        if code != 200 or not isinstance(payload, dict) or payload.get("service") != service or payload.get("ok") is not True:
            errors.append(f"Local {service} health identity/status mismatch")
            continue
        version = payload.get("version")
        if service == "mt-panel" and version != expected_version:
            errors.append(f"Dashboard version is {version!r}; expected {expected_version!r} (not promoted)")
        else:
            print(f"PASS: {service} health (version {version})")
    for path in (
        "/api/auth/me", "/api/catalog/servers", "/api/server/overview",
        "/api/monitoring/overview", "/api/deployments/readiness",
        "/api/settings/security",
    ):
        try:
            code, _ = get_local(8086, path)
        except (OSError, ValueError, TimeoutError):
            errors.append(f"Unable to check unauthenticated boundary {path}")
            continue
        if code != 401:
            errors.append(f"Unauthenticated {path} returned HTTP {code}; expected 401")
        else:
            print(f"PASS: unauthenticated {path} denied")
    return errors


def check_database(path: Path = DB_PATH) -> list[str]:
    errors = []
    if not path.is_file():
        return ["MT Panel database not found"]
    try:
        # Mode ro plus query_only; never import the application (which would
        # otherwise run additive schema initialization).
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2) as db:
            db.execute("PRAGMA query_only=ON")
            row = db.execute("PRAGMA quick_check").fetchone()
            if row != ("ok",):
                errors.append("Database quick_check failed")
            found = {
                name for (name,) in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            for name, required in TABLES.items():
                if name not in found:
                    errors.append(f"Missing schema table {name}")
                    continue
                actual = {col[1] for col in db.execute(f"PRAGMA table_info({name})")}
                if not required.issubset(actual):
                    errors.append(f"Missing expected columns in {name}")
    except (sqlite3.Error, OSError):
        errors.append("Unable to read and inspect installed SQLite database")
    if not errors:
        print("PASS: read-only SQLite integrity and enrollment/reporting schema checks")
    return errors


def check_tailscale() -> list[str]:
    try:
        proc = subprocess.run(
            ["tailscale", "serve", "status"],
            capture_output=True, text=True, timeout=8, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ["Unable to read Tailscale Serve status"]
    if proc.returncode or not SERVE_ROUTE.search(proc.stdout):
        return ["Expected private HTTPS 8443 -> local 8086 Tailscale Serve route not found"]
    print("PASS: Tailscale Serve private HTTPS 8443 -> 127.0.0.1:8086")
    return []


def check_revision(path: Path = INSTALL) -> list[str]:
    marker = path / ".staged-commit"
    if not marker.is_file():
        print("WARN: No staged commit marker in installed code (older pilot installation)")
        return []
    try:
        sha = marker.read_text(encoding="utf-8").strip()
    except OSError:
        return ["Unable to read installed revision marker"]
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        return ["Invalid installed revision marker"]
    print(f"PASS: installed staged Git revision {sha[:12]}")
    return []


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", required=True)
    parser.add_argument("--expected-version", default="0.3.5-dev")
    args = parser.parse_args()
    errors = []
    errors.extend(check_http(args.expected_version))
    errors.extend(check_database())
    errors.extend(check_tailscale())
    errors.extend(check_revision())
    if errors:
        for problem in errors:
            print("FAIL:", problem, file=sys.stderr)
        raise SystemExit(1)
    print("PASS: MT Panel post-promotion read-only verification completed")


if __name__ == "__main__":
    main()
