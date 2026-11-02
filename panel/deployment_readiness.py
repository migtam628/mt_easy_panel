"""Read-only deployment readiness from owner-scoped, validated draft metadata.

This is *not* a deployment planner/executor. It never sends jobs, reads
Docker, parses Compose, reads environment secrets or modifies a host.
"""
from __future__ import annotations

import json
from panel.registry import Registry, RegistryError
from panel.manifests import ServiceDraft
from pydantic import ValidationError


class DeploymentReadiness:
    def __init__(self, db_path: str):
        self.registry = Registry(db_path)

    def review(self, owner: str, draft_id: str) -> dict:
        """Explain whether an owner-owned draft satisfies *static* policy.

        This is NOT a permission to deploy, reserve a port or run Docker.
        Identity pairing cannot establish remote host capacity or authority.
        """
        with self.registry.connect() as db:
            row = db.execute("""
                SELECT d.name, d.slug, d.manifest_json, e.name AS environment,
                       p.name AS project, p.server_id, s.name AS server_name,
                       s.status AS server_status
                  FROM service_drafts d
                  JOIN environments e ON e.id=d.environment_id
                  JOIN projects p ON p.id=e.project_id
             LEFT JOIN servers s ON s.id=p.server_id AND s.owner=p.owner
                 WHERE p.owner=? AND d.id=?
            """, (owner, draft_id)).fetchone()
        if row is None:
            raise RegistryError("Draft not found", 404)
        checks = []
        def check(code: str, passed: bool, explanation: str) -> None:
            checks.append({"code": code, "passed": passed, "explanation": explanation})

        try:
            manifest = ServiceDraft.model_validate_json(row["manifest_json"])
            valid = True
        except (ValidationError, ValueError, TypeError):
            manifest = None
            valid = False
        check("safe_manifest", valid,
              "Strict schema, immutable image digest and read-only root filesystem")
        check("server_assigned", row["server_id"] is not None,
              "An intended server record must be assigned")
        check("identity_paired",
              row["server_id"] is not None and row["server_status"] == "paired",
              "Saved server identity must be paired; pairing is NOT Docker authorization")
        check("remote_host_verified", False,
              "An independent disposable-host security validation is required")
        check("execution_gate", False,
              "Production job runner and write authorization are not implemented")

        safe_manifest = None
        if manifest is not None:
            safe_manifest = {
                "image": manifest.image,
                "container_port": manifest.container_port,
                "cpu_limit": manifest.cpu_limit,
                "memory_mb": manifest.memory_mb,
                "read_only_rootfs": manifest.read_only_rootfs,
            }
        return {
            "draft_id": draft_id, "draft": row["name"], "project": row["project"],
            "environment": row["environment"], "server": row["server_name"],
            "manifest": safe_manifest,
            "checks": checks, "passed_static_checks": sum(
                1 for item in checks[:3] if item["passed"]),
            "total_static_checks": 3,
            "executable": False, "execution_enabled": False,
            "remote_docker_access": False,
        }

    def list_drafts(self, owner: str) -> dict:
        with self.registry.connect() as db:
            rows = db.execute("""
                SELECT d.id, d.name, d.slug, d.created_at, d.manifest_json,
                       e.name AS environment, p.name AS project,
                       p.server_id, s.name AS server_name, s.status AS server_status
                  FROM service_drafts d
                  JOIN environments e ON e.id=d.environment_id
                  JOIN projects p ON p.id=e.project_id
             LEFT JOIN servers s ON s.id=p.server_id AND s.owner=p.owner
                 WHERE p.owner=?
              ORDER BY d.created_at DESC, d.id DESC
                 LIMIT 201
            """, (owner,)).fetchall()
        truncated = len(rows) > 200
        entries = []
        for row in rows[:200]:
            # Only show the public pinned image reference; never expose full
            # draft JSON or future potentially sensitive manifest extensions.
            try:
                manifest = json.loads(row["manifest_json"])
                image = manifest.get("image") if isinstance(manifest, dict) else None
                if not isinstance(image, str) or len(image) > 320:
                    image = None
            except (ValueError, TypeError):
                image = None
            blockers = ["execution_not_implemented"]
            if not row["server_id"]:
                blockers.append("server_not_assigned")
            elif row["server_status"] != "paired":
                blockers.append("server_identity_not_paired")
            # Even a paired identity gives NO remote Docker authorization.
            entries.append({
                "id": row["id"], "name": row["name"], "slug": row["slug"],
                "project": row["project"], "environment": row["environment"],
                "server_name": row["server_name"] if row["server_id"] else None,
                "server_status": row["server_status"] if row["server_id"] else None,
                "image": image, "created_at": row["created_at"],
                "status": "draft_only", "executable": False, "blockers": blockers,
            })
        return {
            "drafts": entries, "total_returned": len(entries),
            "truncated": truncated, "execution_enabled": False,
            "docker_writes_enabled": False, "jobs_created": False,
            "note": "Configuration drafts only; nothing has been deployed.",
        }
