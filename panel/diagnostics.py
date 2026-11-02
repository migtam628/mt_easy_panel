"""Safe, on-demand diagnostics derived from existing read-only Docker inventory.

No socket access, container inspect, logs, DB writes, or host mutation.
Docker's 'Status' text is observational and not a health-check guarantee.
"""
from __future__ import annotations

from collections import Counter

STATE_ORDER = ("running", "restarting", "paused", "exited", "dead", "created", "removing")
MAX_ITEMS = 2000


def summarize_containers(raw: object) -> dict:
    if not isinstance(raw, list):
        raise ValueError("Container inventory must be a list")
    rows = raw[:MAX_ITEMS]
    counts: Counter[str] = Counter()
    items = []
    warnings = {"unhealthy": 0, "restarting": 0, "dead": 0}
    for item in rows:
        if not isinstance(item, dict):
            continue
        state = str(item.get("state") or "unknown").lower()[:32]
        status = str(item.get("status") or "unknown")[:128]
        name = str(item.get("name") or "unnamed")[:150]
        counts[state] += 1
        health = "not_reported"
        flags = []
        if "(unhealthy)" in status.lower():
            health = "unhealthy"
            flags.append("reported_unhealthy")
            warnings["unhealthy"] += 1
        elif "(healthy)" in status.lower():
            health = "reported_healthy"
        if state == "restarting":
            flags.append("restarting")
            warnings["restarting"] += 1
        elif state == "dead":
            flags.append("dead")
            warnings["dead"] += 1
        items.append({
            "name": name, "state": state, "status": status,
            "health": health, "flags": flags,
        })
    # Flagged containers first so the on-demand diagnostics page is useful
    # without implying exit status alone is an operational incident.
    items.sort(key=lambda x: (not bool(x["flags"]), x["name"].casefold()))
    return {
        "sampled": len(items), "truncated": len(raw) > MAX_ITEMS,
        "states": dict(counts), "warnings": warnings,
        "containers": items,
        "source": "local_read_only_docker_inventory",
        "docker_writes_enabled": False,
    }


def host_capacity(overview: object) -> dict | None:
    if not isinstance(overview, dict):
        return None
    total = overview.get("disk_total_bytes")
    free = overview.get("disk_free_bytes")
    if (not isinstance(total, int) or isinstance(total, bool) or total <= 0
            or not isinstance(free, int) or isinstance(free, bool)
            or free < 0 or free > total):
        return {"disk_free_percent": None, "disk_warning": "not_reported"}
    percent = round(free * 100.0 / total, 1)
    warning = "critical" if percent < 10 else "warning" if percent < 20 else "none"
    return {"disk_free_percent": percent, "disk_warning": warning}
