"""Durable, serialized, non-secret Ed25519 heartbeat sequence counter.

Avoids replay failures after clock corrections or service restarts.
Used only on the remote agent machine; never accesses the Docker socket.
"""
from __future__ import annotations
import fcntl
import os
from pathlib import Path
import stat
import time

MAX_SEQUENCE = 2**63 - 1


def next_sequence(key_file: Path) -> int:
    path = key_file.with_name(key_file.name + ".sequence")
    if path.is_symlink():
        raise ValueError("Refusing a symlink heartbeat counter")
    flags = os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise ValueError("Heartbeat counter must be a private, owner-controlled file")
        fcntl.flock(fd, fcntl.LOCK_EX)
        raw = os.read(fd, 64)
        if raw and (not raw.isdigit() or len(raw) > 20):
            raise ValueError("Heartbeat counter is corrupt")
        previous = int(raw) if raw else 0
        sequence = max(time.time_ns(), previous + 1)
        if sequence > MAX_SEQUENCE:
            raise ValueError("Heartbeat counter exceeds supported range")
        # Write and sync BEFORE emitting a signed heartbeat. Losing an outbound
        # request can skip a sequence, which is safe; reusing one is not.
        os.lseek(fd, 0, os.SEEK_SET)
        data = str(sequence).encode("ascii")
        os.write(fd, data)
        os.ftruncate(fd, len(data))
        os.fsync(fd)
        return sequence
    finally:
        os.close(fd)
