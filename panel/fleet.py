"""Owner-scoped fleet health summary from verified agent-owned SQLite records.

No remote host connections, Docker commands, subprocesses or background jobs.
Signed identity freshness is distinct from signed host report freshness.
"""
from __future__ import annotations

import json
import time

from panel.registry import Registry


def status_for(status: str, seen: int | None, now: int) -> str:
    if status == "revoked":
        return "revoked"
    if status != "paired":
        return "unpaired"
    if seen is None:
        return "never_seen"
    return "recent" if 0 <= now - seen <= 180 else "stale"


class FleetStore:
    def __init__(self, db_path: str):
        self.registry = Registry(db_path)

    def summary(self, owner: str) -> dict:
        now = int(time.time())
        with self.registry.connect() as db:
            rows = db.execute("""
                SELECT s.id, s.name, s.status, s.created_at,
                       a.fingerprint, a.last_seen,
                       h.recorded_at, h.snapshot_json
                  FROM servers s
             LEFT JOIN agent_identities a ON a.server_id=s.id
             LEFT JOIN host_snapshots h ON h.server_id=s.id
                 WHERE s.owner=?
              ORDER BY s.name COLLATE NOCASE, s.id
                 LIMIT 501
            """, (owner,)).fetchall()
        # Prevent runaway responses as the pilot grows; all statements below
        # refer to the bounded page, not to a fabricated global count.
        truncated = len(rows) > 500
        rows = rows[:500]
        items = []
        for row in rows:
            status = row["status"]
            heartbeat = status_for(status, row["last_seen"], now)
            report = status_for(status, row["recorded_at"], now)
            if report == "unpaired" and status == "revoked":
                report = "revoked"
            health = None
            if status == "paired" and row["snapshot_json"] is not None:
                # Every stored snapshot was validated on the signed ingestion
                # path; do not return its raw JSON or any unexpected fields.
                snapshot = json.loads(row["snapshot_json"])
                total = snapshot["disk_total_bytes"]
                free = snapshot["disk_free_bytes"]
                health = {
                    "hostname": snapshot["hostname"],
                    "cpu_count": snapshot["cpu_count"],
                    "memory_total_bytes": snapshot["memory_total_bytes"],
                    "disk_free_percent": round(100 * free / total, 1),
                }
            warnings = []
            if status == "paired":
                if heartbeat == "stale":
                    warnings.append({
                        "code": "heartbeat_stale", "severity": "warning",
                        "message": "No recent signed heartbeat"
                    })
                if report == "stale":
                    warnings.append({
                        "code": "host_report_stale", "severity": "warning",
                        "message": "Last signed host report is stale"
                    })
                if health is not None:
                    pct = health["disk_free_percent"]
                    if pct < 10:
                        warnings.append({
                            "code": "disk_low", "severity": "critical",
                            "message": "Last signed disk report below 10% free"
                        })
                    elif pct < 20:
                        warnings.append({
                            "code": "disk_low", "severity": "warning",
                            "message": "Last signed disk report below 20% free"
                        })
            items.append({
                "id": row["id"], "name": row["name"], "status": status,
                "created_at": row["created_at"],
                "heartbeat_state": heartbeat,
                "last_heartbeat": row["last_seen"] if status == "paired" else None,
                "report_state": report,
                "last_report": row["recorded_at"] if status == "paired" else None,
                "health": health,
                "warnings": warnings,
            })
        counts = {state: sum(item["status"] == state for item in items)
                  for state in ("unpaired", "paired", "revoked")}
        counts["heartbeat_recent"] = sum(item["heartbeat_state"] == "recent" for item in items)
        counts["heartbeat_stale"] = sum(item["heartbeat_state"] == "stale" for item in items)
        counts["report_recent"] = sum(item["report_state"] == "recent" for item in items)
        counts["warning_servers"] = sum(bool(item["warnings"]) for item in items)
        counts["critical_servers"] = sum(
            any(w["severity"] == "critical" for w in item["warnings"])
            for item in items
        )
        return {"servers": items, "counts": counts, "truncated": truncated,
                "fleet_scope": "owner", "remote_docker_access": False}
