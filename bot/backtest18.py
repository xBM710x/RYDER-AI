"""Skeptic backtest (read-only): the coins that reached RYDER's scoring stage, using decision-time filter results ('score' events)."""
import collections, json, sqlite3, brain17, brain18
exec(open("backtest17.py").read().split("bought =")[0])  # reuse rows (decision-time pair rebuilt from logged numbers)
bought = {m for (m,) in c.execute("SELECT mint FROM events WHERE kind='paper_buy'")}
pn = {m: p for m, p in c.execute("SELECT mint, pnl FROM positions WHERE status='closed'")}
cnt = collections.Counter(); out = []
for s, m, pair, f in rows:
    sc = brain17.scorecard(pair, f); w = brain17.weak(sc) or brain18.skeptic(m, pair, f, sc, 15.0, "v3", now=0)
    if w: cnt[w.split(":")[0]] += 1; out.append((s, m in bought, pn.get(m), w))
print(f"{len(rows)} scored coins -> skeptic rejects {len(out)} {dict(cnt)}")
for x in out: print("  ", x)
