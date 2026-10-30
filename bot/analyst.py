"""Stage 3: Analyst. v3 score = 0.25*vol + 0.25*liq + 0.25*buysell + 0.15*spread + 0.10*momentum, each in [0,1]
 vol      = min(1, vol_h1 / 200k)
 liq      = min(1, liquidity_usd / 100k)
 buysell  = clamp((buys_h1/(buys+sells) - 0.4) / 0.3)   (40% buys ->0, 70% ->1)
 spread   = clamp((25 - top10_pct) / 15)                (25% ->0, 10% ->1)
 momentum = clamp((m5_change + 5) / 25) if h1 change > -20% else 0  (-5% ->0, +20% ->1)
Threshold 0.6."""
import re
cl = lambda x: max(0.0, min(1.0, x))
def score(pair, filt):
    v = (pair.get("volume") or {}).get("h1", 0); l = (pair.get("liquidity") or {}).get("usd", 0) or 0
    t = (pair.get("txns") or {}).get("h1") or {}; b, s = t.get("buys", 0), t.get("sells", 0)
    pc = pair.get("priceChange") or {}
    top = float(re.match(r"[\d.]+", filt["top10"][1]).group())
    parts = dict(vol=cl(v / 200_000), liq=cl(l / 100_000), buysell=cl(((b / (b + s) if b + s else 0) - 0.4) / 0.3),
                 spread=cl((25 - top) / 15), momentum=cl(((pc.get("m5") or 0) + 5) / 25) if (pc.get("h1") or 0) > -20 else 0.0)
    w = weights()
    return round(sum(parts[k] * w[k] for k in w), 3), {k: round(x, 3) for k, x in parts.items()}

import json, os
WF = os.path.join(os.path.dirname(os.path.abspath(__file__)), "weights.json")
BASE = dict(vol=.25, liq=.25, buysell=.25, spread=.15, momentum=.10)  # v3: momentum cut .20->.10
def weights():
    try: return json.load(open(WF))["w"]
    except Exception: return dict(BASE)
def retune(every=25):
    """v3 self-tuning: every 25 closed trades, nudge weights toward parts that separated winners from losers."""
    from logger import conn, log
    from common import CFG
    c = conn(); V = CFG["VERSION"]
    cl = [dict(r) for r in c.execute("SELECT mint,pnl FROM positions WHERE status='closed' AND version=? AND reason!='partial_tp'", (V,))]
    try: done = json.load(open(WF)).get("n", 0)
    except Exception: done = 0
    if len(cl) < every or len(cl) - done < every: c.close(); return
    parts = {}
    for r in c.execute("SELECT mint,data FROM events WHERE kind='score' AND version=?", (V,)): parts[r["mint"]] = json.loads(r["data"])["parts"]
    c.close(); w = weights(); win = [parts[x["mint"]] for x in cl if x["pnl"] > 0 and x["mint"] in parts]; los = [parts[x["mint"]] for x in cl if x["pnl"] <= 0 and x["mint"] in parts]
    if not win or not los: return
    for k in w:
        edge = sum(p[k] for p in win) / len(win) - sum(p[k] for p in los) / len(los)
        w[k] = max(0.05, min(0.40, w[k] * (1 + max(-0.3, min(0.3, edge)))))
    s = sum(w.values()); w = {k: round(v / s, 3) for k, v in w.items()}
    json.dump(dict(w=w, n=len(cl), at=time.time()), open(WF, "w")); log("retune", weights=w, trades=len(cl))
import time
