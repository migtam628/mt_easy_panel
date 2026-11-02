#!/usr/bin/env python3
"""Read-only diagnostic for an existing MT Panel VPS installation.

No shell execution, no mutation, no secrets emitted.
"""
from __future__ import annotations
import argparse
import pathlib
import re
import subprocess

ENV_PATH = pathlib.Path("/etc/mt-panel/mt-panel.env")
UNITS = {"mt-panel.service": "mtpanel", "mt-panel-agent.service": "mtpanel-agent"}
PORTS = (8086, 8788)


def run(*args):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None


def inspect() -> int:
    errors = 0
    print("MT Panel installed-VPS status (read-only)")
    for service, owner in UNITS.items():
        active = run("systemctl", "is-active", "--quiet", service)
        user = run("systemctl", "show", "-p", "User", "--value", service)
        if active is not None and active.returncode == 0:
            print(f"PASS: {service} active")
        else:
            print(f"FAIL: {service} inactive")
            errors += 1
        if user is not None and user.returncode == 0 and user.stdout.strip() == owner:
            print(f"PASS: {service} identity {owner}")
        else:
            print(f"FAIL: {service} unexpected identity")
            errors += 1

    sock = run("ss", "-H", "-lnt")
    if sock is None or sock.returncode:
        print("FAIL: Unable to inspect listening sockets")
        errors += 1
    else:
        for port in PORTS:
            addresses = []
            for line in sock.stdout.splitlines():
                fields = line.split()
                if len(fields) >= 4 and fields[3].endswith(":" + str(port)):
                    addresses.append(fields[3])
            expected = {"127.0.0.1:" + str(port), "[::1]:" + str(port)}
            if addresses and all(address in expected for address in addresses):
                print(f"PASS: Port {port} is loopback only")
            else:
                print(f"FAIL: Port {port} missing or exposed on non-loopback address")
                errors += 1

    try:
        rows = ENV_PATH.read_text(encoding="utf-8").splitlines()
    except OSError:
        rows = []
        print("WARN: Installed private configuration is unavailable")
    safe = {}
    for line in rows:
        if line.startswith("PANEL_PUBLIC_ORIGIN="):
            safe["origin"] = line.partition("=")[2]
        elif line.startswith("PANEL_COOKIE_SECURE="):
            safe["secure"] = line.partition("=")[2]
    origin = safe.get("origin", "")
    if (re.fullmatch(r"https://[a-z0-9-]+(?:\.[a-z0-9-]+)+\.ts\.net:8443", origin)
            and safe.get("secure") == "true"):
        print("PASS: Tailscale HTTPS origin and Secure cookies")
        print("Configured browser origin: " + origin)
    else:
        print("WARN: Tailscale HTTPS origin and Secure cookies are not both configured")

    if errors:
        print(f"FAIL: {errors} installation check(s) need operator review")
        return 1
    print("PASS: All process and listener checks succeeded")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", required=True)
    parser.parse_args()
    raise SystemExit(inspect())


if __name__ == "__main__":
    main()
