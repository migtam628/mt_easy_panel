#!/usr/bin/env python3
"""Read-only MT Panel release lifecycle status for the existing VPS.

Reports source, installed and staged revisions separately. No authentication,
Docker access, service modification, database mutation or promotion.
"""
from __future__ import annotations

import argparse
import http.client
import json
from pathlib import Path
import re
import subprocess
import tomllib

SOURCE = Path(__file__).resolve().parent.parent
INSTALL = Path("/opt/mt-panel")
OPT = Path("/opt")
REVISION = re.compile(r"[0-9a-f]{40}\Z")
STAGE = re.compile(r"mt-panel-stage\.[a-zA-Z0-9]{8,16}\Z")


def revision(path: Path) -> str | None:
    marker = path / ".staged-commit"
    try:
        if marker.is_symlink() or not marker.is_file():
            return None
        value = marker.read_text(encoding="utf-8").strip()
        return value if REVISION.fullmatch(value) else None
    except OSError:
        return None


def source_info() -> tuple[str | None, str | None]:
    sha = None
    version = None
    try:
        proc = subprocess.run(
            ["git", "-C", str(SOURCE), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5, check=False,
        )
        candidate = proc.stdout.strip()
        if proc.returncode == 0 and REVISION.fullmatch(candidate):
            sha = candidate
    except (OSError, subprocess.TimeoutExpired):
        pass
    try:
        data = tomllib.loads((SOURCE / "pyproject.toml").read_text(encoding="utf-8"))
        value = data["project"]["version"]
        if isinstance(value, str) and re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+\.dev[0-9]+", value):
            version = value.split(".dev", 1)[0] + "-dev"
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return sha, version


def live_version() -> str | None:
    conn = http.client.HTTPConnection("127.0.0.1", 8086, timeout=3)
    try:
        conn.request("GET", "/api/health", headers={"Accept": "application/json"})
        response = conn.getresponse()
        raw = response.read(2048)
        data = json.loads(raw) if response.status == 200 else None
        if (isinstance(data, dict) and data.get("ok") is True
                and data.get("service") == "mt-panel"
                and isinstance(data.get("version"), str)):
            return data["version"]
    except (OSError, ValueError):
        pass
    finally:
        conn.close()
    return None


def candidate_stages(root: Path = OPT) -> list[tuple[Path, str | None]]:
    try:
        paths = sorted(
            (p for p in root.iterdir()
             if STAGE.fullmatch(p.name) and not p.is_symlink() and p.is_dir()),
            key=lambda p: p.name,
        )
    except OSError:
        return []
    return [(path, revision(path)) for path in paths[:20]]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", required=True)
    args = parser.parse_args()
    source_sha, source_version = source_info()
    running = live_version()
    installed = revision(INSTALL)

    print("MT Panel release lifecycle (read-only)")
    print("LIVE VERSION:", running or "unavailable")
    print("INSTALLED COMMIT:", installed or "not marked")
    print("SOURCE VERSION:", source_version or "unavailable")
    print("SOURCE COMMIT:", source_sha or "unavailable")

    stages = candidate_stages()
    print("STAGED CANDIDATES:", len(stages))
    matching = []
    for path, sha in stages:
        print("  ", str(path), "revision", sha or "invalid/missing")
        if source_sha and sha == source_sha:
            matching.append(path)

    if source_version and running == source_version:
        print("STATE: LIVE VERSION MATCHES CURRENT SOURCE VERSION")
        print("PASS: Status collected; no services or databases changed")
        return

    if matching:
        print("STATE: SOURCE REVISION STAGED, NOT CONFIRMED LIVE")
        print("NEXT: Check one matching candidate with scripts/promote-vps.py")
        print("Use --check --stage EXACT_DIRECTORY --expect-commit EXACT_SOURCE_SHA")
        print("After operator-approved activation, run scripts/verify-live-vps.py")
    else:
        print("STATE: NO STAGE MATCHES CURRENT SOURCE (or source unavailable)")
        print("NEXT: Run bash scripts/upgrade-vps.sh --check then --stage")
    print("PASS: Status collected; no services or databases changed")


if __name__ == "__main__":
    main()
