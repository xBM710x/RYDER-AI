"""Stage 5: Risk. Hard stop -8% set BEFORE entry; at +15% switch to trailing stop 8% below peak."""
from common import CFG
def initial_stop(entry): return entry * (1 - CFG["STOP_PCT"])
def update(pos, price, trail_pct=None, sell_spike=False):
    peak = max(pos["peak"], price); stop, trailing = pos["stop"], pos["trailing"]
    v3 = CFG["VERSION"] not in ("v1", "v2") and pos.get("version") not in ("v1", "v2")
    if price >= pos["entry"] * (1 + CFG["TRAIL_ACTIVATE"]): trailing = 1
    if trailing: stop = max(stop, peak * (1 - (trail_pct if v3 and trail_pct else CFG["TRAIL_PCT"])))  # 75 adaptive trail
    if v3 and peak >= pos["entry"] * 1.10: stop = max(stop, pos["entry"])  # 74 breakeven after +10%
    if v3 and sell_spike: stop = max(stop, price * 0.96)  # 73 tighten on sell-pressure spike
    out = dict(peak=peak, stop=stop, trailing=trailing, exit=price <= stop, partial=False, time_stop=False)
    if CFG["VERSION"] not in ("v1", "v2"):
        import time
        lv = pos.get("tp_done") or 0  # 76 scaled exits: +30% half, +60% half of rest, +100% half of rest
        for i, lvl in enumerate((1.20, 1.50, 2.00)):  # 130 tiers 20/50/100
            if lv == i and price >= pos["entry"] * lvl: out["partial"] = i + 1; out["trailing"] = 1
        if not trailing and time.time() - pos["opened"] > 20 * 60 and abs(price / pos["entry"] - 1) < 0.05: out["time_stop"] = True  # v3: flat 20 min
    return out
