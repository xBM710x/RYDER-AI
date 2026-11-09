"""RYDER specialist-agent suite: deterministic paper-only research and risk.

This module never connects to wallets, posts to X, places orders, or claims
that external sources are connected. Inputs must be verified upstream.
"""
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class AgentEvent:
    agent: str
    token: str
    action: str
    reason: str
    timestamp: float
    paper_only: bool = True


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def x_scout(mentions, *, now, max_age=300, min_unique_authors=3):
    """Summarize verified social mentions; never fabricate X access."""
    valid = [m for m in mentions if isinstance(m, dict)
             and isinstance(m.get("token"), str) and m["token"]
             and isinstance(m.get("author"), str) and m["author"]
             and _finite(m.get("timestamp"))
             and 0 <= now - m["timestamp"] <= max_age
             and m.get("verified_source") is True]
    tokens = sorted({m["token"] for m in valid})
    events = []
    for token in tokens:
        authors = {m["author"] for m in valid if m["token"] == token}
        if len(authors) >= min_unique_authors:
            events.append(AgentEvent("X Scout", token, "WATCH",
                                     f"{len(authors)} distinct verified-source authors; research only", now))
    return events


@dataclass(frozen=True)
class RiskPolicy:
    max_position_fraction: float = 0.10
    max_total_exposure_fraction: float = 0.30
    trailing_stop_fraction: float = 0.08
    partial_exit_gain_fraction: float = 0.15
    partial_exit_fraction: float = 0.50
    reinvest_profit_fraction: float = 0.40


def validate_policy(p):
    values = (p.max_position_fraction, p.max_total_exposure_fraction,
              p.trailing_stop_fraction, p.partial_exit_gain_fraction,
              p.partial_exit_fraction, p.reinvest_profit_fraction)
    if not all(_finite(x) for x in values):
        raise ValueError("non-finite risk policy")
    if not (0 < p.max_position_fraction <= p.max_total_exposure_fraction <= 1):
        raise ValueError("invalid position/exposure cap")
    if not (0 < p.trailing_stop_fraction < 1 and p.partial_exit_gain_fraction > 0
            and 0 < p.partial_exit_fraction <= 1 and 0 <= p.reinvest_profit_fraction <= 1):
        raise ValueError("invalid exit/compounding policy")
    return p


def paper_budget(initial_budget, realized_net_profit, policy=RiskPolicy()):
    """Only positive *realized net* profit contributes to reinvestment."""
    validate_policy(policy)
    if not _finite(initial_budget) or initial_budget < 0:
        raise ValueError("invalid initial budget")
    if not _finite(realized_net_profit):
        raise ValueError("invalid realized profit")
    retained = max(realized_net_profit, 0) * (1 - policy.reinvest_profit_fraction)
    reinvested = max(realized_net_profit, 0) * policy.reinvest_profit_fraction
    return {"paper_budget": max(0, initial_budget + realized_net_profit -
                                 retained), "retained_paper_profit": retained,
            "reinvested_paper_profit": reinvested, "paper_only": True}


def evaluate_position(*, token, entry, peak, current, position_value,
                      equity, total_exposure, now, policy=RiskPolicy(),
                      partial_already_taken=False):
    """Return a paper exit instruction, never an order."""
    validate_policy(policy)
    vals = (entry, peak, current, position_value, equity, total_exposure, now)
    if not token or not all(_finite(v) for v in vals) or min(entry, peak, current, equity) <= 0:
        return AgentEvent("Risk", token or "", "SKIP", "missing or invalid price/equity", now)
    if position_value < 0 or total_exposure < 0 or peak < entry or current > peak:
        return AgentEvent("Risk", token, "SKIP", "inconsistent position state", now)
    if current <= peak * (1 - policy.trailing_stop_fraction):
        return AgentEvent("Risk", token, "PAPER_EXIT", "trailing stop triggered", now)
    if not partial_already_taken and current >= entry * (1 + policy.partial_exit_gain_fraction):
        return AgentEvent("Risk", token, "PAPER_PARTIAL_EXIT",
                          f"profit threshold; fraction {policy.partial_exit_fraction:.2f}", now)
    if position_value > equity * policy.max_position_fraction:
        return AgentEvent("Risk", token, "BLOCK_NEW_ENTRY", "position cap exceeded", now)
    if total_exposure > equity * policy.max_total_exposure_fraction:
        return AgentEvent("Risk", token, "BLOCK_NEW_ENTRY", "total exposure cap exceeded", now)
    return AgentEvent("Risk", token, "PAPER_HOLD", "risk conditions monitored", now)


def notification_payload(event):
    """Structured message for optional external notification adapter."""
    if not isinstance(event, AgentEvent) or not event.paper_only:
        raise ValueError("paper events only")
    return {"title": f"RYDER PAPER {event.action}", "agent": event.agent,
            "token": event.token, "reason": event.reason,
            "timestamp": event.timestamp, "paper_only": True}
