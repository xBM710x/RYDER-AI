"""RYDER upgrades 516-530 (PAPER ONLY): near-miss bar advisor. SUGGESTS which bar is costing winners; never changes a bar.
Caveat: a near-miss was rejected at its first failing gate, so later safety checks (rug/holders/LP) were never run on it.
A 'missed winner' here may still have failed safety, so the advice is an upper bound on what a looser bar would have caught."""
import time, os, json
import brain10
from common import CFG
from logger import log
BANDS = ((0.9, 1.0), (0.75, 0.9), (0.6, 0.75), (0.3, 0.6))
def advise(min_n=15, win=0.30):
    """519-524: per bar (volume_1h / liquidity) and band of how close the coin was to the bar, count near-misses that hit +30%
    within 60 min vs fell -30%. A band 'costs winners' when n >= min_n, win rate >= 25% and wins > losses."""
    recs = [r for r in brain10.S.get("nm_recs", []) if time.time() - r["t"] < 7 * 86400]
    out = {}
    for reason, key in (("volume_1h", "vr"), ("liquidity", "lr")):
        rows = []
        for lo, hi in BANDS:
            xs = [r for r in recs if r["reason"] == reason and r.get(key) is not None and lo <= r[key] < hi]
            n = len(xs); w = sum(r["gmax"] >= win for r in xs); l = sum(r["g60"] <= -win for r in xs)
            rows.append(dict(band=f"{int(lo*100)}-{int(hi*100)}% of bar", n=n, won=w, lost=l, win_rate=round(w / n, 2) if n else None))
        cost = [r for r in rows if r["n"] >= min_n and r["win_rate"] >= 0.25 and r["won"] > r["lost"]]
        bar = CFG["MIN_VOL_H1"] if reason == "volume_1h" else CFG["MIN_LIQ"]
        if cost:
            lo = min(float(r["band"].split("-")[0]) for r in cost) / 100
            sug = f"SUGGEST (not applied): {reason} bar ${bar:,.0f} may be costing winners; coins at {int(lo*100)}%+ of it ran +30% {sum(r['won'] for r in cost)}x vs dumped {sum(r['lost'] for r in cost)}x. Ask Braydon before trying ~${bar*max(lo,0.85):,.0f} on the practice desk first."
        else:
            n_ = sum(r["n"] for r in rows); sug = f"keep {reason} bar (${bar:,.0f}): " + ("not enough data yet" if n_ < min_n else "near-misses are not winning more than they dump")
        out[reason] = dict(bands=rows, suggestion=sug)
    out["records"] = len(recs); out["caveat"] = "near-misses never ran the later safety checks; wins are an upper bound"
    return out
_L = [0]
def line():
    """525: one-line summary for the recap / Telegram."""
    a = advise(); return "Bar check: " + " | ".join(a[k]["suggestion"].split(":")[0] + ("" if "keep" in a[k]["suggestion"] else " ⚠️") for k in ("volume_1h", "liquidity")) + f" ({a['records']} near-misses tracked)"
def jobs(k):
    """526: hourly 'bar_advice' event in runner.log (no setting change)."""
    if k % 3600 == 1234:
        try: a = advise(); log("bar_advice", vol=a["volume_1h"]["suggestion"], liq=a["liquidity"]["suggestion"], records=a["records"])
        except Exception as e: log("error", where="brain12.jobs", trace=str(e)[:200])
def status():
    """527-530: heartbeat block b12 with full band tables."""
    try: return advise()
    except Exception as e: return dict(err=str(e)[:100])
