"""Constrained, read-only Docker Engine adapter.

Only hard-coded GET requests are permitted. Do not turn this into an arbitrary
Engine API proxy. The Unix socket itself is still root-equivalent; isolate the
agent from the public web server and restrict access at the OS level.
"""
from __future__ import annotations

import http.client
import json
import os
import re
import shutil
import socket
from typing import Any
from urllib.parse import urlencode


CONTAINER_ID = re.compile(r"^[a-f0-9]{12,64}$")
MAX_RESPONSE = 2_000_000
MAX_LOG_BYTES = 524_288


class DockerError(RuntimeError):
    pass


class _UnixConnection(http.client.HTTPConnection):
    def __init__(self, socket_path: str, *, timeout: float = 4):
        # Read-only inventory stays on a short timeout; constrained lab
        # STOP needs a longer bounded timeout for Docker's graceful shutdown.
        super().__init__("localhost", timeout=timeout)
        self.socket_path = socket_path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.socket_path)


def choose_docker_socket() -> str:
    """Use a local Unix socket only (never Docker's TCP daemon endpoint)."""
    override = os.environ.get("DOCKER_SOCKET_PATH", "").strip()
    if override:
        if not os.path.isabs(override) or "://" in override:
            raise ValueError("DOCKER_SOCKET_PATH must be an absolute Unix socket path")
        return override
    # Docker Desktop on macOS may not create /var/run/docker.sock.
    candidates = ("/var/run/docker.sock", os.path.expanduser("~/.docker/run/docker.sock"))
    return next((path for path in candidates if os.path.exists(path)), candidates[0])


class DockerReader:
    def __init__(self, socket_path: str | None = None):
        self.socket_path = socket_path if socket_path is not None else choose_docker_socket()

    def _get(self, path: str, max_bytes: int = MAX_RESPONSE) -> tuple[bytes, str]:
        conn = _UnixConnection(self.socket_path)
        try:
            conn.request("GET", path, headers={"Accept": "application/json"})
            response = conn.getresponse()
            body = response.read(max_bytes + 1)
            if len(body) > max_bytes:
                raise DockerError("Docker response exceeded configured size limit")
            if not (200 <= response.status < 300):
                raise DockerError(f"Docker Engine returned HTTP {response.status}")
            return body, response.getheader("content-type", "")
        except (OSError, TimeoutError, http.client.HTTPException) as exc:
            raise DockerError("Docker Engine is not reachable by the local agent") from exc
        finally:
            conn.close()

    def _json(self, path: str) -> Any:
        data, _ = self._get(path)
        try:
            return json.loads(data)
        except (ValueError, UnicodeDecodeError) as exc:
            raise DockerError("Docker Engine returned invalid JSON") from exc

    def overview(self) -> dict:
        info = self._json("/info")
        disk = shutil.disk_usage("/")
        return {
            "hostname": str(info.get("Name", "Unknown"))[:128],
            "docker_version": str(info.get("ServerVersion", "Unknown"))[:32],
            "os": str(info.get("OperatingSystem", "Unknown"))[:128],
            "cpus": info.get("NCPU", 0),
            "memory_bytes": info.get("MemTotal", 0),
            "containers_total": info.get("Containers", 0),
            "containers_running": info.get("ContainersRunning", 0),
            "images_total": info.get("Images", 0),
            "disk_total_bytes": disk.total,
            "disk_used_bytes": disk.used,
            "disk_free_bytes": disk.free,
            "source": "live",
        }

    def containers(self) -> list[dict]:
        rows = self._json("/containers/json?all=1")
        return [{
            "id": str(row.get("Id", "")),
            "name": str((row.get("Names") or ["unknown"])[0]).lstrip("/")[:150],
            "image": str(row.get("Image", "unknown"))[:256],
            "state": str(row.get("State", "unknown"))[:32],
            "status": str(row.get("Status", "unknown"))[:128],
            "created": row.get("Created"),
            "ports": [
                {"private": p.get("PrivatePort"), "public": p.get("PublicPort"),
                 "type": p.get("Type")}
                for p in (row.get("Ports") or [])[:20]
            ],
        } for row in rows[:2000]]

    def images(self) -> list[dict]:
        rows = self._json("/images/json")
        return [{
            "id": str(item.get("Id", ""))[:80],
            "tags": [str(t)[:180] for t in (item.get("RepoTags") or [])[:12]],
            "size_bytes": item.get("Size", 0),
            "created": item.get("Created"),
        } for item in rows[:1000]]

    def networks(self) -> list[dict]:
        rows = self._json("/networks")
        return [{
            "id": str(item.get("Id", ""))[:80],
            "name": str(item.get("Name", ""))[:160],
            "driver": str(item.get("Driver", ""))[:64],
            "scope": str(item.get("Scope", ""))[:32],
        } for item in rows[:1000]]

    def volumes(self) -> list[dict]:
        rows = self._json("/volumes").get("Volumes") or []
        # Deliberately DO NOT expose mountpoints, labels, or options.
        return [{
            "name": str(item.get("Name", ""))[:200],
            "driver": str(item.get("Driver", ""))[:64],
            "scope": str(item.get("Scope", ""))[:32],
        } for item in rows[:1000]]

    def logs(self, container_id: str, tail: int) -> str:
        if not CONTAINER_ID.fullmatch(container_id):
            raise ValueError("Container ID must be 12-64 lowercase hex characters")
        if not (1 <= tail <= 200):
            raise ValueError("tail must be between 1 and 200")
        query = urlencode({"stdout": "1", "stderr": "1", "tail": str(tail), "timestamps": "1"})
        data, _ = self._get(f"/containers/{container_id}/logs?{query}", MAX_LOG_BYTES)
        # Non-TTY containers are often Docker stdcopy frames: 8-byte header,
        # payload length big endian; TTY containers return plain bytes.
        if len(data) >= 8 and data[0] in (1, 2) and data[1:4] == b"\x00\x00\x00":
            chunks = []
            pos = 0
            while pos + 8 <= len(data):
                if data[pos] not in (1, 2) or data[pos + 1:pos + 4] != b"\x00\x00\x00":
                    break
                size = int.from_bytes(data[pos + 4:pos + 8], "big")
                pos += 8
                if size > len(data) - pos:
                    raise DockerError("Truncated Docker log frame")
                chunks.append(data[pos:pos + size])
                pos += size
            data = b"".join(chunks)
        return data.decode("utf-8", errors="replace")
