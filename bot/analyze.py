"""Which filters/scores relate to outcomes. Tiny samples: descriptive only."""
import json, collections
from logger import conn
c = conn()
pos = {r["mint"]: dict(r) for r in c.execute("SELECT * FROM positions WHERE status='closed'")}
sc = {}
for r in c.execute("SELECT mint,symbol,data,version FROM events WHERE kind='score'"):
    sc[r["mint"]] = (r["symbol"], json.loads(r["data"]), r["version"])
print("Scored tokens (score, parts) and outcome:")
for m, (s, d, v) in sorted(sc.items(), key=lambda x: -x[1][1]["score"]):
    p = pos.get(m); out = f"{(p['exit']/p['entry']-1)*100:+.1f}% {p['reason']} in {(p['closed']-p['opened'])/60:.1f}min" if p else ("traded/open" if d["score"] >= 0.6 else "not traded")
    print(f"  {v} {s[:12]:<12} {d['score']:.3f} {d['parts']}  -> {out}")
k = collections.Counter(json.loads(r["data"])["reason"] for r in c.execute("SELECT data FROM events WHERE kind='kill'"))
print("All kills:", dict(k))
