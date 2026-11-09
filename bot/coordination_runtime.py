"""Paper-only coordination reporting from observed runner evidence.

Never invent Scout WATCH or Analyst APPROVE. Existing skip reasons are
real observations, not simulated agreement or permission to execute.
"""
from agent_coordination import coordinate
from agent_suite import AgentEvent


def coordination_from_runtime(state, now):
    if not isinstance(state, dict):
        return {"paper_only": True, "status": "unavailable", "decisions": []}
    items = state.get("kills_live")
    if not isinstance(items, list):
        return {"paper_only": True, "status": "no_skip_evidence", "decisions": []}
    decisions = []
    seen = set()
    for item in reversed(items[-30:]):
        if not isinstance(item, dict):
            continue
        token = str(item.get("mint") or item.get("sym") or "").strip()[:48]
        reason = str(item.get("reason") or item.get("why") or "filtered")[:160]
        if not token or token in seen:
            continue
        seen.add(token)
        veto = AgentEvent("Risk", token, "SKIP", reason, now)
        result = coordinate(token, [veto], equity=1)
        decisions.append({"token": token, "action": result.action,
                          "reason": reason, "paper_only": True,
                          "source": "kills_live", "agent": "Risk"})
        if len(decisions) >= 12:
            break
    return {"paper_only": True, "status": "observed_skips_only",
            "decisions": decisions}
