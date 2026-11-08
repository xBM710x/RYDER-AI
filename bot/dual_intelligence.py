"""RYDER dual-intelligence decision layer (paper-only).

Consumes normalized observations from separately configured data providers.
No network requests, wallet access, signing, or real trade execution.
"""
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Signal:
    source: str  # "copy" or "independent"
    token: str
    action: str  # BUY, HOLD, SELL, SKIP
    confidence: float
    liquidity_usd: Optional[float]
    observed_at: float
    wallet: str = ""
    reason: str = ""


@dataclass(frozen=True)
class Decision:
    token: str
    action: str
    confidence: float
    reason: str
    paper_only: bool = True


def decide(signals, now, *, max_age_seconds=90, min_liquidity_usd=25000,
           min_confidence=0.65):
    """Deterministic, fail-closed reconciliation of copy and independent signals.

    Signals must be normalized and timestamped upstream. Any conflicting
    eligible BUY/SELL directions result in SKIP. A single eligible BUY is
    permitted as a paper signal; real execution is intentionally absent.
    """
    if not signals:
        return Decision("", "SKIP", 0.0, "no_signals")
    token = signals[0].token
    if not token or any(s.token != token for s in signals):
        return Decision(token, "SKIP", 0.0, "mixed_or_missing_token")
    eligible = []
    rejected = []
    for s in signals:
        if s.source not in ("copy", "independent") or s.action not in (
                "BUY", "HOLD", "SELL", "SKIP"):
            rejected.append("invalid_signal")
        elif not 0 <= s.confidence <= 1:
            rejected.append("invalid_confidence")
        elif s.observed_at > now or now - s.observed_at > max_age_seconds:
            rejected.append("stale_signal")
        elif s.liquidity_usd is None or s.liquidity_usd < min_liquidity_usd:
            rejected.append("insufficient_or_unknown_liquidity")
        elif s.confidence < min_confidence:
            rejected.append("low_confidence")
        else:
            eligible.append(s)
    if not eligible:
        return Decision(token, "SKIP", 0.0,
                        ",".join(sorted(set(rejected))) or "no_eligible_signals")
    directions = {s.action for s in eligible if s.action in ("BUY", "SELL")}
    if len(directions) > 1:
        return Decision(token, "SKIP", 0.0, "copy_independent_conflict")
    if not directions:
        return Decision(token, "HOLD", max(s.confidence for s in eligible),
                        "no_entry_or_exit_signal")
    action = next(iter(directions))
    matching = [s for s in eligible if s.action == action]
    return Decision(token, action, sum(s.confidence for s in matching) / len(matching),
                    "paper_signal:" + ",".join(sorted({s.source for s in matching})))
