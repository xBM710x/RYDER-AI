"""Sanitize paper-only specialist heartbeat before public dashboard export."""
import math


def sanitize_heartbeat_agents(heartbeat, *, now, max_age=120):
    empty = {"paper_only": True, "status": "unavailable", "agents": [], "activity": []}
    if not isinstance(heartbeat, dict) or not isinstance(now, (int, float)) or not math.isfinite(now):
        return empty
    ts = heartbeat.get("ts")
    if isinstance(ts, bool) or not isinstance(ts, (int, float)) or not math.isfinite(ts):
        return dict(empty, status="heartbeat_missing")
    if ts > now or now - ts > max_age:
        return dict(empty, status="heartbeat_stale")
    source = heartbeat.get("specialist_agents")
    if not isinstance(source, dict) or source.get("paper_only") is not True:
        return dict(empty, status="agent_data_missing")
    agents = []
    for item in source.get("agents", [])[:16]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "")[:40]
        status = str(item.get("status") or "unknown")[:32]
        if not name:
            continue
        agents.append({"name": name, "status": status,
                       "detail": str(item.get("detail") or "")[:120],
                       "evidence": item.get("evidence") is True})
    activity = []
    for item in source.get("activity", [])[-20:]:
        if not isinstance(item, dict) or item.get("paper_only") is not True:
            continue
        activity.append({"agent": str(item.get("agent") or "")[:40],
                         "token": str(item.get("token") or "")[:30],
                         "decision": str(item.get("decision") or "")[:32],
                         "reason": str(item.get("reason") or "")[:180],
                         "paper_only": True})
    return {"paper_only": True, "status": "read_only_observation",
            "agents": agents, "activity": activity}
