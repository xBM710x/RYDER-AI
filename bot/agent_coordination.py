"""Deterministic paper-only coordination of verified agent observations.

This is an advisory decision engine. It does not place or mutate trades.
"""
from dataclasses import dataclass
import math
from agent_suite import AgentEvent, RiskPolicy, validate_policy


@dataclass(frozen=True)
class CoordinationDecision:
    token: str
    action: str
    reason: str
    evidence: tuple
    paper_only: bool = True


def coordinate(token, observations, *, equity, position_value=0,
               total_exposure=0, policy=RiskPolicy()):
    """Fail closed: require current positive verified scout/analyst evidence.

    Observations: AgentEvent objects for the same token. A Risk SKIP,
    PAPER_EXIT, or BLOCK_NEW_ENTRY vetoes new paper entries.
    """
    validate_policy(policy)
    if not isinstance(token, str) or not token.strip():
        return CoordinationDecision("", "SKIP", "invalid token", ())
    nums = (equity, position_value, total_exposure)
    if any(isinstance(x, bool) or not isinstance(x, (int, float))
           or not math.isfinite(x) for x in nums) or equity <= 0 or min(position_value, total_exposure) < 0:
        return CoordinationDecision(token, "SKIP", "invalid account evidence", ())
    if not isinstance(observations, (list, tuple)):
        return CoordinationDecision(token, "SKIP", "missing agent evidence", ())
    events = [e for e in observations if isinstance(e, AgentEvent) and e.paper_only
              and e.token == token and isinstance(e.timestamp, (int, float))
              and math.isfinite(e.timestamp)]
    evidence = tuple(sorted({e.agent + ":" + e.action for e in events}))
    if any(e.action in ("SKIP", "BLOCK_NEW_ENTRY", "PAPER_EXIT") for e in events):
        return CoordinationDecision(token, "SKIP", "agent risk veto", evidence)
    if position_value > equity * policy.max_position_fraction:
        return CoordinationDecision(token, "SKIP", "position cap", evidence)
    if total_exposure > equity * policy.max_total_exposure_fraction:
        return CoordinationDecision(token, "SKIP", "total exposure cap", evidence)
    if not any(e.agent == "Scout" and e.action == "WATCH" for e in events):
        return CoordinationDecision(token, "WATCH", "awaiting scout confirmation", evidence)
    if not any(e.agent == "Analyst" and e.action == "APPROVE" for e in events):
        return CoordinationDecision(token, "WATCH", "awaiting analyst approval", evidence)
    return CoordinationDecision(token, "PAPER_ENTRY_ELIGIBLE",
                                "scout and analyst agree; execution remains disabled", evidence)
