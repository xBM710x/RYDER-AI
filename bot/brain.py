"""v3 upgrades 61-100 (PAPER ONLY; public read-only data; no keys, no real orders)."""
import time, json, os, math, collections, threading
from common import CFG, http_json, dex_market, HEALTH
from logger import conn, log
import extras, onchain, detect
D = os.path.dirname(os.path.abspath(__file__))
PROMO = os.path.join(D, "promoted.json"); MODEL = {"m": None, "n": 0, "feats": None}
COOLDOWN = {"until": 0}; _lock = threading.Lock()
FEATS = ["score", "vol", "liq", "buysell", "spread", "momentum", "m5", "h1", "liq_mcap", "age_min", "mcap_k", "night"]
def _closed(ver=None):
    c = conn(); r = [dict(x) for x in c.execute("SELECT * FROM positions WHERE status='closed' AND version=? AND reason!='partial_tp'", (ver or CFG["VERSION"],))]; c.close(); return r
def _buys():
    c = conn(); r = {x["mint"]: json.loads(x["data"]) for x in c.execute("SELECT mint,data FROM events WHERE kind='paper_buy' AND version=?", (CFG["VERSION"],))}; c.close(); return r
def features(pair, parts, score):
    pc = (pair or {}).get("priceChange") or {}; liq = ((pair or {}).get("liquidity") or {}).get("usd") or 0; mc = (pair or {}).get("marketCap") or (pair or {}).get("fdv") or 1
    age = (time.time() * 1000 - ((pair or {}).get("pairCreatedAt") or time.time() * 1000)) / 60000; h = time.localtime().tm_hour
    return dict(score=score, **{k: parts.get(k, 0) for k in ("vol", "liq", "buysell", "spread", "momentum")}, m5=pc.get("m5") or 0, h1=pc.get("h1") or 0,
                liq_mcap=round(liq / mc, 3), age_min=round(age), mcap_k=round(mc / 1000), night=int(h < 7 or h >= 22))
# 61/78/79/80/86/87: bucket learning memory
def bucket(f, dex, narr):
    mc = f["mcap_k"]; age = f["age_min"]
    return dict(narr=narr, dex=dex, mcap="<100k" if mc < 100 else "100k-500k" if mc < 500 else "500k-2m" if mc < 2000 else ">2m",
                age="<30m" if age < 30 else "30m-2h" if age < 120 else "2h-24h" if age < 1440 else ">1d", daypart="night" if f["night"] else "day",
                week="weekend" if time.localtime().tm_wday >= 5 else "weekday")
def memory():
    buys = _buys(); stats = collections.defaultdict(lambda: dict(n=0, w=0, pnl=0.0))
    for p in _closed():
        b = buys.get(p["mint"], {}).get("bucket") or {}
        for k, v in b.items():
            s = stats[f"{k}:{v}"]; s["n"] += 1; s["w"] += p["pnl"] > 0; s["pnl"] = round(s["pnl"] + p["pnl"], 2)
    return dict(stats)
def bucket_adj(b, mem):
    adj, why = 0.0, []
    for k, v in b.items():
        s = mem.get(f"{k}:{v}")
        if s and s["n"] >= 4:
            wr = s["w"] / s["n"]
            if wr <= 0.2: adj -= 0.04; why.append(f"{k} {v} weak ({s['w']}/{s['n']})")
            elif wr >= 0.6: adj += 0.03; why.append(f"{k} {v} strong ({s['w']}/{s['n']})")
    return max(-0.12, min(0.09, adj)), why
# 62/63: ML win probability (logistic regression once >= 50 trades; rules fallback)
def train():
    buys = _buys(); X, y = [], []
    for p in _closed():
        f = buys.get(p["mint"], {}).get("feats")
        if f: X.append([f.get(k, 0) for k in FEATS]); y.append(int(p["pnl"] > 0))
    if len(X) < 50 or len(set(y)) < 2: return False
    try:
        from sklearn.linear_model import LogisticRegression
        from sklearn.preprocessing import StandardScaler
        from sklearn.pipeline import make_pipeline
        m = make_pipeline(StandardScaler(), LogisticRegression(max_iter=500)).fit(X, y); MODEL.update(m=m, n=len(X)); log("ml_trained", n=len(X)); return True
    except Exception as e: log("error", where="ml_train", trace=str(e)[:200]); return False
def win_prob(f):
    if MODEL["m"] is not None:
        try: return round(float(MODEL["m"].predict_proba([[f.get(k, 0) for k in FEATS]])[0][1]), 3), "ml"
        except Exception: pass
    z = (f["score"] - 0.6) * 6 + (0.3 if f["m5"] > 0 else -0.3) + (0.3 if 0.05 <= f["liq_mcap"] <= 0.5 else -0.3)
    return round(1 / (1 + math.exp(-z)) * 0.6, 3), "rules"  # rules prior deliberately <= 0.6
# 64 confidence sizing (cap 10% via executor)
def size_mult(conf, wp):
    return round(max(0.4, min(1.0, 0.4 + (conf - 0.6) * 1.5 + (wp - 0.35))), 2)
# 65/66/77/84: market-structure checks from DexScreener pair
def structure(pair):
    pc = pair.get("priceChange") or {}; tx = pair.get("txns") or {}; vol = pair.get("volume") or {}
    m5, h1, h6 = pc.get("m5") or 0, pc.get("h1") or 0, pc.get("h6") or 0
    if m5 < -3 and h1 < 0: return "fail", "trend", f"down on 5m ({m5}%) and 1h ({h1}%)"
    t1 = (tx.get("h1") or {}); n1 = (t1.get("buys") or 0) + (t1.get("sells") or 0); v1 = vol.get("h1") or 0; liq = (pair.get("liquidity") or {}).get("usd") or 1
    avg = v1 / max(1, n1)
    if n1 < 60 and avg > 0.03 * liq: return "fail", "whale_volume", f"{n1} txs/1h, avg ${avg:,.0f} = whale-driven volume"
    s5 = (tx.get("m5") or {}).get("sells") or 0; b5 = (tx.get("m5") or {}).get("buys") or 0
    if h1 > 150 and s5 >= b5 * 0.8: return "fail", "exit_liquidity", f"+{h1}% in 1h with sells catching up (5m {b5}b/{s5}s)"
    mc = pair.get("marketCap") or pair.get("fdv") or 0
    if mc and liq / mc < 0.03: return "fail", "liq_mcap", f"liq/mcap {liq/mc:.3f} too thin"
    return "pass", "", f"5m {m5}% 1h {h1}% 6h {h6}%, {n1} txs/h, liq/mcap {liq/max(mc,1):.2f}"
# 68/69/70/82: dev behaviour
def dev_check(creator):
    if not creator: return "pass", "", "no creator", 0.5
    c = conn(); n_today = c.execute("SELECT COUNT(*) FROM creators WHERE creator=? AND ts>?", (creator, time.time() - 86400)).fetchone()[0]; c.close()
    if n_today > 1: return "fail", "same_dev_today", f"dev launched {n_today} coins in 24h", 0
    sg = onchain.r("getSignaturesForAddress", [creator, {"limit": 50}]) or []
    if len(sg) < 5: return "fail", "fresh_dev", f"dev wallet has only {len(sg)} txs (fresh/unfunded)", 0
    src = None
    try: src = detect.funder(creator) if len(sg) < 50 else None
    except Exception: pass
    if src:
        bad, why = detect.is_rugger(src)
        if bad: return "fail", "linked_launch", f"dev funded by listed rug wallet {src[:6]}", 0
        c = conn(); c.execute("CREATE TABLE IF NOT EXISTS dev_funders(creator TEXT PRIMARY KEY, funder TEXT, ts REAL)")
        c.execute("INSERT OR REPLACE INTO dev_funders VALUES(?,?,?)", (creator, src, time.time()))
        sib = c.execute("SELECT COUNT(*) FROM dev_funders WHERE funder=? AND creator!=?", (src, creator)).fetchone()[0]; c.commit(); c.close()
        if sib >= 2: return "fail", "linked_launch", f"same funder {src[:6]} funded {sib} other launch devs", 0
    age_score = min(1.0, len(sg) / 50)
    return "pass", "", f"dev {len(sg)}{'+' if len(sg)==50 else ''} txs, funder {str(src)[:6]}", round(age_score, 2)
# 72: learned dump patterns (nearest neighbours of losing trades)
def dump_pattern(f):
    buys = _buys(); los = [buys[p["mint"]]["feats"] for p in _closed() if p["pnl"] < 0 and buys.get(p["mint"], {}).get("feats")]
    if len(los) < 5: return None
    keys = ["vol", "liq", "buysell", "spread", "momentum"]
    near = sum(1 for g in los if math.dist([f[k] for k in keys], [g.get(k, 0) for k in keys]) < 0.12)
    return f"{near} past losers look identical" if near >= 3 else None
# 85: price impact of a $30 buy
def impact(mint, usd=30):
    sol = float((dex_market(["So11111111111111111111111111111111111111112"]).get("So11111111111111111111111111111111111111112") or {}).get("priceUsd") or 150)
    q = http_json(f"https://lite-api.jup.ag/swap/v1/quote?inputMint=So11111111111111111111111111111111111111112&outputMint={mint}&amount={int(usd/sol*1e9)}&slippageBps=500", timeout=8)
    return float(q.get("priceImpactPct") or 0) * 100
# 81/88: pauses
def paused():
    if time.time() < COOLDOWN["until"]: return f"cooldown after stop ({round(COOLDOWN['until']-time.time())}s)"
    h = HEALTH.get("api.dexscreener.com")
    if h and h["ok"] + h["err"] > 20 and h["err"] / (h["ok"] + h["err"]) > 0.3: return "data outage: DexScreener error rate >30%"
    if h and h.get("last_ok") and time.time() - h["last_ok"] > 90: return "data outage: no DexScreener success in 90s"
    return None
def on_stop(): COOLDOWN["until"] = time.time() + 180
# 97 explanation
def explain(sym, score, wp, src, conf, mult, why_adj, struct_d, dev_d):
    return (f"Bought {sym}: score {score}, win-prob {wp:.0%} ({src}), confidence {conf}, size x{mult}. "
            f"Structure: {struct_d}. Dev: {dev_d}." + (" Memory: " + "; ".join(why_adj) + "." if why_adj else ""))
# 92 champion/challenger promotion
def promoted():
    try: return json.load(open(PROMO))
    except Exception: return {}
def check_promotion():
    A, B = _closed(CFG["VERSION"]), _closed(CFG["VERSION"] + "b")
    if len(B) < 30 or promoted().get("done"): return None
    pa, pb = sum(p["pnl"] for p in A), sum(p["pnl"] for p in B)
    if pb > pa and pb > 0:
        json.dump(dict(done=True, MIN_SCORE=CFG["AB_SCORE"], at=time.time(), a=round(pa, 2), b=round(pb, 2)), open(PROMO, "w")); log("promote", champion="v3b", a=pa, b=pb)
    return dict(a=round(pa, 2), b=round(pb, 2), b_trades=len(B))
# 93/94/95: kill audit + missed winners + false passes
def audit():
    c = conn(); c.execute("CREATE TABLE IF NOT EXISTS audit(mint TEXT PRIMARY KEY, reason TEXT, kill_px REAL, later_px REAL, ts REAL)")
    rows = [dict(r) for r in c.execute("SELECT mint, data, ts FROM events WHERE kind='kill' AND version=? AND ts<? AND ts>? ORDER BY ts DESC LIMIT 400", (CFG["VERSION"], time.time() - 3600, time.time() - 86400))]
    done = {r[0] for r in c.execute("SELECT mint FROM audit")}; c.close()
    todo = []
    for r in rows:
        d = json.loads(r["data"])
        if r["mint"] in done or not d.get("final", True) or not d.get("px"): continue
        todo.append((r["mint"], d["reason"], d["px"]))
    todo = todo[:30]
    if todo:
        mk = dex_market([t[0] for t in todo]); c = conn()
        for m, rs, px in todo:
            c.execute("INSERT OR REPLACE INTO audit VALUES(?,?,?,?,?)", (m, rs, px, float((mk.get(m) or {}).get("priceUsd") or 0), time.time()))
        c.commit(); c.close()
def audit_summary():
    try:
        c = conn(); rows = [dict(r) for r in c.execute("SELECT * FROM audit")]; c.close()
    except Exception: return {}
    by = collections.defaultdict(lambda: dict(n=0, missed=0))
    miss = []
    for r in rows:
        b = by[r["reason"]]; b["n"] += 1
        if r["kill_px"] and r["later_px"] >= r["kill_px"] * 2: b["missed"] += 1; miss.append(r["mint"])
    fp = [p for p in _closed() if p["pnl"] < 0 and p["reason"] in ("dev_sell", "lp_pull")]
    return dict(by_reason=dict(by), missed_winners=len(miss), missed_sample=[m[:8] for m in miss[:5]], false_passes=len(fp))
# 98 calibration / 99 drift
def calibration():
    buys = _buys(); bins = collections.defaultdict(lambda: [0, 0])
    for p in _closed():
        wp = buys.get(p["mint"], {}).get("win_prob")
        if wp is None: continue
        b = f"{int(wp*10)*10}-{int(wp*10)*10+10}%"; bins[b][0] += 1; bins[b][1] += p["pnl"] > 0
    return {k: dict(n=v[0], actual=round(v[1] / v[0], 2)) for k, v in sorted(bins.items())}
def drift():
    cl = sorted(_closed(), key=lambda p: p["closed"])
    if len(cl) < 20: return dict(alarm=False, note=f"needs 20 trades ({len(cl)})")
    rec, old = cl[-10:], cl[:-10]; wr = lambda x: sum(p["pnl"] > 0 for p in x) / len(x)
    alarm = wr(rec) < wr(old) - 0.25
    if alarm: log("drift_alarm", recent=wr(rec), before=wr(old))
    return dict(alarm=alarm, recent_wr=round(wr(rec), 2), prior_wr=round(wr(old), 2))
# 90/96/100: nightly backtest, weekly report, lessons
def nightly():
    import backtest
    bt = backtest.run(); b = bt.get("best_threshold"); rep = dict(at=time.strftime("%F %T"), backtest=bt)
    if b and abs(b - CFG["MIN_SCORE"]) >= 0.05: rep["suggest"] = f"backtest favors MIN_SCORE {b}; NOT auto-applied (needs champion/challenger proof)"
    json.dump(rep, open(os.path.join(D, "nightly_backtest.json"), "w"), indent=1); log("nightly_backtest", best=b)
def weekly_report():
    cl = [p for p in _closed() if p["closed"] > time.time() - 7 * 86400]
    txt = f"RYDER weekly self-report ({time.strftime('%F')}) PAPER ONLY\nTrades {len(cl)}, wins {sum(p['pnl']>0 for p in cl)}, P&L ${sum(p['pnl'] for p in cl):.2f}\n"
    txt += "Lessons:\n" + "\n".join("- " + l for l in lessons()) + "\n"
    open(os.path.join(D, "weekly_report.txt"), "w").write(txt)
def lessons():
    out = []; mem = memory()
    for k, s in sorted(mem.items(), key=lambda kv: -kv[1]["n"])[:20]:
        if s["n"] >= 4 and s["w"] / s["n"] <= 0.2: out.append(f"{k} is losing ({s['w']}/{s['n']} wins, ${s['pnl']})")
        elif s["n"] >= 4 and s["w"] / s["n"] >= 0.6: out.append(f"{k} is working ({s['w']}/{s['n']} wins, ${s['pnl']})")
    a = audit_summary()
    for r, b in (a.get("by_reason") or {}).items():
        if b["n"] >= 10 and b["missed"] / b["n"] > 0.15: out.append(f"kill reason '{r}' missed {b['missed']}/{b['n']} later 2x coins; may be too strict")
    c = conn(); pm = [json.loads(r[0]).get("lesson") for r in c.execute("SELECT data FROM events WHERE kind='postmortem' AND version=? ORDER BY ts DESC LIMIT 20", (CFG["VERSION"],))]; c.close()
    for l, n in collections.Counter(pm).most_common(2):
        if l and l != "clean" and n >= 2: out.append(f"{n} recent trades: {l}")
    return out or ["not enough trades yet to learn lessons"]
