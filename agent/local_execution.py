"""Lab-only, tightly allowlisted Docker *write* adapter for MT Panel-owned candidates.

This module is not an arbitrary Docker API proxy. No host ports, networks,
mounts, secrets, environment, capabilities, exec, image pulls or deletion.
Writes must be separately opted-in at the agent and authorized by panel jobs.
"""
from __future__ import annotations

import http.client
import json
import re
import time
from urllib.parse import quote, urlencode

from agent.docker import _UnixConnection, DockerError
from panel.manifests import DIGEST, ServiceDraft

HEX = re.compile(r"^[0-9a-f]{32}$")
LABEL = "io.mtpanel.lab.managed"
MAX_REPLY = 65536


class ActionDenied(ValueError):
    pass


class LocalDockerWriter:
    def __init__(self, socket_path: str, *, poll_delay: float = 1.0, checks: int = 10):
        self.socket_path = socket_path
        self.poll_delay = poll_delay
        self.checks = checks

    def _call(self, method: str, path: str, body: dict | None = None,
              *, missing: bool = False) -> dict | None:
        # Paths are generated exclusively in this class using 32-hex IDs and
        # already schema-validated pinned images. Never take a path from HTTP.
        timeout = 20 if method == "POST" and path.endswith("/stop") else 4
        conn = _UnixConnection(self.socket_path, timeout=timeout)
        raw = json.dumps(body, separators=(",", ":")).encode() if body is not None else None
        try:
            conn.request(method, path, body=raw, headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            })
            response = conn.getresponse()
            data = response.read(MAX_REPLY + 1)
            if len(data) > MAX_REPLY:
                raise DockerError("Docker response too large")
            if response.status == 404 and missing:
                return None
            if not 200 <= response.status < 300:
                raise DockerError("Docker refused an allowlisted local action")
            if not data:
                return {}
            try:
                result = json.loads(data)
                if not isinstance(result, dict):
                    raise ValueError("Not a JSON object")
                return result
            except (ValueError, UnicodeDecodeError) as exc:
                raise DockerError("Invalid Docker response") from exc
        except (OSError, TimeoutError, http.client.HTTPException) as exc:
            raise DockerError("Local Docker Engine unavailable") from exc
        finally:
            conn.close()

    @staticmethod
    def _name(job_id: str) -> str:
        if not HEX.fullmatch(job_id):
            raise ActionDenied("Invalid managed job identifier")
        return "mtpanel-lab-" + job_id

    def inspect(self, job_id: str) -> dict | None:
        name = self._name(job_id)
        return self._call("GET", "/containers/" + name + "/json", missing=True)

    def candidate_status(self, job_id: str, draft_id: str, expected_image: str) -> dict:
        """Read-only, sanitized observation of one exact lab-owned candidate.

        A missing container is NOT proof of rollback or safe retry. A
        same-name container with wrong ownership is always denied.
        """
        if not HEX.fullmatch(draft_id) or not DIGEST.fullmatch(expected_image):
            raise ActionDenied("Invalid lab candidate verification parameters")
        item = self.inspect(job_id)
        if item is None:
            return {"observation": "absent", "present": False,
                    "safe_to_retry": False, "traffic_switched": False}
        self._ownership(item, job_id, draft_id)
        if item.get("Config", {}).get("Image") != expected_image:
            raise ActionDenied("Candidate image does not match immutable job manifest")
        state = item.get("State")
        if not isinstance(state, dict):
            raise DockerError("Managed candidate state unavailable")
        running = state.get("Running")
        if not isinstance(running, bool):
            raise DockerError("Managed candidate running state unavailable")
        health = state.get("Health") or {}
        if not isinstance(health, dict):
            raise DockerError("Managed candidate health unavailable")
        reported = health.get("Status")
        if not running:
            status = "stopped"
        elif reported == "healthy":
            status = "running_healthy"
        elif reported == "unhealthy":
            status = "running_unhealthy"
        elif reported == "starting":
            status = "running_starting"
        else:
            status = "running_unknown"
        return {"observation": status, "present": True,
                "safe_to_retry": False, "traffic_switched": False}

    @staticmethod
    def _ownership(item: dict, job_id: str, draft_id: str) -> None:
        labels = item.get("Config", {}).get("Labels") or {}
        if (not isinstance(labels, dict) or labels.get(LABEL) != "v1"
                or labels.get("io.mtpanel.lab.job") != job_id
                or labels.get("io.mtpanel.lab.draft") != draft_id
                or item.get("Name") != "/mtpanel-lab-" + job_id):
            raise ActionDenied("Container is not owned by the exact MT Panel lab job")

    def _require_image_healthcheck(self, image: str) -> None:
        result = self._call("GET", "/images/" + quote(image, safe="") + "/json",
                            missing=True)
        if result is None:
            raise ActionDenied("Pinned image is not present locally; pulls are disabled")
        hc = (result.get("Config") or {}).get("Healthcheck")
        if not isinstance(hc, dict) or not hc.get("Test") or hc["Test"] == ["NONE"]:
            raise ActionDenied("Image must provide a baked-in Docker HEALTHCHECK")

    def create_candidate(self, job_id: str, draft_id: str, manifest: ServiceDraft) -> dict:
        name = self._name(job_id)
        if not HEX.fullmatch(draft_id):
            raise ActionDenied("Invalid deployment draft identifier")
        existing = self.inspect(job_id)
        if existing is not None:
            self._ownership(existing, job_id, draft_id)
            if existing.get("Config", {}).get("Image") != manifest.image:
                raise ActionDenied("Managed job image differs from authorized manifest")
            return {"container": name, "created": False}
        self._require_image_healthcheck(manifest.image)
        # Never create published ports or bind mounts; the candidate runs
        # disconnected and cannot claim production traffic on the host.
        config = {
            "Image": manifest.image,
            "User": "65534:65534",
            "Labels": {
                LABEL: "v1",
                "io.mtpanel.lab.job": job_id,
                "io.mtpanel.lab.draft": draft_id,
            },
            "ExposedPorts": {str(manifest.container_port) + "/tcp": {}},
            "HostConfig": {
                "NetworkMode": "none",
                "PublishAllPorts": False,
                "PortBindings": {},
                "Binds": [],
                "Mounts": [],
                "ReadonlyRootfs": True,
                "Privileged": False,
                "CapDrop": ["ALL"],
                "SecurityOpt": ["no-new-privileges:true"],
                "PidsLimit": 128,
                "Memory": manifest.memory_mb * 1024 * 1024,
                "NanoCpus": int(manifest.cpu_limit * 1_000_000_000),
                "AutoRemove": False,
            },
        }
        self._call("POST", "/containers/create?" + urlencode({"name": name}), config)
        verified = self.inspect(job_id)
        if not isinstance(verified, dict):
            raise DockerError("Created container missing after Docker acknowledgement")
        self._ownership(verified, job_id, draft_id)
        return {"container": name, "created": True}

    def lifecycle(self, job_id: str, draft_id: str, operation: str) -> dict:
        if operation not in {"start", "stop", "restart"}:
            raise ActionDenied("Unsupported managed-container operation")
        item = self.inspect(job_id)
        if item is None:
            raise ActionDenied("Managed lab container not found")
        self._ownership(item, job_id, draft_id)
        name = self._name(job_id)
        self._call("POST", "/containers/" + name + "/" + operation)
        return {"container": name, "operation": operation}

    def deploy(self, job_id: str, draft_id: str, manifest: ServiceDraft) -> dict:
        created = self.create_candidate(job_id, draft_id, manifest)
        current = self.inspect(job_id)
        self._ownership(current, job_id, draft_id)
        if not current.get("State", {}).get("Running"):
            self.lifecycle(job_id, draft_id, "start")
        for index in range(self.checks):
            current = self.inspect(job_id)
            self._ownership(current, job_id, draft_id)
            state = current.get("State") or {}
            health = (state.get("Health") or {}).get("Status")
            if state.get("Running") and health == "healthy":
                return {"status": "HEALTHY", "container": created["container"],
                        "traffic_switched": False}
            if not state.get("Running") or health == "unhealthy":
                break
            if index < self.checks - 1:
                time.sleep(self.poll_delay)
        # Failure only stops THIS new candidate; the previous healthy
        # container, any Caddy routes and all existing workloads are untouched.
        # A failed stop is explicitly escalated rather than claiming rollback.
        self.lifecycle(job_id, draft_id, "stop")
        # Docker may acknowledge a stop call before an external observer sees
        # it terminated. A successful rollback MUST be independently verified.
        # Missing or mismatched containers are ambiguous, never "rolled back".
        after_stop = self.inspect(job_id)
        if not isinstance(after_stop, dict):
            raise DockerError("Stopped candidate could not be verified")
        self._ownership(after_stop, job_id, draft_id)
        state = after_stop.get("State")
        if not isinstance(state, dict) or state.get("Running") is not False:
            raise DockerError("Candidate stop is unconfirmed; operator review required")
        return {"status": "ROLLED_BACK", "container": created["container"],
                "traffic_switched": False, "reason": "candidate_health_check_failed"}
