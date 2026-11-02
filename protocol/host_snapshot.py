"""Strict, cross-process signed host-health report protocol.

Only fixed, low-risk numerical host metrics; no container names, environment
values, logs, secrets, interface addresses, commands, paths, or arbitrary JSON.
"""
from __future__ import annotations
import hashlib
import json
import re
from pydantic import BaseModel, ConfigDict, Field, field_validator

HOSTNAME = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,99}$")


class HostSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    hostname: str = Field(min_length=1, max_length=100)
    system: str = Field(min_length=1, max_length=120)
    cpu_count: int = Field(ge=1, le=1024)
    memory_total_bytes: int = Field(ge=1, le=2**60)
    disk_total_bytes: int = Field(ge=1, le=2**63 - 1)
    disk_free_bytes: int = Field(ge=0, le=2**63 - 1)
    uptime_seconds: int = Field(ge=0, le=2**40)

    @field_validator("hostname")
    @classmethod
    def host_pattern(cls, value):
        if not HOSTNAME.fullmatch(value):
            raise ValueError("Invalid hostname")
        return value

    @field_validator("system")
    @classmethod
    def system_string(cls, value):
        if value.strip() != value or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Invalid operating system label")
        return value

    @field_validator("disk_free_bytes")
    @classmethod
    def disk_free_nonnegative(cls, value):
        return value

    def safe_dump(self) -> dict:
        if self.disk_free_bytes > self.disk_total_bytes:
            raise ValueError("Free disk bytes exceed total disk capacity")
        return self.model_dump()


def host_report_message(server_id: str, sequence: int, timestamp: int,
                        snapshot: HostSnapshot) -> bytes:
    payload = json.dumps(snapshot.safe_dump(), sort_keys=True,
                         separators=(",", ":"), ensure_ascii=True).encode("ascii")
    digest = hashlib.sha256(payload).hexdigest()
    return f"mtpanel-agent-host-report-v1:{server_id}:{sequence}:{timestamp}:{digest}".encode("ascii")
