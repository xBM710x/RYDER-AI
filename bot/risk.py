"""Stage 5: Risk. Hard stop -8% set BEFORE entry; at +15% switch to trailing stop 8% below peak."""
from common import CFG
def initial_stop(entry): return entry * (1 - CFG["STOP_PCT"])
def update(pos, price):
    peak = max(pos["peak"], price); stop, trailing = pos["stop"], pos["trailing"]
    if price >= pos["entry"] * (1 + CFG["TRAIL_ACTIVATE"]): trailing = 1
    if trailing: stop = max(stop, peak * (1 - CFG["TRAIL_PCT"]))
    out = dict(peak=peak, stop=stop, trailing=trailing, exit=price <= stop, partial=False, time_stop=False)
    if CFG["VERSION"] not in ("v1", "v2"):
        import time
        if not pos.get("tp_done") and price >= pos["entry"] * 1.30: out["partial"] = True; out["trailing"] = 1  # v3: sell half at +30%, trail rest
        if not trailing and time.time() - pos["opened"] > 20 * 60 and abs(price / pos["entry"] - 1) < 0.05: out["time_stop"] = True  # v3: flat 20 min
    return out
