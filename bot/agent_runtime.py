"""Read-only bridge between existing RYDER runtime and specialist agent desk.

Only reports evidence actually present in runner state. No new trade placement,
wallet interaction, fabricated FOMO/X feeds or side effects.
"""
import time
from agent_suite import RiskPolicy, validate_policy


def runtime_agents(state, now=None):
    """Derive statuses from the existing runner heartbeat without claiming live X."""
    now = time.time() if now is None else now
    if not isinstance(state, dict):
        return {"paper_only": True, "agents": [], "activity": [], "status": "unavailable"}
    agents = [
        {"name": "Scout", "status": "observed", "detail": "scanner telemetry",
         "evidence": "scan_scheduler" in state},
        {"name": "Analyst", "status": "observed", "detail": "council decisions",
         "evidence": "council" in state},
        {"name": "Risk", "status": "observed", "detail": "existing risk engine",
         "evidence": "risk" in state},
        {"name": "Copy", "status": "observed", "detail": "existing copy-trade monitor",
         "evidence": "b16" in state},
        {"name": "X Scout", "status": "not_connected", "detail": "verified X feed required",
         "evidence": False},
        {"name": "Compounding", "status": "advisory_only", "detail": "no budget mutation",
         "evidence": False},
        {"name": "Notifications", "status": "not_connected", "detail": "transport not configured",
         "evidence": False},
    ]
    activity = []
    for item in state.get("kills_live", [])[-12:]:
        if isinstance(item, dict):
            token = str(item.get("sym") or item.get("mint") or "")[:24]
            reason = str(item.get("reason") or item.get("why") or "filtered")[:160]
            activity.append({"agent": "Risk", "token": token, "decision": "SKIP",
                             "reason": reason, "paper_only": True})
    return {"paper_only": True, "asof": now, "agents": agents, "activity": activity,
            "status": "read_only_observation", "source": "runner_heartbeat"}


def policy_status(policy=RiskPolicy()):
    validate_policy(policy)
    return {"paper_only": True, "mode": "advisory_only",
            "trailing_stop_fraction": policy.trailing_stop_fraction,
            "partial_exit_gain_fraction": policy.partial_exit_gain_fraction,
            "reinvest_profit_fraction": policy.reinvest_profit_fraction,
            "active_order_routing": False}
