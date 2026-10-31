"""Backtest of the six agent rules on stored history (PAPER, read-only). Outcome = price ~1h after first sight (counterfactual table,
or snapshots.px1). dead = -80% or worse; winner = +30% or better. 'pnl' = mean 1h move clipped to [-100%, +100%] (per-coin, no stops)."""
import sqlite3, json, statistics as st, collections, sys, time
c = sqlite3.connect("desk.db"); R = {}
def clip(x): return max(-100, min(100, x))
def summ(ps):
    if not ps: return dict(n=0)
    return dict(n=len(ps), dead=sum(p <= -80 for p in ps), win=sum(p >= 30 for p in ps), dead_rate=round(sum(p <= -80 for p in ps) / len(ps), 3),
                median=round(st.median(ps), 1), pnl_clip=round(sum(map(clip, ps)) / len(ps), 1))
src = {}
for m, d in c.execute("SELECT mint, data FROM events WHERE kind='kill' ORDER BY id"):
    j = json.loads(d); src.setdefault(m, j.get("source") or "?")
cf = c.execute("SELECT mint, pct, ts FROM counterfactual ORDER BY ts").fetchall()
R["universe"] = dict(summ([p for _, p, _ in cf]), span_h=round((cf[-1][2] - cf[0][2]) / 3600, 1))
# Scout: source death-rate. Walk forward in time: rate learned only from earlier coins (no look-ahead), min n=8.
for th in (0.6, 0.5, 0.4, 0.35, 0.3, 0.25):
    seen = collections.defaultdict(lambda: [0, 0]); flag, keep = [], []
    for m, p, t in cf:
        s = src.get(m, "?"); r = seen[s]
        (flag if r[0] >= 8 and r[1] / r[0] >= th else keep).append(p)
        r[0] += 1; r[1] += p <= -80
    R[f"scout_src>={th}"] = dict(flagged=summ(flag), passed=summ(keep))
R["by_source"] = {s: summ([p for m, p, _ in cf if src.get(m, "?") == s]) for s in set(src.get(m, "?") for m, _, _ in cf)}
# Pair-shape rules need txns / 5m change / mcap at decision time -> only from snapshots (stored from tonight on).
try: sn = c.execute("SELECT mint, data, px1, liq1 FROM snapshots WHERE px1 IS NOT NULL").fetchall()
except Exception: sn = []
rules = dict(
    filter_wash=lambda d: (d.get("tx5") == d.get("tx1")) and d.get("tx5") and d.get("age") and (time.time() * 1000 - d["age"]) / 60000 > 10,
    analyst_m5_gt25=lambda d: d.get("m5", 0) > 25,
    executor_mc_gt20x_liq=lambda d: d.get("liq") and d.get("mc", 0) > 20 * d["liq"])
for name, fn in rules.items():
    fl, ok = [], []
    for m, d, px1, l1 in sn:
        d = json.loads(d); g = -100 if (l1 or 0) < 1000 else (px1 / d["px"] - 1) * 100 if d.get("px") else None
        if g is None: continue
        (fl if fn(d) else ok).append(g)
    R[name] = dict(flagged=summ(fl), passed=summ(ok), note="needs snapshots (stored from 2026-10-30 22:xx PT on)" if not sn else "")
cv = c.execute("SELECT COUNT(*) FROM events WHERE kind='council_votes'").fetchone()[0]
R["disagreement_and_rug_memory"] = dict(council_votes_logged=cv, note="no council decisions logged yet (no coin reached the council since the agent upgrade)" if not cv else "")
R["trades"] = [dict(sym=s, ver=v, pnl=round(p, 2), why=r) for s, v, p, r in c.execute("SELECT symbol, version, pnl, reason FROM positions WHERE status='closed'")]
json.dump(R, open("reports/backtest14.json", "w"), indent=1); print(json.dumps(R, indent=1))
# Copycat (symbol only; names/images were not stored historically): walk forward, flag a coin if an EARLIER coin with the same symbol died.
sym = {}
for m, s in c.execute("SELECT mint, symbol FROM events WHERE kind='kill' AND symbol IS NOT NULL"): sym.setdefault(m, (s or "").strip().lower())
dead_syms, fl, ok = set(), [], []
for m, p, t in cf:
    s = sym.get(m, "")
    if len(s) >= 3: (fl if s in dead_syms else ok).append(p)
    if p <= -80 and len(s) >= 3: dead_syms.add(s)
R["copycat_symbol"] = dict(flagged=summ(fl), passed=summ(ok)); print("copycat", R["copycat_symbol"])
json.dump(R, open("reports/backtest14.json", "w"), indent=1)
