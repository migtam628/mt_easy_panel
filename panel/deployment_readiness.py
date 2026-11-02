"""Read-only deployment readiness from owner-scoped, validated draft metadata.

This is *not* a deployment planner/executor. It never sends jobs, reads
Docker, parses Compose, reads environment secrets or modifies a host.
"""
from __future__ import annotations

import json
from panel.registry import Registry


class DeploymentReadiness:
    def __init__(self, db_path: str):
        self.registry = Registry(db_path)

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
                if not isinstance(image, str) or len(image) > 260:
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
