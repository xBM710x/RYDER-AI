"""RYDER read-only dual-intelligence telemetry bridge.

Writes compact paper-signal summaries for the existing dashboard data pipeline.
Does not open positions, call FOMO, place orders, or modify risk filters.
"""
import json
import math
from pathlib import Path

from copy_intelligence import PaperSignalDesk, WalletEvent
from dual_intelligence import Signal


def signal_from_scanner(mint, action, confidence, liquidity_usd, timestamp, reason=""):
    """Convert a scanner verdict to the normalized independent signal format."""
    if not mint or action not in ("BUY", "SELL", "HOLD", "SKIP"):
        return None
    try:
        values = (float(confidence), float(liquidity_usd), float(timestamp))
        if not all(math.isfinite(v) for v in values):
            return None
    except (TypeError, ValueError, OverflowError):
        return None
    return Signal("independent", mint, action, values[0], values[1], values[2],
                  reason=reason)


def summarize(desk, *, limit=20):
    """Expose safe, serializable telemetry; no wallet secrets or account keys."""
    if not isinstance(desk, PaperSignalDesk):
        raise TypeError("expected PaperSignalDesk")
    rows = desk.history[-max(0, min(int(limit), 100)):]
    return dict(mode="paper", source="dual_intelligence", count=len(desk.history),
                decisions=[dict(mint=r["mint"], decision=r["decision"],
                                reason=r["reason"], observed_at=r["observed_at"],
                                paper_only=True) for r in rows])


def write_snapshot(desk, path):
    """Atomic local export; caller chooses a data directory outside source control."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(target.name + ".tmp")
    temp.write_text(json.dumps(summarize(desk), separators=(",", ":")), encoding="utf-8")
    temp.replace(target)
    return target
