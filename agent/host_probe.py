"""Collect a bounded, read-only Linux host summary and sign an outbound report.

No Docker socket access; never sends IP addresses, paths, environment values or
container details. Only a separate, opted-in agent identity can submit.
"""
from __future__ import annotations
import os
from pathlib import Path
import platform
import shutil
import socket
import time

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from agent.enroll import checked_origin, encode, identity_path, request, HEX_ID
from agent.sequence import next_sequence
from protocol.host_snapshot import HostSnapshot, host_report_message


def read_mem_total() -> int:
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemTotal:"):
            return int(line.split()[1]) * 1024
    raise ValueError("Linux /proc/meminfo is missing MemTotal")


def read_uptime() -> int:
    return int(float(Path("/proc/uptime").read_text().split()[0]))


def collect_host_snapshot() -> HostSnapshot:
    if platform.system() != "Linux":
        raise ValueError("Host reports currently support Linux only")
    disk = shutil.disk_usage("/")
    cpus = os.cpu_count()
    return HostSnapshot(
        hostname=socket.gethostname(),
        system=platform.system() + " " + platform.release(),
        cpu_count=cpus or 0,
        memory_total_bytes=read_mem_total(),
        disk_total_bytes=disk.total,
        disk_free_bytes=disk.free,
        uptime_seconds=read_uptime(),
    )


def submit_report(origin: str, server_id: str, key_file: Path) -> dict:
    origin = checked_origin(origin)
    if not HEX_ID.fullmatch(server_id):
        raise ValueError("Invalid server ID")
    key_file = identity_path(key_file, True)
    private = serialization.load_pem_private_key(key_file.read_bytes(), password=None)
    if not isinstance(private, Ed25519PrivateKey):
        raise ValueError("Expected an Ed25519 private key")
    snapshot = collect_host_snapshot()
    sequence = next_sequence(key_file)
    timestamp = int(time.time())
    signature = encode(private.sign(
        host_report_message(server_id, sequence, timestamp, snapshot)))
    result = request(origin, "/api/agents/" + server_id + "/host-report",
                     {"sequence":sequence, "timestamp":timestamp,
                      "snapshot":snapshot.safe_dump(), "signature":signature})
    if result.get("status") != "accepted" or result.get("server_id") != server_id:
        raise ValueError("Unexpected host report response")
    return {"ok": True, "server_id": server_id, "status": "accepted"}
