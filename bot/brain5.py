"""Upgrades 201-220: decision quality + confidence (PAPER ONLY; no real trading, wallets, keys or signing — ever)."""
import time, json, math, collections, statistics
from common import CFG
from logger import conn, log
import brain2
B = brain2.BRAIN; AG = brain2.AGENTS; EXP = CFG["VERSION"] + "x"  # 211 experimental paper desk
XW = 0.5  # v3x trades teach the main book at half weight
def _all(days=30):
    a = _trades(days=days); x = _trades(EXP, days)
    for p in a: p["w"] = 1.0
    for p in x: p["w"] = XW
    return a + x
def exp_tally():
    x = _trades(EXP, 1); w = sum(p["tot"] > 0 for p in x); c = conn()
    eq = (c.execute("SELECT v FROM account WHERE k=?", ("cash_" + EXP,)).fetchone() or [CFG["START_BALANCE"]])[0] + c.execute("SELECT COALESCE(SUM(cost),0) FROM positions WHERE status='open' AND version=?", (EXP,)).fetchone()[0]; c.close()
    return f"v3x experimental (24h): {len(x)} trades, {w}W/{len(x)-w}L, ${sum(p['tot'] for p in x):+.2f} · equity ${eq:.2f}"
def _trades(ver=None, days=30):
    ver = ver or CFG["VERSION"]; c = conn()
    cl = [dict(x) for x in c.execute("SELECT * FROM positions WHERE status='closed' AND version=? AND reason!='partial_tp' AND closed>?", (ver, time.time() - days * 86400))]
    buys = {r["mint"]: json.loads(r["data"]) for r in c.execute("SELECT mint,data FROM events WHERE kind='paper_buy' AND COALESCE(json_extract(data,'$.book'),version)=? ORDER BY ts", (ver,))}
    part = collections.defaultdict(float)
    for r in c.execute("SELECT mint,pnl FROM positions WHERE reason='partial_tp' AND version=?", (ver,)): part[r["mint"]] += r["pnl"]
    c.close()
    for p in cl: p["tot"] = p["pnl"] + part[p["mint"]]; p["buy"] = buys.get(p["mint"], {})
    return cl
# 201 calibration: binned predicted vs realised win rate (isotonic-style monotone smoothing)
BINS = [0, .4, .5, .6, .7, 1.01]
def calib_table():
    rows = [((p["buy"].get("plan") or {}).get("p_raw") or (p["buy"].get("council") or {}).get("consensus"), p["tot"] > 0, p["w"]) for p in _all()]
    rows = [r for r in rows if r[0] is not None]; out = []
    for lo, hi in zip(BINS, BINS[1:]):
        s = [(win, wt) for c, win, wt in rows if lo <= c < hi]; prior = (lo + hi) / 2 * 0.8
        out.append(round((sum(win * wt for win, wt in s) + 2 * prior) / (sum(wt for _, wt in s) + 2), 3))  # shrink to prior when few trades
    for i in range(1, len(out)): out[i] = max(out[i], out[i - 1])  # monotone (isotonic pass)
    return out, round(sum(r[2] for r in rows), 1)
def calibrate(p):
    t, n = calib_table(); i = max(i for i, lo in enumerate(BINS[:-1]) if p >= lo)
    return round(0.5 * p + 0.5 * t[i], 3) if n >= 10 else t[i], n  # few trades -> conservative prior table
# 206 combined model over council votes + features (logistic), fallback to rules
MODEL = {"m": None, "n": 0, "t": 0}
FK = ["score", "vol", "liq", "buysell", "momentum", "m5", "h1", "liq_mcap", "age_min"]
def _x(buy):
    v = (buy.get("council") or {}).get("votes") or {}; f = buy.get("feats") or {}
    return [v.get(a, [0.5])[0] for a in AG] + [float(f.get(k, 0) or 0) for k in FK]
def train():
    tr = [p for p in _all(days=60) if p["buy"].get("council")]; MODEL["t"] = time.time()
    y = [int(p["tot"] > 0) for p in tr]
    if len(tr) < 20 or len(set(y)) < 2: return False
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    from sklearn.pipeline import make_pipeline
    MODEL["m"] = make_pipeline(StandardScaler(), LogisticRegression(max_iter=500, C=0.5)).fit([_x(p["buy"]) for p in tr], y, logisticregression__sample_weight=[p["w"] for p in tr]); MODEL["n"] = len(tr)
    log("model5_trained", n=len(tr)); return True
def model_p(votes, feats, cons):
    if time.time() - MODEL["t"] > 3600:
        try: train()
        except Exception: MODEL["t"] = time.time()
    if MODEL["m"] is not None:
        try: return round(float(MODEL["m"].predict_proba([_x(dict(council=dict(votes=votes), feats=feats))])[0][1]), 3), "model"
        except Exception: pass
    return cons, "rules"
# 207 similarity to past winners / 215 rug pattern memory (nearest neighbours on features)
SK = ["vol", "liq", "buysell", "momentum", "liq_mcap"]
def similarity(feats):
    tr = [p for p in _all(days=60) if p["buy"].get("feats")]; c = conn()
    rug = [json.loads(r["data"]).get("feats") for r in c.execute("SELECT data FROM events WHERE kind='paper_buy' AND mint IN (SELECT mint FROM positions WHERE reason IN ('dev_sell','lp_pull','holder_concentration','sell_spike_5s'))")]; c.close()
    d = lambda g: math.dist([float(feats.get(k, 0) or 0) for k in SK], [float(g.get(k, 0) or 0) for k in SK])
    near = sorted(tr, key=lambda p: d(p["buy"]["feats"]))[:5]
    win_sim = round(sum((p["tot"] > 0) * p["w"] for p in near) / sum(p["w"] for p in near), 2) if len(near) >= 3 else None
    rug_sim = sum(1 for g in rug if g and d(g) < 0.1)
    return win_sim, rug_sim
# 208 per-coin-type exit learning: target from realised peaks of winners of the same type
def coin_type(pair, narr):
    return f"{pair.get('dexId','?')}|{narr}"
def learned_target(ct):
    t = (B.get("exit_types") or {}).get(ct)
    return max(0.15, min(1.0, t["peak"])) if t and t["n"] >= 3 else 0.20  # conservative default until learned
def learn_exit(ct, peak_gain, win, w=1.0):
    if not ct: return
    e = B.setdefault("exit_types", {}).setdefault(ct, dict(n=0, peak=0.2))
    if win: e["n"] += w; a = 0.3 * w; e["peak"] = round(e["peak"] * (1 - a) + a * peak_gain * 0.8, 3)  # aim for ~80% of the typical winner's peak
# 216 own-impact pricing + 202 positive EV gate after fees & slippage
def ev(p, target, stop, slip, impact_pct=0):
    cost = 2 * CFG["FEE"] + 2 * slip + (impact_pct or 0) / 100
    return round(p * target - (1 - p) * stop - cost, 4), round(cost, 4)
# 203 fractional, capped Kelly (relative to the 10% max position)
def kelly(p, target, stop):
    b = target / max(stop, 1e-6); f = (p * b - (1 - p)) / b
    return round(max(0.0, min(1.0, 0.25 * f / CFG["MAX_PCT_PER_TRADE"])), 3)  # quarter-Kelly, never above the 10% cap
# 213 streak ramp: slow ramp up after wins, fast cut after losses
def streak_mult():
    cl = sorted(_trades(days=3), key=lambda p: p["closed"])[-4:]; s = 0
    for p in reversed(cl):
        if (p["tot"] > 0) == (s >= 0) or s == 0: s += 1 if p["tot"] > 0 else -1
        else: break
    return {-1: 0.75, -2: 0.5, -3: 0.35}.get(max(-3, s), 1.0) if s < 0 else min(1.2, 1 + 0.05 * s)
# 214 24h regime day mode
def day_mode(reg):
    h24 = (reg or {}).get("sol_h24") or 0
    return "defense day" if h24 <= -5 else "offense day" if h24 >= 5 else "normal day"
# 217 weekly hot themes (narratives with best recent results across all scored coins)
def hot_themes():
    c = conn(); ws = collections.defaultdict(lambda: [0, 0.0])
    for r in c.execute("SELECT data FROM events WHERE kind='paper_exit' AND ts>?", (time.time() - 7 * 86400,)):
        pass
    for p in _trades(days=7) + _trades(EXP, 7):
        n = p["buy"].get("narrative") or "other"; ws[n][0] += 1; ws[n][1] += p["tot"]
    c.close()
    return sorted([(n, round(v[1], 2), v[0]) for n, v in ws.items() if v[0] >= 2 and v[1] > 0], key=lambda x: -x[1])[:3]
# 212 per-rule scorekeeping -> weight of the Filter vote
def rule_weight():
    rs = B.get("rule_stats") or {}; n = sum(s.get("n", 0) for s in rs.values()); mw = sum(s.get("missed_winners", 0) for s in rs.values())
    return round(max(0.7, 1 - mw / max(1, n)), 3)
# 205 split-vote debate round
def debate(v):
    vals = [x[0] for x in v.values()]
    if statistics.pstdev(vals) <= 0.2: return v, None
    tr = B["trust"]; mean = sum(tr[a] * v[a][0] for a in v) / sum(tr[a] for a in v); nv = {}; notes = []
    for a, (c, why) in v.items():
        hi = max(v, key=lambda k: v[k][0]); lo = min(v, key=lambda k: v[k][0])
        shift = 0.3 * (mean - c) * (1.0 if tr[a] < (tr[hi] + tr[lo]) / 2 else 0.5)  # less-trusted agents move more
        nv[a] = (round(min(1, max(0, c + shift)), 3), why)
    notes = f"debate: {hi} argued '{v[hi][1][:45]}' vs {lo} '{v[lo][1][:45]}'"
    return nv, notes
# 204 agents learn from each other's best calls: trust moves toward the best-graded agent's level
def peer_learn():
    g = B["grades"]; acc = {a: (g[a][1] + 1) / (g[a][0] + 2) for a in AG if a in g}
    if not acc: return
    best = max(acc, key=acc.get)
    for a in AG:
        if a != best and g.get(a, [0])[0] >= 5: B["trust"][a] = round(B["trust"][a] + 0.1 * (B["trust"][best] - B["trust"][a]), 3)
    B["mentor"] = best
# 209/218/220 pre-trade plan, confidence meter, explanation
def meter(p): n = int(round(p * 10)); return "▰" * n + "▱" * (10 - n) + f" {p*100:.0f}%"
def plan(sym, p, src, target, stop, hold_min, evv, cost, kel):
    return dict(p=p, src=src, target=round(target, 3), stop=round(stop, 3), time_limit_min=hold_min, ev=evv, cost=cost, kelly=kel,
                text=f"Plan: target +{target*100:.0f}%, stop −{stop*100:.1f}%, time limit {hold_min} min · EV {evv*100:+.1f}% after {cost*100:.1f}% costs · size {kel:.2f}× max\nConfidence {meter(p)} ({src})")
# 210 post-trade decision grading
def grade(buy, tot):
    pl = buy.get("plan") or {}; good = (pl.get("ev") or 0) > 0
    return ("good call ✅" if tot > 0 else "unlucky (good decision, bad outcome)") if good else ("lucky (weak decision, good outcome)" if tot > 0 else "bad call ❌")
def on_close(pos, tot):
    c = conn(); r = c.execute("SELECT data FROM events WHERE kind='paper_buy' AND mint=? AND COALESCE(json_extract(data,'$.book'),version)=? ORDER BY ts DESC LIMIT 1", (pos["mint"], pos["version"])).fetchone(); c.close()
    buy = json.loads(r["data"]) if r else {}; g = grade(buy, tot)
    learn_exit((buy.get("plan") or {}).get("type"), pos["peak"] / pos["entry"] - 1 if pos.get("peak") else 0, tot > 0, XW if pos["version"] == EXP else 1.0)
    if pos["version"] == CFG["VERSION"]: peer_learn()
    gs = B.setdefault("decision_grades", {}); gs[g] = gs.get(g, 0) + 1; brain2.save(B); log("decision_grade", pos["mint"], pos["symbol"], grade=g, pnl=round(tot, 2), book=pos["version"])
    if pos["version"] == CFG["VERSION"]: __import__("alerts").send_async(f"📋 RYDER self-grade · {pos['symbol']}: {g} (${tot:+.2f}, paper)")
# 219 paper goal tracker (informational only)
GOALS = dict(trades=30, win_rate=0.55, profit=30.0)
def goals_line():
    tr = _trades(days=365); n = len(tr); w = sum(p["tot"] > 0 for p in tr); pf = sum(p["tot"] for p in tr)
    ok = lambda b: "✅" if b else "⏳"
    return (f"Paper goals: trades {n}/{GOALS['trades']} {ok(n >= GOALS['trades'])} · win rate {w/max(1,n):.0%}/{GOALS['win_rate']:.0%} {ok(n >= 10 and w/max(1,n) >= GOALS['win_rate'])} · "
            f"profit ${pf:+.2f}/${GOALS['profit']:.0f} {ok(pf >= GOALS['profit'])} (informational; paper only)")
# the full decision: returns (go, size_mult, plan, why)
def decide(sym, m, pair, votes, cons, feats, narr, stop_pct, impact, reg, exp=False):
    p_m, src = model_p({a: list(x) for a, x in votes.items()}, feats, cons)
    p_raw = round(0.5 * cons + 0.5 * p_m, 3) if src == "model" else cons
    ws, rs = similarity(feats)
    if ws is not None: p_raw = round(0.8 * p_raw + 0.2 * ws, 3); src += "+similar"
    if rs >= 2: return False, 0, None, f"looks like {rs} past rugs (rug memory)"
    if narr in [t[0] for t in hot_themes()]: p_raw = min(1, p_raw + 0.03); src += "+hot theme"
    p, ncal = calibrate(p_raw); dm = day_mode(reg)
    ct = coin_type(pair, narr); target = learned_target(ct)
    hold = int(max(10, min(60, 2 * (B.get("exit_hold_min") or 20))))
    from brain4 import slip; evv, cost = ev(p, target, stop_pct, slip(30, pair), impact)
    kel = kelly(p, target, stop_pct); mult = round(kel * streak_mult() * (0.7 if dm == "defense day" else 1.1 if dm == "offense day" else 1.0), 3)
    pl = plan(sym, p, src, target, stop_pct, hold, evv, cost, kel); pl.update(p_raw=p_raw, type=ct, day=dm, calibrated_on=ncal)
    if exp: return (evv > 0), 1.0, pl, f"v3x EV {evv*100:+.1f}%"  # experimental desk: any positive EV, fixed small size
    if evv <= 0.01: return False, 0, pl, f"EV {evv*100:+.1f}% below +1% after costs (p {p}, target +{target*100:.0f}%, stop −{stop_pct*100:.0f}%)"
    if mult < 0.15: return False, 0, pl, f"Kelly size too small ({mult})"
    return True, min(1.0, mult), pl, f"EV {evv*100:+.1f}% · {dm}"
