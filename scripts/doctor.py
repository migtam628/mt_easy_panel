#!/usr/bin/env python3
"""Diagnostic for local Phase 1 installation. Does not change configuration."""
from __future__ import annotations
import os
import pathlib
import socket
import sys
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from agent.docker import choose_docker_socket


def load_env():
    config = ROOT / ".env"
    if not config.is_file():
        print("FAIL: .env missing (run bash scripts/init-env.sh)")
        sys.exit(1)
    # This diagnostics script reads simple KEY=VALUE fields, not arbitrary shell code.
    for line in config.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key in ("AGENT_PORT", "PANEL_PORT", "AGENT_TOKEN", "AGENT_DEMO_MODE", "DOCKER_SOCKET_PATH"):
            os.environ.setdefault(key, value.strip().strip('"').strip("'"))


def probe(url, token=None):
    headers = {"Authorization": "Bearer " + token} if token else {}
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=4) as response:
            print(f"PASS: {url} -> HTTP {response.status}")
            return response.status
    except urllib.error.HTTPError as exc:
        print(f"WARN: {url} -> HTTP {exc.code}")
        return exc.code
    except (OSError, urllib.error.URLError) as exc:
        print(f"FAIL: {url} -> connection failed ({type(exc).__name__})")
        return None


def main():
    load_env()
    agent_port = os.environ.get("AGENT_PORT", "8788")
    panel_port = os.environ.get("PANEL_PORT", "8086")
    demo = os.environ.get("AGENT_DEMO_MODE", "false").lower() == "true"
    print("MT Panel diagnostics (no changes made)")
    print(f"Demo mode: {demo}")
    sock = choose_docker_socket()
    if os.path.exists(sock):
        print(f"Docker socket found: {sock}")
    else:
        print(f"Docker socket missing: {sock}")
    probe(f"http://127.0.0.1:{panel_port}/api/health")
    probe(f"http://127.0.0.1:{agent_port}/health")
    tok = os.environ.get("AGENT_TOKEN", "")
    if len(tok) < 32:
        print("WARN: AGENT_TOKEN is missing or too short")
    else:
        status = probe(f"http://127.0.0.1:{agent_port}/v1/overview", token=tok)
        if status == 503:
            print("NEXT: Start Docker Desktop/Engine, or configure DOCKER_SOCKET_PATH in .env")
        elif status == 401:
            print("NEXT: Restart both services so they read the same AGENT_TOKEN")
        elif status is None:
            print("NEXT: Run bash scripts/dev.sh and check the agent startup output")


if __name__ == "__main__":
    main()
