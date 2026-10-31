"""brain17 floor backtest (read-only): every coin that reached RYDER's scoring stage ('score' events carry the decision-time filter results),
pair rebuilt from those logged numbers (volume, liquidity, 5m/1h buys/sells). Price-change timing is not logged -> timing = 0.5 (neutral)."""
import sqlite3, json, re, collections, brain17
c = sqlite3.connect("file:desk.db?mode=ro", uri=True)
rows = []
for m, s, d in c.execute("SELECT mint, symbol, data FROM events WHERE kind='score' ORDER BY ts"):
    j = json.loads(d); f = {k: tuple(v) for k, v in (j.get("filters") or {}).items()}
    num = lambda k: float(re.sub(r"[^\d.]", "", (f.get(k) or ("", "0"))[1]) or 0)
    pr = re.findall(r"(\d+)b/(\d+)s", (f.get("pressure") or ("", ""))[1])
    pair = dict(volume=dict(h1=num("volume_1h")), liquidity=dict(usd=num("liquidity")),
                txns=dict(m5=dict(buys=int(pr[0][0]), sells=int(pr[0][1])) if pr else {}, h1=dict(buys=int(pr[-1][0]), sells=int(pr[-1][1])) if pr else {}))
    rows.append((s, m, pair, f))
bought = {m for (m,) in c.execute("SELECT mint FROM events WHERE kind='paper_buy'")}
pn = {m: p for m, p in c.execute("SELECT mint, pnl FROM positions WHERE status='closed'")}
for lab, fl in [("all 0.35", {k: 0.35 for k in brain17.FLOORS}), ("chosen", dict(brain17.FLOORS)), ("all 0.50", {k: 0.5 for k in brain17.FLOORS})]:
    brain17.FLOORS.update(fl); cnt = collections.Counter(); rej = []
    for s, m, pair, f in rows:
        w = brain17.weak(brain17.scorecard(pair, f))
        if w: cnt[w] += 1; rej.append(f"{s}{'*' if m in bought else ''}")
    print(f"{lab}: {len(rows)} scored coins, {len(rej)} newly rejected {dict(cnt)} -> {rej}")
brain17.FLOORS.update(dict(rug=0.35, hype=0.25, holders=0.35, dev=0.35, bundle=0.35, originality=0.35, timing=0.25))
print("bought (*) results:", {s: pn.get(m) for s, m, _, _ in rows if m in bought})
for s, m, pair, f in rows: print(s, brain17.scorecard(pair, f))
