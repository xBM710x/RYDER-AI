"""Upgrades 121-160 (PAPER ONLY; public read-only data; no wallets, keys or signing).
121-140: detection/speed/reliability helpers. 141-160: the agent council (shared brain, per-agent confidence, Risk veto, learning)."""
import time, json, math, os, threading, collections, statistics
from common import CFG
from logger import conn, log
D = os.path.dirname(os.path.abspath(__file__)); SB = os.path.join(D, "shared_brain.json"); _L = threading.Lock()
STATS = collections.Counter()
AGENTS = ["scout", "filter", "analyst", "executor", "risk", "logger"]
# ---------- 140 result caching (short TTL, thread-safe) ----------
_C = {}
HS = {}  # mint -> holder scores
def cached(key, ttl, fn):
    now = time.time(); v = _C.get(key)
    if v and now - v[0] < ttl: STATS["cache_hit"] += 1; return v[1]
    r = fn(); _C[key] = (now, r); STATS["cache_miss"] += 1
    if len(_C) > 4000:
        for k in [k for k, (t, _) in list(_C.items()) if now - t > 600]: _C.pop(k, None)
    return r
# ---------- 138 instant re-reject cache ----------
REJ = {}  # mint -> (ts, reason)
def rejected(m):
    r = REJ.get(m)
    if r and time.time() - r[0] < 3600: STATS["rereject"] += 1; return r[1]
def reject(m, reason):
    if reason not in ("volume_1h", "liquidity", "recheck"): REJ[m] = (time.time(), reason)
    if len(REJ) > 20000: [REJ.pop(k) for k in list(REJ)[:5000]]
# ---------- 121 graduation snipe watchlist ----------
WATCH = {}  # mint -> launch ts (seen on pump.fun bonding curve)
def watch_launch(mint): WATCH[mint] = time.time(); [WATCH.pop(k) for k in [k for k, t in list(WATCH.items()) if time.time() - t > 6 * 3600]]
def graduated(mint):
    if mint in WATCH: STATS["grad_watch_hit"] += 1; return True
    return False
# ---------- 122 source freshness scoring ----------
def source_score(cd):
    src = cd.get("source", ""); age = time.time() - (cd.get("t") or time.time())
    base = {"pumpportal-migration": 0.9, "pumpportal-ws": 0.75, "geckoterminal": 0.6, "dexscreener": 0.5}.get(src, 0.5)
    return round(max(0.2, base - min(0.3, age / 600)), 2)
# ---------- 124 5s volume spike / 137 buy-sell pressure (tick buffer from DexScreener m5 counters) ----------
TK = collections.defaultdict(lambda: collections.deque(maxlen=120))
def tick(mint, pair):
    t5 = ((pair.get("txns") or {}).get("m5") or {}); v5 = ((pair.get("volume") or {}).get("m5") or 0)
    TK[mint].append((time.time(), float(pair.get("priceUsd") or 0), t5.get("buys") or 0, t5.get("sells") or 0, v5))
def spike(mint, win=5):
    q = TK.get(mint)
    if not q or len(q) < 2: return dict(buys=0, sells=0, vol=0, px=0)
    old = next((x for x in q if q[-1][0] - x[0] <= win), q[0]); new = q[-1]
    return dict(buys=max(0, new[2] - old[2]), sells=max(0, new[3] - old[3]), vol=round(max(0, new[4] - old[4])), px=round((new[1] / old[1] - 1) * 100, 2) if old[1] else 0)
def pressure(pair):
    tx = pair.get("txns") or {}; m5, h1 = tx.get("m5") or {}, tx.get("h1") or {}
    b5, s5, bh, sh = m5.get("buys") or 0, m5.get("sells") or 0, h1.get("buys") or 0, h1.get("sells") or 0
    return round(0.6 * b5 / max(1, b5 + s5) + 0.4 * bh / max(1, bh + sh), 3)
# ---------- 125/126/134 bundle, sniper, holder-concentration scores (RugCheck report already fetched) ----------
def holder_scores(rc):
    if not rc: return {}
    known = rc.get("knownAccounts") or {}
    th = [h for h in rc.get("topHolders") or [] if (known.get(h.get("owner")) or {}).get("type") not in ("AMM", "LOCKER")]
    top10 = sum(h.get("pct", 0) for h in th[:10]); top1 = max([h.get("pct", 0) for h in th] or [0])
    snipers = sum(1 for h in th[:20] if 1.5 <= (h.get("pct") or 0) <= 4.0)  # 126: equal-sized early mid bags = sniper pattern
    eq = [round(h.get("pct", 0), 1) for h in th[:20] if h.get("pct", 0) >= 0.5]
    same = max([eq.count(x) for x in set(eq)] or [0])  # 125: identical bag sizes = bundled buys
    conc = round(max(0, 1 - top10 / 40) * (0.5 if top1 > 8 else 1), 3)  # 134 (1 good .. 0 bad)
    return dict(top10=round(top10, 1), top1=round(top1, 1), snipers=snipers, bundle_same=same, conc_score=conc)
def holder_verdict(hs):
    if not hs: return None
    if hs["bundle_same"] >= 5: return "bundle_sizes", f"{hs['bundle_same']} top wallets hold identical bags (bundled)"
    if hs["snipers"] >= 6: return "sniper_wallets", f"{hs['snipers']} sniper-sized wallets in top 20"
    return None
# ---------- 127 dev rug-history score ----------
def dev_score(creator):
    if not creator: return 0.5
    c = conn()
    try:
        bad = c.execute("SELECT COUNT(*) FROM rug_wallets WHERE wallet=?", (creator,)).fetchone()[0]
    except Exception: bad = 0
    try: n = c.execute("SELECT COUNT(*) FROM creators WHERE creator=?", (creator,)).fetchone()[0]
    except Exception: n = 0
    c.close()
    return round(max(0, 0.7 - 0.5 * bad - 0.05 * max(0, n - 1)), 2)
# ---------- 133 time-of-day / 135 age vs volume hype / 136 wash ----------
def tod_score():
    h = time.localtime().tm_hour; c = conn()
    r = [x["pnl"] for x in c.execute("SELECT pnl,closed FROM positions WHERE status='closed' AND version=?", (CFG["VERSION"],)) if time.localtime(x["closed"]).tm_hour == h]; c.close()
    return 0.5 if len(r) < 3 else round(sum(p > 0 for p in r) / len(r), 2)
def hype(pair):
    age = max(1, (time.time() * 1000 - (pair.get("pairCreatedAt") or time.time() * 1000)) / 60000)
    v1 = (pair.get("volume") or {}).get("h1") or 0; liq = (pair.get("liquidity") or {}).get("usd") or 1
    if age < 15 and v1 > 40 * liq: return "fake_hype", f"{age:.0f} min old but 1h vol is {v1/liq:.0f}x liquidity"
    return None
def wash(pair):
    tx = (pair.get("txns") or {}).get("h1") or {}; n = (tx.get("buys") or 0) + (tx.get("sells") or 0); v = (pair.get("volume") or {}).get("h1") or 0
    if n > 300 and v / n < 15: return "wash_trades", f"{n} txs/1h averaging ${v/n:.0f} (bot churn)"
    b, s = tx.get("buys") or 0, tx.get("sells") or 0
    if n > 200 and abs(b - s) / n < 0.02: return "wash_trades", f"buys {b} ≈ sells {s} (mirror trading)"
    return None
# ---------- 132 cooldown after 2 losses ----------
def two_loss_cooldown():
    c = conn(); r = [x for x in c.execute("SELECT pnl,closed FROM positions WHERE status='closed' AND version=? AND reason!='partial_tp' ORDER BY closed DESC LIMIT 2", (CFG["VERSION"],))]; c.close()
    if len(r) == 2 and all(x["pnl"] < 0 for x in r) and time.time() - r[0]["closed"] < 900: return "15 min cooldown after 2 straight losses"
# ---------- 129 momentum-widening trail / 130 tiers 20/50/100 ----------
def trail_pct(base, pair, peak_gain):
    m5 = ((pair.get("priceChange") or {}).get("m5") or 0); w = base
    if m5 > 10: w += 0.03
    if peak_gain > 0.5: w += 0.02
    return round(min(0.18, w), 3)
TIERS = (1.20, 1.50, 2.00)
# ---------- 155 market-wide dump pause ----------
def market_dump(regime):
    if (regime or {}).get("sol_h1", 0) <= -3: return f"market dump: SOL {regime['sol_h1']}% 1h"
    c = conn(); r = [x["kind"] for x in c.execute("SELECT kind,data FROM events WHERE kind='paper_exit' AND ts>?", (time.time() - 1800,))]; c.close()
    return None
# ---------- 139 per-minute self-heal ----------
def selfheal(threads, restart):
    from common import HEALTH
    out = {}
    for name, th in threads.items():
        if not th.is_alive(): restart(name); STATS["heal_" + name] += 1; log("selfheal", what=name); out[name] = "restarted"
    for h, v in HEALTH.items():
        if v["err"] > 20 and v["err"] > 3 * v["ok"]: out[h] = "degraded"
    try: c = conn(); c.execute("PRAGMA journal_mode=WAL"); c.close()
    except Exception: out["db"] = "busy"
    return out
# ================= 141-160 agent council =================
DEF = dict(trust={a: 1.0 for a in AGENTS}, grades={a: [0, 0] for a in AGENTS}, thresholds=dict(min_consensus=0.55, veto=0.25, min_liq=CFG["MIN_LIQ"]),
           patterns={}, rule_stats={}, exit_hold_min=None, lessons=[], reviewed=0, regime_mode="normal")
def load():  # 141 shared brain every agent reads
    try: b = json.load(open(SB))
    except Exception: b = {}
    for k, v in DEF.items(): b.setdefault(k, json.loads(json.dumps(v)))
    return b
def save(b):
    with _L: json.dump(b, open(SB + ".tmp", "w"), indent=1); os.replace(SB + ".tmp", SB)
BRAIN = load()
def pattern_key(cd, pair):  # 144
    st = (pair.get("dexId") or "?"); age = (time.time() * 1000 - (pair.get("pairCreatedAt") or 0)) / 60000
    return f"{cd.get('source','?')}|{st}|{'<30m' if age < 30 else '<3h' if age < 180 else 'old'}"
def narrative(sym):  # 156
    import extras; return extras.narrative(sym or "")
def votes(cd, pair, res, score, wp, conf, rc_scores, ctx):
    """142: each agent returns a confidence 0..1 plus a one-line reason."""
    v = {}; pk = pattern_key(cd, pair); ps = BRAIN["patterns"].get(pk, [0, 0])
    v["scout"] = (round(0.5 * source_score(cd) + 0.5 * ((ps[1] + 1) / (ps[0] + 2)), 3), f"{cd.get('source')} pattern {pk} {ps[1]}/{ps[0]} wins")
    unver = sum(1 for x in res.values() if isinstance(x, tuple) and x[2] in ("unverified", "rugcheck-approx-fallback"))
    fc = 0.9 - 0.1 * unver; hs = rc_scores or {}
    if hs: fc = 0.5 * fc + 0.5 * hs.get("conc_score", 0.5)
    v["filter"] = (round(max(0, fc), 3), f"{unver} unverified checks, top10 {hs.get('top10','?')}%")
    v["analyst"] = (round(0.5 * score + 0.5 * wp, 3), f"score {score}, win prob {wp}")
    liq = (pair.get("liquidity") or {}).get("usd") or 0; imp = ctx.get("impact")
    ec = min(1, liq / 100_000) * (1 - min(1, (imp or 0) / 3)) * (0.6 + 0.4 * pressure(pair))
    v["executor"] = (round(ec, 3), f"liq ${liq:,.0f}, impact {imp if imp is not None else '?'}%, pressure {pressure(pair)}")
    rk = 1.0; why = []
    if ctx.get("open", 0) >= 2: rk -= 0.25; why.append(f"{ctx['open']} open")
    if ctx.get("day_pnl", 0) < -0.05 * CFG["START_BALANCE"]: rk -= 0.4; why.append("day down >5%")
    if ctx.get("regime") == "risk-off": rk -= 0.3; why.append("risk-off market")
    rk -= 0.3 * (1 - dev_score(ctx.get("creator")))
    v["risk"] = (round(max(0, rk), 3), ", ".join(why) or "portfolio ok")
    v["logger"] = (round(0.5 * tod_score() + 0.5 * ctx.get("lesson_score", 0.5), 3), f"hour win rate {tod_score()}, lessons {ctx.get('lesson_score', 0.5)}")
    return v
def decide(v):
    """143/150: trust-weighted vote; Risk (and any agent below veto line) can veto. Returns (go, consensus, size_mult, reason)."""
    tr = BRAIN["trust"]; th = BRAIN["thresholds"]
    if BRAIN["regime_mode"] == "defensive": th = dict(th, min_consensus=th["min_consensus"] + 0.05)  # 152
    cons = sum(tr[a] * v[a][0] for a in v) / sum(tr[a] for a in v)
    sd = statistics.pstdev([x[0] for x in v.values()])
    if v["risk"][0] < th["veto"]: return False, cons, 0, f"RISK VETO ({v['risk'][1]})"
    low = [a for a in v if v[a][0] < th["veto"] * 0.6 and tr[a] >= 1.0]
    if low: return False, cons, 0, f"{low[0].upper()} veto ({v[low[0]][1]})"
    if cons < th["min_consensus"]: return False, cons, 0, f"consensus {cons:.2f} < {th['min_consensus']:.2f}"
    size = max(0.4, min(1.25, 0.5 + (cons - th["min_consensus"]) * 3)) * (0.8 if sd > 0.2 else 1)  # 131 confidence sizing
    return True, round(cons, 3), round(size, 2), f"council {cons:.2f} ({'split' if sd > 0.2 else 'agree'})"
def one_line(sym, v, cons, reason):  # 146/157
    best = max(v, key=lambda a: v[a][0]); worst = min(v, key=lambda a: v[a][0])
    return f"{sym}: {reason}; strongest {best} {v[best][0]:.2f} ({v[best][1][:50]}), weakest {worst} {v[worst][0]:.2f}"
def second_opinion(cons):  # 151
    return abs(cons - BRAIN["thresholds"]["min_consensus"]) < 0.04
def learn(trade_votes, pnl, cdpk=None, hold_min=None):
    """150/160: grade agents on the realised outcome, update trust, Scout patterns, learned exit timing."""
    win = pnl > 0
    for a, (c, _) in (trade_votes or {}).items():
        right = (c >= 0.5) == win; g = BRAIN["grades"].setdefault(a, [0, 0]); g[0] += 1; g[1] += right
        BRAIN["trust"][a] = round(max(0.5, min(1.5, 0.5 + (g[1] + 1) / (g[0] + 2))), 3)
    if cdpk: p = BRAIN["patterns"].setdefault(cdpk, [0, 0]); p[0] += 1; p[1] += win
    if hold_min is not None and win:  # 154 learned exit timing (EMA of winning hold time)
        e = BRAIN["exit_hold_min"]; BRAIN["exit_hold_min"] = round(hold_min if e is None else e * 0.8 + hold_min * 0.2, 1)
    save(BRAIN)
def rule_hit(rule, killed_px=None):  # 158 track how often each rule fires
    s = BRAIN["rule_stats"].setdefault(rule, dict(n=0, missed_winners=0, active=True)); s["n"] += 1
def shadow(kills):
    """153: re-price coins we skipped ~1h ago; if a rule keeps killing coins that then pump >50%, count it as a missed winner."""
    from common import dex_market
    if not kills: return 0
    mk = dex_market([k[0] for k in kills]); n = 0
    for m, rule, px in kills:
        q = float((mk.get(m) or {}).get("priceUsd") or 0)
        if px and q > px * 1.5:
            s = BRAIN["rule_stats"].setdefault(rule, dict(n=0, missed_winners=0, active=True)); s["missed_winners"] += 1; n += 1
    save(BRAIN); return n
SOFT = {"socials", "dump_pattern", "score<0.6", "fake_hype", "sniper_wallets"}  # only soft heuristics may be pruned; safety checks never
def pruned(rule):  # 158
    s = BRAIN["rule_stats"].get(rule) or {}
    return rule in SOFT and s.get("n", 0) >= 40 and s.get("missed_winners", 0) / max(1, s["n"]) > 0.25
def nightly_review():
    """159/145/149: retune consensus + liquidity thresholds from closed trades, refresh lessons."""
    c = conn(); V = CFG["VERSION"]
    cl = [dict(x) for x in c.execute("SELECT * FROM positions WHERE status='closed' AND version=? AND reason!='partial_tp'", (V,))]
    buys = {r["mint"]: json.loads(r["data"]) for r in c.execute("SELECT mint,data FROM events WHERE kind='paper_buy' AND version=?", (V,))}; c.close()
    th = BRAIN["thresholds"]; les = []
    cs = [(buys.get(p["mint"], {}).get("council", {}).get("consensus"), p["pnl"]) for p in cl]; cs = [x for x in cs if x[0] is not None]
    if len(cs) >= 6:
        lo = [p for c_, p in cs if c_ < th["min_consensus"] + 0.08]
        if lo and sum(lo) < 0: th["min_consensus"] = round(min(0.75, th["min_consensus"] + 0.02), 3); les.append("low-consensus trades lost: raised bar")
        elif sum(p for _, p in cs) > 0: th["min_consensus"] = round(max(0.5, th["min_consensus"] - 0.01), 3); les.append("council profitable: bar eased slightly")
    lq = [(buys.get(p["mint"], {}).get("liq") or 0, p["pnl"]) for p in cl]
    thin = [p for l, p in lq if l and l < th["min_liq"] * 1.5]
    if len(thin) >= 4 and sum(thin) < 0: th["min_liq"] = int(min(60_000, th["min_liq"] * 1.15)); les.append(f"thin-liq entries lost: min liq -> ${th['min_liq']:,}")
    rs = collections.Counter(p["reason"] for p in cl if p["pnl"] < 0)
    if rs: les.append(f"most common losing exit: {rs.most_common(1)[0][0]}")
    BRAIN["lessons"] = (les + BRAIN["lessons"])[:10]; BRAIN["reviewed"] = time.time(); save(BRAIN)
    log("self_review", thresholds=th, lessons=les, trust=BRAIN["trust"]); return les
def lesson_score():  # 149
    return 0.4 if any("lost" in l for l in BRAIN["lessons"][:3]) else 0.55
def set_regime(reg):  # 152
    BRAIN["regime_mode"] = "defensive" if (reg or {}).get("mood") == "risk-off" else "aggressive" if (reg or {}).get("mood") == "hot" else "normal"
def summary():
    return dict(trust=BRAIN["trust"], thresholds=BRAIN["thresholds"], regime_mode=BRAIN["regime_mode"], exit_hold_min=BRAIN["exit_hold_min"],
                lessons=BRAIN["lessons"][:3], patterns=len(BRAIN["patterns"]), stats=dict(STATS))
