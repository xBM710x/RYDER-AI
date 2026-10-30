"""37: Backtester on stored data (PAPER). Replays this version's scored coins + realized trades under alternative score thresholds."""
import json, sys
from logger import conn
from common import CFG
def run(ver=None):
    ver = ver or CFG["VERSION"]; c = conn()
    sc = {r["mint"]: json.loads(r["data"]).get("score", 0) for r in c.execute("SELECT mint,data FROM events WHERE kind='score' AND version=?", (ver,))}
    tr = {}
    for r in c.execute("SELECT mint,pnl FROM positions WHERE status='closed' AND version=?", (ver,)): tr[r["mint"]] = tr.get(r["mint"], 0) + r["pnl"]
    c.close(); out = []
    for th in (0.55, 0.6, 0.65, 0.7, 0.75, 0.8):
        sel = [p for m, p in tr.items() if sc.get(m, 0) >= th]
        out.append(dict(th=th, trades=len(sel), pnl=round(sum(sel), 2), win=round(sum(p > 0 for p in sel) / len(sel), 2) if sel else None))
    best = max((o for o in out if o["trades"] >= 3), key=lambda o: o["pnl"], default=None)
    return dict(ver=ver, scored=len(sc), traded=len(tr), by_threshold=out, best_threshold=best and best["th"])
if __name__ == "__main__": print(json.dumps(run(*(sys.argv[1:2])), indent=1))
