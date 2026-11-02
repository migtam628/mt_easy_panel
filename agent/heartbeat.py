"""Opt-in, one-shot outbound-only heartbeat runner.

No daemon, no background process, no Docker socket and no remote commands.
A user-systemd timer can invoke --once when explicitly installed by operator.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import stat
import sys

from agent.enroll import checked_origin, heartbeat, identity_path, HEX_ID

FIELDS = frozenset(("control_url", "server_id", "key_file"))


def read_config(path: Path) -> dict:
    path = path.expanduser().absolute()
    if path.is_symlink() or not path.is_file():
        raise ValueError("Config must be a regular file, not a symbolic link")
    info = path.stat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
            or info.st_mode & 0o077 or info.st_size > 4096):
        raise ValueError("Config must be private, owner-owned and smaller than 4 KB")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or set(data) != FIELDS:
        raise ValueError("Expected only control_url, server_id and key_file")
    if not all(isinstance(data[key], str) for key in FIELDS):
        raise ValueError("All config fields must be strings")
    origin = checked_origin(data["control_url"])
    server_id = data["server_id"]
    if not HEX_ID.fullmatch(server_id):
        raise ValueError("Invalid agent server ID")
    key_path = Path(data["key_file"])
    if not key_path.is_absolute():
        raise ValueError("Key path must be absolute")
    return {"control_url": origin, "server_id": server_id,
            "key_file": identity_path(key_path, True)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--check", action="store_true")
    modes.add_argument("--once", action="store_true")
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    try:
        config = read_config(args.config)
        if args.check:
            print("PASS: Private agent identity and Tailscale control URL validated")
            return
        heartbeat(**dict(origin=config["control_url"],
                         server_id=config["server_id"], path=config["key_file"]))
        print("PASS: One signed outbound heartbeat accepted")
    except Exception as exc:
        # Output only the exception type, never URLs, keys or HTTP response bodies.
        print("Agent heartbeat failed:", type(exc).__name__, file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
