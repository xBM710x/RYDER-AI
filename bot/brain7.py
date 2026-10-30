"""RYDER upgrades 261-360 (PAPER ONLY). Reads public market data + the local paper DB. No wallets, keys, signing or real orders."""
import time, json, os, re, math, threading, collections
from common import CFG, dex_market, http_json
from logger import conn, log
D = os.path.dirname(os.path.abspath(__file__)); SF = os.path.join(D, "brain7.json"); _LK = threading.Lock()
DEF = dict(checks={}, tod={}, nm={}, calib=[], journal={}, changes=[], best_skip=None, src={}, dex={}, age={}, exitr={}, mae=[], mfe=[], hold={},
           rugfeat=[], lessons=[], mistakes={}, tight={}, agents={}, pause_until=0, stats={})
def _load():
    try: d = json.load(open(SF))
    except Exception: d = {}
    for k, v in DEF.items(): d.setdefault(k, json.loads(json.dumps(v)))
    return d
S = _load(); STATS = collections.Counter()
def save():
    with _LK:
        tmp = SF + ".tmp"; json.dump(S, open(tmp, "w"), default=str); os.replace(tmp, SF)
def clamp(x, lo, hi): return max(lo, min(hi, x))
def _f(x):
    try: return float(x or 0)
    except Exception: return 0.0
def age_min(pair): return max(0.0, (time.time() * 1000 - (pair.get("pairCreatedAt") or time.time() * 1000)) / 60000) if pair else 0.0
def _tx(pair, k): t = ((pair or {}).get("txns") or {}).get(k) or {}; return t.get("buys") or 0, t.get("sells") or 0
def _vol(pair, k): return _f(((pair or {}).get("volume") or {}).get(k))
def _liq(pair): return _f(((pair or {}).get("liquidity") or {}).get("usd"))
def _ticks(m):
    import brain2; return list(brain2.TK.get(m) or [])
def _closed(ver="v3", days=30):
    c = conn(); r = [dict(x) for x in c.execute("SELECT * FROM positions WHERE status='closed' AND version=? AND reason!='partial_tp' AND closed>? ORDER BY closed", (ver, time.time() - days * 86400))]; c.close(); return r
# ======================= 261-280 =======================
def confirm_buyers(m, age_s):
    """261: after 20-60s, fast-track only if fresh buyers keep coming (buys outpace sells, price not fading). Returns 'fast' | 'wait' | 'weak'."""
    tk = _ticks(m)
    if len(tk) < 3 or age_s < 20: return "wait"
    a, b = tk[0], tk[-1]; buys, sells = max(0, b[2] - a[2]), max(0, b[3] - a[3]); px = (b[1] / a[1] - 1) if a[1] else 0
    if age_s <= 60 and buys >= 4 and buys >= 1.5 * max(1, sells) and px > -0.02: STATS["261_fast"] += 1; return "fast"
    if age_s >= 60 and buys < sells: return "weak"
    return "wait"
def holds_level(m):
    """262: is price holding a level (tight range near recent median) or a spike that is already fading?"""
    tk = [x for x in _ticks(m) if x[1]]
    if len(tk) < 4: return "unknown", "not enough ticks"
    px = [x[1] for x in tk]; hi = max(px); med = sorted(px)[len(px) // 2]; last = px[-1]
    if hi > px[0] * 1.15 and last < hi * 0.92: return "spike_fade", f"spiked {(hi/px[0]-1)*100:.0f}% then faded {(last/hi-1)*100:.0f}%"
    if abs(last / med - 1) <= 0.04: return "holding", f"holding within 4% of {med:.3g}"
    return "moving", f"last {(last/med-1)*100:+.1f}% vs median"
def early_sellers(pair):
    """263 (partial: no per-wallet trade stream on the free tier): very young coin where sells already outnumber buys -> first buyers are dumping."""
    if not pair or age_min(pair) > 20: return None
    b5, s5 = _tx(pair, "m5"); bh, sh = _tx(pair, "h1")
    if sh >= 15 and sh > 1.2 * bh: return f"early sellers: {sh} sells vs {bh} buys in first {age_min(pair):.0f} min"
    if s5 >= 10 and s5 > 1.5 * b5: return f"early sellers: {s5} sells vs {b5} buys last 5 min"
    return None
LIQ0 = {}
def liq_growth(m, pair):
    """264: liquidity growth rate ($/min since first seen); returns score adj -0.03..+0.04."""
    l = _liq(pair); now = time.time()
    if m not in LIQ0: LIQ0[m] = (now, l); return 0.0, None
    t0, l0 = LIQ0[m]; mins = (now - t0) / 60
    if mins < 0.5 or not l0: return 0.0, None
    g = (l / l0 - 1) / mins
    return (round(clamp(g * 0.4, -0.03, 0.04), 3), round(g * 100, 1))
def conc_penalty(res):
    """265: graded holder-concentration penalty (hard 25% top10 cap still applies in Filter)."""
    try: t10 = float(re.search(r"([\d.]+)%", str((res.get("top10") or ("", ""))[1])).group(1))
    except Exception: return 0.0, None
    return -round(clamp((t10 - 12) * 0.004, 0, 0.05), 3), t10
def holder_velocity(rate):
    """266: new holders per minute in the first minutes -> score adj."""
    r = _f(rate)
    return round(0.04 if r >= 8 else 0.02 if r >= 4 else -0.02 if r < 1 else 0.0, 3)
def dip_entry(m, pair, waited_s):
    """267: after a big launch candle (m5 > +30%), only buy the first 5-20% dip from the wait high; never chase. 'ok'|'wait'|'skip'."""
    m5 = _f(((pair or {}).get("priceChange") or {}).get("m5"))
    if m5 < 30: return "ok", None
    px = [x[1] for x in _ticks(m) if x[1]]
    if not px: return "wait", "no ticks yet"
    hi, last = max(px), px[-1]; dd = last / hi - 1
    if -0.20 <= dd <= -0.05: STATS["267_dip"] += 1; return "ok", f"bought first dip {dd*100:.0f}% after +{m5:.0f}% candle"
    if dd < -0.20: return "skip", f"dip too deep {dd*100:.0f}% after launch candle"
    return ("wait" if waited_s < 210 else "skip"), f"waiting for first dip (m5 +{m5:.0f}%)"
def pregrad_guard(pair):
    """268: don't buy a pump.fun coin in the last stretch before graduation (mcap ~$55k+ on the curve) - migration dumps are common."""
    if (pair or {}).get("dexId") in ("pumpfun", "pump-fun") and 55_000 <= _f(pair.get("marketCap") or pair.get("fdv")) < 90_000:
        return f"about to graduate (mcap ${_f(pair.get('marketCap') or pair.get('fdv')):,.0f} on curve)"
    return None
def serial_launcher(creator):
    """269: creator launched >=3 coins in 24h -> penalty; >=6 -> kill."""
    if not creator: return 0.0, None
    c = conn(); n = c.execute("SELECT COUNT(*) FROM creators WHERE creator=? AND ts>?", (creator, time.time() - 86400)).fetchone()[0]; c.close()
    if n >= 6: return None, f"serial launcher: {n} coins in 24h"
    return (-0.06 if n >= 3 else 0.0), (f"{n} launches/24h" if n >= 3 else None)
def ryder_conf(score, conf, wp, cons, adj=0.0):
    """270: one combined RYDER confidence 0-1 from Analyst score, safety confidence, model win-prob and council consensus (+ learned adj)."""
    parts = [(score, 0.30), (conf, 0.25), (wp if wp is not None else 0.5, 0.20), (cons if cons is not None else score, 0.25)]
    v = sum(_f(x) * w for x, w in parts) / sum(w for _, w in parts) + adj
    return round(clamp(calibrated(v), 0, 1), 3)
def trail_tighten(base, gain):
    """271: trailing stop tightens as profit grows."""
    if base is None: return None
    f = 0.5 if gain >= 1.0 else 0.65 if gain >= 0.6 else 0.8 if gain >= 0.3 else 1.0
    return round(max(0.035, base * f), 3)
def partial15(p, price):
    """272: first partial take-profit at +15% (was +20%); rest keeps trailing."""
    return (p.get("tp_done") or 0) == 0 and price >= p["entry"] * 1.15
def buy_fade(p, price):
    """273: buying volume fading while price hasn't dropped yet -> get out early (held > 3 min, not well in profit)."""
    tk = _ticks(p["mint"])
    if time.time() - p["opened"] < 180 or len(tk) < 30 or price > p["entry"] * 1.12: return None
    now = tk[-1][0]; rec = [x for x in tk if now - x[0] <= 60]; old = [x for x in tk if 60 < now - x[0] <= 180]
    if len(rec) < 2 or len(old) < 2: return None
    rb = max(0, rec[-1][2] - rec[0][2]); ob = max(0, old[-1][2] - old[0][2]) / 2
    if ob >= 6 and rb < 0.3 * ob: return f"buys faded {rb} vs {ob:.0f}/min before"
    return None
def flat_minutes(reg):
    """274/276: time-stop for flat coins adapts to the market (cold 12 min, neutral 20, hot 25)."""
    mood = (reg or {}).get("mood"); return 12 if mood == "risk-off" else 25 if mood == "hot" else 20
def regime_trail(trail, reg):
    """276: exits adapt to the regime: risk-off tightens trail 20%, hot loosens 15%."""
    if trail is None: return None
    mood = (reg or {}).get("mood"); return round(trail * (0.8 if mood == "risk-off" else 1.15 if mood == "hot" else 1.0), 3)
def tags_for(ctx):
    """278: which signals were positive on this buy (used to learn which checks predict winners)."""
    t = []
    for k, cond in (("liq_growing", (ctx.get("liq_g") or 0) > 0.01), ("holders_fast", (ctx.get("hv") or 0) > 0), ("buyers_confirmed", ctx.get("fast")),
                    ("dip_entry", ctx.get("dip")), ("low_conc", (ctx.get("t10") or 99) < 15), ("boosted", ctx.get("boosted")), ("holding_level", ctx.get("hold") == "holding"),
                    ("young", age_min(ctx.get("pair")) < 30), ("pumpfun", (ctx.get("pair") or {}).get("dexId") in ("pumpfun", "pump-fun"))):
        if cond: t.append(k)
    return t
def learned_adj(tags):
    """277/278: learned weight per signal from closed trades (bounded +-0.05 each, +-0.10 total, needs >=5 trades per tag)."""
    a = 0.0
    for t in tags:
        w, n = S["checks"].get(t, [0, 0])
        if n >= 5: a += clamp((w / n - 0.5) * 0.2, -0.05, 0.05)
    return round(clamp(a, -0.10, 0.10), 3)
def tod_adj():
    """279: hour-of-day learning: weak hours -> more careful (score -0.04, size x0.7); strong hours small boost."""
    w, n = S["tod"].get(str(time.localtime().tm_hour), [0, 0])
    if n < 5: return 0.0, 1.0
    wr = w / n; return ((-0.04, 0.7) if wr < 0.35 else (0.02, 1.0) if wr > 0.6 else (0.0, 1.0))
def journal_buy(m, d):
    S["journal"][m] = dict(d, t=time.time())
    if len(S["journal"]) > 400:
        for k in sorted(S["journal"], key=lambda k: S["journal"][k].get("t", 0))[:100]: S["journal"].pop(k, None)
    save()
def review(pos, tot):
    """277: post-trade review -> update signal weights, hour-of-day, calibration, source/dex/age stats, MAE/MFE, exit stats (all bounded)."""
    try:
        j = S["journal"].get(pos["mint"]) or {}; win = tot > 0; wt = (0.25 if __import__("fomo").is_fomo(pos["mint"]) else 0.5) if pos.get("version") == "v3x" else 1.0  # 415
        if pos.get("version") not in ("v3", "v3x"): return
        for t in j.get("tags", []): x = S["checks"].setdefault(t, [0, 0]); x[0] += win * wt; x[1] += wt
        h = str(time.localtime(pos["opened"]).tm_hour); x = S["tod"].setdefault(h, [0, 0]); x[0] += win * wt; x[1] += wt
        if j.get("rc") is not None: S["calib"] = (S["calib"] + [[j["rc"], int(win)]])[-300:]
        for key, val in (("src", j.get("source")), ("dex", j.get("dex")), ("age", j.get("age_b"))):
            if val: x = S[key].setdefault(str(val), [0, 0, 0.0]); x[0] += win; x[1] += 1; x[2] = round(x[2] + tot, 2)
        r = pos.get("reason") or "?"; x = S["exitr"].setdefault(r, [0, 0.0]); x[0] += 1; x[1] = round(x[1] + tot, 2)
        S["mfe"] = (S["mfe"] + [round((pos.get("peak") or pos["entry"]) / pos["entry"] - 1, 3)])[-200:]
        if win: S["mae"] = (S["mae"] + [j.get("mae", 0)])[-200:]
        hm = (time.time() - pos["opened"]) / 60; b = j.get("bucket") or "any"; x = S["hold"].setdefault(b, [0, 0.0]); x[0] += 1; x[1] = round(x[1] + (hm if win else 0), 1)
        mistake_learn(pos, tot, j); save()
        log("review", pos["mint"], pos.get("symbol"), win=win, pnl=round(tot, 2), tags=j.get("tags"), rc=j.get("rc"), label=label(pos, tot, j))
    except Exception as e: log("error", where="brain7.review", trace=str(e)[:200])
def nearmiss_learn():
    """280: did near-miss / skipped coins win? (re-priced ~1h later by counterfactual job) -> per-rule win rate."""
    c = conn(); rows = c.execute("SELECT rule, pct FROM counterfactual WHERE ts>?", (time.time() - 7 * 86400,)).fetchall(); c.close()
    nm = {}
    for r in rows:
        x = nm.setdefault(r[0] or "?", [0, 0, 0.0]); x[1] += 1; x[0] += (r[1] or 0) >= 30; x[2] += clamp(r[1] or 0, -100, 500)
    S["nm"] = {k: [v[0], v[1], round(v[2] / max(1, v[1]), 1)] for k, v in nm.items()}; save(); return S["nm"]
# ======================= 281-300 =======================
SOFT_RULES = {"liquidity": ("min_liq", 15_000, 25_000), "volume_1h": ("min_vol_h1", 22_000, 40_000)}
def replay(rule, factor):
    """282: replay recent skipped coins (counterfactual table, re-priced ~1h later) under a candidate rule change.
    Estimates extra winners vs extra losers admitted. Returns (net_score, n_win, n_lose)."""
    c = conn(); rows = c.execute("SELECT pct FROM counterfactual WHERE rule=? AND ts>?", (rule, time.time() - 86400)).fetchall(); c.close()
    if len(rows) < 15: return None, 0, 0
    share = clamp(1 - factor, 0.05, 0.3) * 2  # rough share of skipped coins a looser bar would admit
    win = [r[0] for r in rows if (r[0] or 0) >= 15]; lose = [r[0] for r in rows if (r[0] or 0) <= -20]
    net = share * (sum(min(x, 60) for x in win) * 0.5 - len(lose) * 8)  # winners: ~half the move captured (cap 60%); losers: stopped near -8%
    return round(net, 1), round(len(win) * share), round(len(lose) * share)
def regret_tune():
    """281: regret score per soft rule. If a rule keeps skipping coins that later win AND the nightly replay (282) says loosening is net
    positive, loosen that bar 5% (bounded floors, at most once per 6h). If skipped coins mostly lose, step back toward base. Hard safety rules never touched."""
    import brain2; th = brain2.BRAIN["thresholds"]; out = []
    for rule, (key, floor, ceil) in SOFT_RULES.items():
        w, n, avg = (S["nm"].get(rule) or [0, 0, 0])
        if n < 20: continue
        regret = w / n; last = next((x for x in reversed(S["changes"]) if x.get("rule") == rule), {})
        if time.time() - last.get("t", 0) < 6 * 3600: continue
        cur = th.get(key, CFG["MIN_LIQ"] if key == "min_liq" else CFG["MIN_VOL_H1"])
        if regret >= 0.30:
            net, nw, nl = replay(rule, 0.95)
            if net is not None and net > 0 and cur * 0.95 >= floor:
                new = round(cur * 0.95); th[key] = new; out.append(dict(rule=rule, key=key, old=cur, new=new, regret=round(regret, 2), replay=net, t=time.time()))
        elif regret <= 0.08 and cur * 1.05 <= ceil:
            new = round(cur * 1.05); th[key] = new; out.append(dict(rule=rule, key=key, old=cur, new=new, regret=round(regret, 2), replay=None, t=time.time()))
    for x in out:
        CFG["MIN_LIQ" if x["key"] == "min_liq" else "MIN_VOL_H1"] = x["new"]; S["changes"] = (S["changes"] + [x])[-60:]; log("rule_change", **x)
    if out: brain2.save(brain2.BRAIN); save()
    return out
def agent_accuracy():
    """283: rolling 20-trade accuracy per agent (feeds the existing trust weights, bounded 0.5-1.5)."""
    c = conn(); rows = c.execute("SELECT e.data, p.pnl FROM positions p JOIN events e ON e.mint=p.mint AND e.kind='paper_buy' WHERE p.status='closed' AND p.version='v3' AND p.reason!='partial_tp' ORDER BY p.closed DESC LIMIT 20").fetchall(); c.close()
    acc = {}
    for d, pnl in rows:
        for a, v in ((json.loads(d).get("council") or {}).get("votes") or {}).items():
            x = acc.setdefault(a, [0, 0]); x[1] += 1; x[0] += (v[0] >= 0.5) == (pnl > 0)
    S["agents"] = {a: round(x[0] / x[1], 2) for a, x in acc.items() if x[1]}; save(); return S["agents"]
def borderline(v, cons, m):
    """284: Analyst vs Risk debate on borderline coins (consensus 0.50-0.62). If they disagree strongly, RYDER breaks the tie on live price action."""
    if not (0.50 <= cons <= 0.62): return True, None
    a, r = (v.get("analyst") or (0.5,))[0], (v.get("risk") or (0.5,))[0]
    if abs(a - r) < 0.25: return True, None
    st, d = holds_level(m); cb = confirm_buyers(m, 90)
    ok = st == "holding" and cb != "weak"
    return ok, f"debate analyst {a:.2f} vs risk {r:.2f} -> RYDER {'buys' if ok else 'passes'} ({d}; buyers {cb})"
def size_x(rc, ver="v3"):
    """285/286/287: confidence-scaled size x streak x proven-gate. Max 1.0x until 30+ closed main trades and >=50% win rate."""
    s = 0.6 + 1.2 * (rc - 0.5)
    cl = _closed(ver, 30); last = [p["pnl"] > 0 for p in cl[-4:]]
    wins = 0
    for w in reversed(last):
        if not w: break
        wins += 1
    s *= (1.0 + 0.08 * min(wins, 3)) if wins else (0.9 if last and not last[-1] else 1.0)
    proven = len(cl) >= 30 and sum(p["pnl"] > 0 for p in cl) / len(cl) >= 0.5
    return round(clamp(s, 0.4, 1.3 if proven else 1.0), 3)
def calibrated(v):
    """288: map raw confidence to observed win rate once >=30 graded trades exist (5 bins, blended 50/50)."""
    cal = S.get("calib") or []
    if len(cal) < 30: return v
    b = [x for x in cal if abs(x[0] - v) <= 0.1]
    if len(b) < 6: return v
    return 0.5 * v + 0.5 * sum(x[1] for x in b) / len(b)
def calib_line():
    cal = S.get("calib") or []
    if len(cal) < 10: return f"confidence calibration: {len(cal)}/30 trades graded"
    hi = [x for x in cal if x[0] >= 0.65]; lo = [x for x in cal if x[0] < 0.65]
    f = lambda q: f"{sum(x[1] for x in q)/len(q):.0%}" if q else "n/a"
    return f"confidence calibration: high-conf win {f(hi)} vs low-conf {f(lo)} ({len(cal)} trades)"
_PC = {}
def prices(mints):
    """291/292: tiny 1s price cache + fast failover to Jupiter when DexScreener stalls/misses."""
    from common import HEALTH
    now = time.time(); out = {m: v for m, (t, v) in _PC.items() if m in mints and now - t < 1.0}
    need = [m for m in mints if m not in out]
    ds = HEALTH.get("api.dexscreener.com") or {}
    stalled = ds.get("last_ok") and now - ds["last_ok"] > 30
    got = {} if stalled else dex_market(need)
    miss = [m for m in need if not (got.get(m) or {}).get("priceUsd")]
    if miss:
        try: got.update(__import__("brain6").fallback_prices(miss)); STATS["292_failover"] += len(miss)
        except Exception: pass
    for m, v in got.items(): _PC[m] = (now, v)
    if len(_PC) > 2000: _PC.clear()
    out.update(got); return out
SCAM_RX = re.compile(r"(airdrop|claim|giveaway|presale|official.*(token|coin)|v2 migration)", re.I)
def fast_reject(m, pair, sym):
    """293: sub-1s rug rejection fast path from data already in hand (no network): honeypot-shaped flow, dead pool, scam names, known rug assets.
    Also 295 (wash-trade shape from aggregates) and 296 (fuzzy copycat)."""
    t0 = time.time(); r = None
    if pair:
        bh, sh = _tx(pair, "h1"); liq = _liq(pair); mc = _f(pair.get("marketCap") or pair.get("fdv"))
        if bh >= 40 and sh == 0: r = ("honeypot_shape", f"{bh} buys and 0 sells in 1h (can't sell?)")
        elif liq >= 2000 and mc > 0 and mc / liq > 60 and pair.get("dexId") not in ("pumpfun", "pump-fun", "meteora-dbc", "raydium-launchlab"): r = ("thin_pool", f"mcap/liq {mc/liq:.0f}x")  # 363 fix: dust/curve pools left to the liquidity check
        elif SCAM_RX.search(sym or ""): r = ("scam_name", sym)
        else: r = wash_shape(pair) or copycat_fuzzy(sym, m, liq)
    STATS["293_ms"] = round((time.time() - t0) * 1000, 1)
    if r: STATS["293_fast_kills"] += 1
    return r
def wash_shape(pair):
    """295: wash-trading shape: buys ~= sells (within 4%) with lots of trades and near-identical average trade size across 5m/1h/6h."""
    bh, sh = _tx(pair, "h1"); b6, s6 = _tx(pair, "h6")
    if bh + sh < 150 or abs(bh - sh) / (bh + sh) > 0.04: return None
    if b6 + s6 < 1.5 * (bh + sh) or bh + sh < 1.5 * sum(_tx(pair, "m5")): return None  # 362 fix: young coins have identical windows -> not evidence of wash
    sizes = [(_vol(pair, k) / max(1, sum(_tx(pair, k)))) for k in ("m5", "h1", "h6") if sum(_tx(pair, k)) >= 20]
    if len(sizes) >= 2 and max(sizes) / max(1e-9, min(sizes)) < 1.06: return ("wash_shape", f"balanced flow {bh}/{sh} and uniform trade size ${min(sizes):.0f}-{max(sizes):.0f}")
    return None
def _norm(s): return re.sub(r"(\$|inu|coin|token|v\d+|2\.0|official|real|the|[^a-z])", "", (s or "").lower())
def copycat_fuzzy(sym, m, liq):
    """296: block a coin whose normalized name copies a bigger coin launched in the last hour."""
    n = _norm(sym)
    if len(n) < 3: return None
    c = conn()
    try: rows = c.execute("SELECT sym, mint, liq FROM names WHERE ts>? AND mint!=?", (time.time() - 3600, m)).fetchall()
    except Exception: rows = []
    c.close()
    for s2, m2, l2 in rows:
        if _norm(s2) == n and (l2 or 0) > max(liq * 1.5, 5000): return ("copycat", f"{sym} copies {s2} ({m2[:6]}) launched this hour with more liquidity")
    return None
def market_pause(reg, ver="v3"):
    """297: market-wide dump auto-pause (20 min): SOL -3% in 1h, or 3+ of the last 5 exits on this desk in 30 min were stops/rug exits."""
    if time.time() < S.get("pause_until", 0): return f"market dump pause ({round((S['pause_until']-time.time())/60)} min left)"
    why = None
    if _f((reg or {}).get("sol_h1")) <= -3: why = f"SOL {reg['sol_h1']}% in 1h"
    else:
        c = conn(); rs = [r[0] for r in c.execute("SELECT reason FROM positions WHERE status='closed' AND closed>? AND reason!='partial_tp' ORDER BY closed DESC LIMIT 5", (time.time() - 1800,))]; c.close()
        bad = sum(1 for r in rs if r in ("stop_loss", "lp_pull", "dev_sell", "rug_recheck", "big_sell", "sell_spike_5s", "early_stop"))
        if bad >= 3: why = f"{bad} of last {len(rs)} exits were stops/rug exits in 30 min"
    if why: S["pause_until"] = time.time() + 1200; save(); log("market_pause", reason=why); return "market dump pause: " + why
    return None
WHY = {"trailing_stop": "locked in profit as the trail caught up", "stop_loss": "hit the stop, cut the loss small", "breakeven_stop": "came back to entry, out at breakeven",
       "time_stop": "went flat too long, freed the cash", "fomo_time": "FOMO trade went flat", "fomo_tp": "hit the quick FOMO target", "dev_sell": "the dev wallet sold",
       "lp_pull": "liquidity got pulled", "volume_decay": "volume dried up", "buy_fade": "buyers faded before price did", "partial_tp": "took some profit, rest still running",
       "sell_spike_5s": "a sudden wave of sells hit", "big_sell": "a big sell hit the pool", "rug_recheck": "rug check turned bad while holding", "low_health": "position health dropped",
       "early_stop": "sell pressure near the stop, got out early", "holder_concentration": "top holders started piling up supply", "learned_time": "held past my learned best time",
       "heat_cap": "portfolio heat too high", "flat_time": "went flat too long, freed the cash"}
def why_buy(sym, rc, tags, extra=""):
    """298: one plain sentence explaining the buy."""
    good = ", ".join(t.replace("_", " ") for t in tags[:3]) or "it passed every safety check"
    return f"Bought {sym} at {rc:.0%} confidence because {good}{(' — ' + extra) if extra else ''}."
def why_exit(reason): return f"Sold because {WHY.get(reason, reason.replace('_', ' '))}."
def week_lessons():
    """299: weekly report section: what RYDER learned + every rule change this week."""
    ch = [x for x in S["changes"] if time.time() - x.get("t", 0) < 7 * 86400]
    top = sorted(((k, v[0] / v[1], v[1]) for k, v in S["checks"].items() if v[1] >= 3), key=lambda x: -x[1])
    out = "\n## What RYDER learned (upgrades 277-300)\n"
    out += "- Signals that predicted winners: " + (", ".join(f"{k} {w:.0%} ({n:.0f})" for k, w, n in top[:4]) or "not enough trades yet") + "\n"
    out += "- Rule changes: " + ("; ".join(f"{x['key']} {x['old']}->{x['new']} (regret {x['regret']})" for x in ch) or "none") + "\n"
    out += "- " + calib_line() + "\n- Near-miss win rates: " + (", ".join(f"{k} {v[0]}/{v[1]}" for k, v in S["nm"].items()) or "n/a") + "\n"
    out += "- " + __import__("brain8").funnel_line() + "\n- Rejections by gate: " + str(__import__("brain8").funnel()["gates"]) + "\n"  # 391/392
    out += "- Best skipped coin: " + (S["best_skip"] or {}).get("text", "n/a") + "\n" + "- Mistakes: " + (", ".join(f"{k} x{v}" for k, v in S["mistakes"].items()) or "none") + "\n"
    return out
def best_skipped():
    """300: Logger 'best skipped coin of the day'."""
    c = conn(); r = c.execute("SELECT c.mint, c.rule, c.pct, (SELECT symbol FROM events e WHERE e.mint=c.mint AND e.kind='kill' LIMIT 1) FROM counterfactual c WHERE c.ts>? ORDER BY c.pct DESC LIMIT 1", (time.time() - 86400,)).fetchone(); c.close()
    if not r: return None
    S["best_skip"] = dict(mint=r[0], rule=r[1], pct=r[2], sym=r[3], text=f"{r[3] or r[0][:6]} {r[2]:+.0f}% after I skipped it for {r[1]}", t=time.time()); save()
    log("best_skipped", r[0], r[3], rule=r[1], pct=r[2]); return S["best_skip"]
# ======================= 301-360 =======================
def momentum_accel(pair):
    """301: volume acceleration: last-5m volume vs 1h average per 5m."""
    v5, v1 = _vol(pair, "m5"), _vol(pair, "h1")
    if not v1: return 0.0
    r = v5 / (v1 / 12); return round(0.03 if r >= 2 else 0.015 if r >= 1.3 else -0.02 if r < 0.5 else 0.0, 3)
def ratio_trend(m):
    """302: buy/sell ratio trend across the ticks collected while waiting (+ = improving)."""
    tk = _ticks(m)
    if len(tk) < 6: return 0.0
    h = len(tk) // 2; f = lambda a, b: (max(0, b[2] - a[2]) + 1) / (max(0, b[3] - a[3]) + 1)
    r1, r2 = f(tk[0], tk[h]), f(tk[h], tk[-1]); return round(clamp((r2 - r1) * 0.01, -0.03, 0.03), 3)
def buy_size_growth(pair):
    """303: average trade size rising (5m vs 1h) = bigger buyers arriving."""
    a5 = _vol(pair, "m5") / max(1, sum(_tx(pair, "m5"))); a1 = _vol(pair, "h1") / max(1, sum(_tx(pair, "h1")))
    if sum(_tx(pair, "m5")) < 10 or not a1: return 0.0
    return round(0.02 if a5 > 1.4 * a1 else -0.02 if a5 < 0.6 * a1 else 0.0, 3)
def liq_mcap(pair):
    """304: liquidity-to-mcap health (healthy 8-40%; thinner = fragile)."""
    l, mc = _liq(pair), _f(pair.get("marketCap") or pair.get("fdv"))
    if not l or not mc or pair.get("dexId") in ("pumpfun", "pump-fun"): return 0.0
    r = l / mc; return round(0.02 if 0.08 <= r <= 0.4 else -0.03 if r < 0.04 else 0.0, 3)
def age_bucket(pair):
    a = age_min(pair); return "<15m" if a < 15 else "<1h" if a < 60 else "<6h" if a < 360 else "6h+"
def learned_bucket_adj(kind, key):
    """305/309/321/322: learned win-rate adjustment for pair-age bucket, migration source, discovery source, dex (needs >=6 trades)."""
    w, n = (S[kind].get(str(key)) or [0, 0, 0])[:2]
    if n < 6: return 0.0
    return round(clamp((w / n - 0.45) * 0.15, -0.04, 0.04), 3)
def breadth(pair):
    """306: trader breadth: many small trades (retail breadth) vs few big ones."""
    n = sum(_tx(pair, "h1")); v = _vol(pair, "h1")
    if n < 30: return -0.01
    return round(0.02 if v / n < 400 and n >= 150 else 0.0, 3)
def tick_vol(m):
    """307: realized volatility of wait ticks -> penalty for wild coins."""
    px = [x[1] for x in _ticks(m) if x[1]]
    if len(px) < 6: return 0.0
    rets = [px[i] / px[i - 1] - 1 for i in range(1, len(px))]; sd = (sum(r * r for r in rets) / len(rets)) ** 0.5
    return round(-0.03 if sd > 0.04 else -0.015 if sd > 0.02 else 0.0, 3)
def curve_progress(pair):
    """308: pump.fun bonding-curve progress (approx from mcap; graduation ~ $69-75k): sweet spot 25-55%."""
    if (pair or {}).get("dexId") not in ("pumpfun", "pump-fun"): return 0.0, None
    p = clamp(_f(pair.get("marketCap") or pair.get("fdv")) / 72_000, 0, 1)
    return (0.02 if 0.25 <= p <= 0.55 else -0.02 if p < 0.12 else 0.0), round(p * 100)
def socials_q(pair):
    """310: socials quality (website + X link + Telegram + image)."""
    info = (pair or {}).get("info") or {}; types = {(s.get("type") or "").lower() for s in info.get("socials") or []}
    n = bool(info.get("websites")) + ("twitter" in types) + ("telegram" in types) + bool(info.get("imageUrl"))
    return round({0: -0.03, 1: -0.01, 2: 0.0, 3: 0.01, 4: 0.02}[n], 3)
def paid_hype(pair):
    """311: lots of paid DexScreener boosts but little real volume -> paid-hype penalty."""
    b = _f(((pair or {}).get("boosts") or {}).get("active")); v = _vol(pair, "h1")
    return -0.03 if b >= 100 and v < 50_000 else 0.0
HEAT = collections.deque(maxlen=600)
def theme_heat(sym):
    """312: narrative heat from RYDER's own scans in the last hour (no X data)."""
    import extras; n = extras.narrative(sym) or "other"; HEAT.append((time.time(), n))
    k = sum(1 for t, x in HEAT if x == n and time.time() - t < 3600)
    return round(0.02 if n != "other" and k >= 15 else 0.0, 3)
def relaunch(sym):
    """313: same name as a coin that rugged in the last 24h -> block."""
    n = _norm(sym)
    if len(n) < 3: return None
    c = conn(); rows = c.execute("SELECT symbol FROM positions WHERE reason IN ('lp_pull','dev_sell','rug_recheck') AND closed>?", (time.time() - 86400,)).fetchall(); c.close()
    return ("relaunch", f"{sym} matches a coin that rugged today") if any(_norm(r[0]) == n for r in rows) else None
def wait_checks(m, p, pair):
    """314/315/316/317: during the entry wait: liquidity dropped >15%, one-candle volume, drawdown from wait high >12%, price far above 1h VWAP proxy."""
    l0 = p.get("liq0") or 0; l = _liq(pair)
    if l0 and l < l0 * 0.85: return "liq_drop_wait", f"liquidity fell {(l/l0-1)*100:.0f}% during wait"
    v5, v1 = _vol(pair, "m5"), _vol(pair, "h1")
    if v1 > 20_000 and v5 > 0.8 * v1 and age_min(pair) > 20: return "one_candle", "almost all 1h volume came in the last 5 min"
    px = [x[1] for x in _ticks(m) if x[1]]
    if px and px[-1] < max(px) * 0.88: return "wait_drawdown", f"{(px[-1]/max(px)-1)*100:.0f}% off wait high"
    ch1 = _f(((pair.get("priceChange") or {}).get("h1")))
    if ch1 > 150 and _f((pair.get("priceChange") or {}).get("m5")) > 25: return "above_vwap", f"+{ch1:.0f}% 1h and still ripping: price far above hour average"
    return None
def dispersion_mult(v):
    """318: agents disagree a lot -> smaller size."""
    xs = [x[0] for x in v.values()] if v else []
    if len(xs) < 3: return 1.0
    mu = sum(xs) / len(xs); sd = (sum((x - mu) ** 2 for x in xs) / len(xs)) ** 0.5
    return 0.75 if sd > 0.2 else 0.9 if sd > 0.14 else 1.0
def ev_floor(rc):
    """319: expected value from learned exit-reason outcomes; skip if clearly negative after 15+ trades."""
    ex = S["exitr"]; n = sum(v[0] for v in ex.values())
    if n < 15: return True, None
    avg = sum(v[1] for v in ex.values()) / n
    adj = avg * (0.5 + rc)
    return adj > -0.5, f"learned EV ${adj:+.2f}/trade"
def journal_ctx(m, sym, pair, tags, rc, p):
    """320: decision journal - every buy's feature snapshot for later review."""
    journal_buy(m, dict(sym=sym, tags=tags, rc=rc, source=(p.get("cd") or {}).get("source"), dex=p.get("dex"), age_b=age_bucket(pair), bucket=str(p.get("bucket")), mae=0,
                          feats={k: v for k, v in (p.get("feats") or {}).items() if isinstance(v, (int, float))}))
def mae_track(p, price):
    """324 helper: track max adverse excursion of open positions."""
    j = S["journal"].get(p["mint"])
    if j is not None: j["mae"] = round(min(j.get("mae", 0), price / p["entry"] - 1), 3)
def exit_report():
    """323: exit-reason analytics: which exits make or lose money."""
    return ", ".join(f"{k} {v[0]}x ${v[1]:+.2f}" for k, v in sorted(S["exitr"].items(), key=lambda kv: kv[1][1])[:6]) or "no exits yet"
def learned_stop(base):
    """324: stop from winners' max adverse excursion (90th pct + buffer), bounded 5-12%; needs 12 winners."""
    xs = sorted(-x for x in S["mae"] if x is not None)
    if len(xs) < 12: return base
    return round(clamp(xs[int(len(xs) * 0.9)] + 0.015, 0.05, 0.12), 3)
def learned_tp():
    """325: partial take-profit level from the MFE distribution (median peak), bounded 12-30%; needs 15 trades."""
    xs = sorted(S["mfe"])
    if len(xs) < 15: return 0.15
    return round(clamp(xs[len(xs) // 2] * 0.8, 0.12, 0.30), 3)
def learned_hold(bucket):
    """326: average winning hold time per bucket (min)."""
    n, tot = S["hold"].get(str(bucket), [0, 0]); return round(tot / n, 1) if n >= 5 else None
def reentry_ok(m):
    """327: re-entry only if buyers confirm on the pullback."""
    return confirm_buyers(m, 60) != "weak" and holds_level(m)[0] != "spike_fade"
THEME_CD = {}
def theme_cooldown(sym, reason=None):
    """328: after a rug-like exit, 15-min cooldown on that narrative."""
    import extras; n = extras.narrative(sym) or "other"
    if reason: THEME_CD[n] = time.time(); return None
    return f"cooldown on {n} theme after a rug exit" if n != "other" and time.time() - THEME_CD.get(n, 0) < 900 else None
def portfolio_guards(sym, ver, usd):
    """329/330/331/332: max 2 open in the same theme; open risk <= 6% of equity; after +10% day halve size; equity >8% below peak -> half size.
    Returns (block_reason, size_mult)."""
    import extras, executor; c = conn()
    ops = [dict(r) for r in c.execute("SELECT symbol, cost, entry, stop FROM positions WHERE status='open' AND version=?", (ver,))]
    eq = executor.equity(c, ver); d0 = time.mktime(time.localtime()[:3] + (0, 0, 0, 0, 0, -1))
    day = c.execute("SELECT COALESCE(SUM(pnl),0) FROM positions WHERE status='closed' AND version=? AND closed>=?", (ver, d0)).fetchone()[0]; c.close()
    th = extras.narrative(sym) or "other"
    if th != "other" and sum(1 for o in ops if (extras.narrative(o["symbol"]) or "other") == th) >= 2: return f"already 2 open {th} coins", 1.0
    heat = sum(o["cost"] * max(0, 1 - o["stop"] / o["entry"]) for o in ops) + usd * 0.08
    if heat > 0.06 * eq: return f"portfolio heat ${heat:.2f} > 6% of equity", 1.0
    m = 1.0
    if day >= 0.10 * CFG["START_BALANCE"]: m *= 0.5
    pk = S["stats"].get("peak_" + ver, eq); S["stats"]["peak_" + ver] = max(pk, eq)
    if eq < 0.92 * max(pk, eq): m *= 0.5
    return None, m
def slot_budget(rc, ver="v3"):
    """333: keep the last hourly slot for high-confidence coins (rc >= 0.7)."""
    c = conn(); n = c.execute("SELECT COUNT(*) FROM positions WHERE version=? AND opened>?", (ver, time.time() - 3600)).fetchone()[0]; c.close()
    return None if n < CFG["MAX_PER_HOUR"] - 1 or rc >= 0.7 else f"last slot this hour reserved for confidence >= 70% (have {rc:.0%})"
def stale_decay(p):
    """334: confidence decays the longer a signal waits (−0.01 per 30s past 90s, max −0.05)."""
    w = time.time() - p.get("t0", p["t"]); return -round(clamp((w - 90) / 30 * 0.01, 0, 0.05), 3)
DEAD = {}
def dead_skip(m):
    """335: pairs with no DexScreener data after max checks are ignored for 10 min (saves calls)."""
    return time.time() - DEAD.get(m, 0) < 600
def mark_dead(m): DEAD[m] = time.time(); len(DEAD) > 5000 and DEAD.clear()
def source_rank():
    """336: rank price sources by health/latency (reported; prices() already fails over)."""
    from common import HEALTH
    return sorted(((h, v.get("ms"), round(v["ok"] / max(1, v["ok"] + v["err"]), 2)) for h, v in HEALTH.items()), key=lambda x: (-x[2], x[1] or 9e9))[:5]
def status():
    """339: heartbeat block for upgrades 261-360."""
    return dict(stats=dict(STATS), pause_left_s=max(0, round(S.get("pause_until", 0) - time.time())), checks=S["checks"], nm=S["nm"], changes=S["changes"][-3:],
                calib=calib_line(), agents=S["agents"], best_skip=(S["best_skip"] or {}).get("text"), tp=learned_tp(), sources=source_rank())
def lp_unlock_pen(res):
    """341: LP not fully locked (but passed) -> penalty."""
    d = str((res.get("lp_locked") or ("", ""))[1]); m_ = re.search(r"([\d.]+)% locked", d)
    return -0.02 if m_ and float(m_.group(1)) < 99 else 0.0
def whale_block(m):
    """342/343/344: single holder >10% (ex-pools) block; snipers/dev share penalties - from the RugCheck holder scores already fetched (brain2.HS)."""
    import brain2; hs = brain2.HS.get(m) or {}
    top1 = hs.get("top1") or hs.get("max_holder")
    if top1 and _f(top1) > 10: return ("whale", f"one wallet holds {_f(top1):.1f}%"), 0.0
    pen = 0.0
    if _f(hs.get("snipers")) >= 3: pen -= 0.03  # 343 (hard block at 6 already in Filter)
    if _f(hs.get("bundle_same")) >= 3: pen -= 0.02  # 344 partial: no dev % in free data; near-bundle bag sizes used instead
    return None, pen
def rug_similar(f):
    """346: features look like past rugs (cosine-ish on numeric features) -> penalty."""
    if not f or not S["rugfeat"]: return 0.0
    ks = [k for k in f if isinstance(f.get(k), (int, float))]
    def sim(a):
        num = sum(_f(f[k]) * _f(a.get(k)) for k in ks); da = math.sqrt(sum(_f(f[k]) ** 2 for k in ks)); db = math.sqrt(sum(_f(a.get(k)) ** 2 for k in ks))
        return num / (da * db) if da and db else 0
    return -0.04 if max(sim(a) for a in S["rugfeat"][-50:]) > 0.97 else 0.0
def remember_rugfeat(m):
    j = S["journal"].get(m) or {}
    if j.get("feats"): S["rugfeat"] = (S["rugfeat"] + [j["feats"]])[-80:]; save()
def exit_liq_ok(usd, pair):
    """347: position must be <= 1% of pool liquidity so we could exit."""
    l = _liq(pair); return (True, None) if not l or usd <= 0.01 * l else (False, f"size ${usd:.0f} > 1% of ${l:,.0f} pool")
def net_target(tp):
    """348: targets are net of round-trip fees + slippage."""
    return round(tp + 2 * (CFG["FEE"] + CFG["SLIP"]), 3)
def offhours_mult():
    """349: overnight (1-6 AM PT) / weekend thin markets -> 0.8x size."""
    lt = time.localtime(); return 0.8 if 1 <= lt.tm_hour < 6 or lt.tm_wday >= 5 else 1.0
def label(pos, tot, j):
    """350/351: tag every closed trade: clean win, gave back, bad entry, rug, early stop, flat."""
    r = pos.get("reason") or ""; pk = (pos.get("peak") or pos["entry"]) / pos["entry"] - 1; hm = (time.time() - pos["opened"]) / 60
    if r in ("lp_pull", "dev_sell", "rug_recheck"): return "rug"
    if tot > 0: return "gave_back" if pk > 0.3 and tot < pos["cost"] * 0.05 else "clean_win"
    if pk < 0.02 and hm < 5: return "bad_entry"
    if r in ("stop_loss", "early_stop") and pk > 0.08: return "stopped_after_run"
    return "flat" if r in ("time_stop", "fomo_time", "flat_time") else "loss"
def mistake_learn(pos, tot, j):
    """351/352: count mistake types; repeated bad entries tighten entry-confirmation (bounded), repeated rugs remember the features."""
    lb = label(pos, tot, j); S["mistakes"][lb] = S["mistakes"].get(lb, 0) + 1
    if lb == "rug": remember_rugfeat(pos["mint"])
    if lb == "bad_entry":
        recent = [x for x in S["lessons"][-10:] if x == "bad_entry"]
        if len(recent) >= 2: S["tight"]["entry"] = clamp(S["tight"].get("entry", 0) + 0.01, 0, 0.05)
    elif lb == "clean_win": S["tight"]["entry"] = clamp(S["tight"].get("entry", 0) - 0.005, 0, 0.05)
    S["lessons"] = (S["lessons"] + [lb])[-50:]
def recap_lines():
    """353/354/356: recap additions - calibration meter, top learned signals, near-miss winners, best skipped coin."""
    top = sorted(((k, v[0] / v[1]) for k, v in S["checks"].items() if v[1] >= 3), key=lambda x: -x[1])[:3]
    nm = sum(v[0] for v in S["nm"].values()); nmn = sum(v[1] for v in S["nm"].values())
    return (calib_line() + "\nTop signals: " + (", ".join(f"{k} {w:.0%}" for k, w in top) or "learning") +
            f"\nSkipped coins that later ran +30%: {nm}/{nmn} · best: " + ((S["best_skip"] or {}).get("text") or "n/a"))
def exit_extra(pos, price):
    """355: exit alerts include hold time and peak."""
    return f"held {(time.time()-pos['opened'])/60:.0f} min · peak {((pos.get('peak') or price)/pos['entry']-1)*100:+.0f}%"
def guard_changes():
    """357/359: audit of brain7 rule changes; revert the last change if main-desk P&L since it is worse than -5% of start."""
    if not S["changes"]: return None
    x = S["changes"][-1]
    if x.get("reverted") or time.time() - x["t"] < 6 * 3600: return None
    c = conn(); pnl = c.execute("SELECT COALESCE(SUM(pnl),0) FROM positions WHERE status='closed' AND version='v3' AND closed>?", (x["t"],)).fetchone()[0]; c.close()
    if pnl < -0.05 * CFG["START_BALANCE"]:
        import brain2; brain2.BRAIN["thresholds"][x["key"]] = x["old"]; CFG["MIN_LIQ" if x["key"] == "min_liq" else "MIN_VOL_H1"] = x["old"]; brain2.save(brain2.BRAIN)
        x["reverted"] = time.time(); save(); log("rule_revert", **{k: v for k, v in x.items() if k != "t"}); return x
    return None
def paper_invariants():
    """358: startup self-test - paper-only invariants (no signing libs in use, no key files, every book is paper)."""
    import sys
    bad = [m for m in ("solders.keypair", "solana.keypair", "nacl.signing") if m in sys.modules]
    keys = [f for f in os.listdir(D) if re.search(r"(id\.json|keypair|\.key$|seed)", f, re.I)]
    ok = not bad and not keys; log("paper_selftest", ok=ok, signing_modules=bad, key_files=len(keys)); return ok
def promotion_hint():
    """360: report-only: if the v3x practice desk beats main over 30+ trades, suggest promoting its looser bars (never auto-applied)."""
    a, b = _closed("v3x", 14), _closed("v3", 14)
    if len(a) < 30 or len(b) < 10: return None
    wa = sum(p["pnl"] for p in a) / len(a); wb = sum(p["pnl"] for p in b) / len(b)
    return f"v3x practice beats main (${wa:+.2f} vs ${wb:+.2f}/trade over {len(a)} trades) - consider promoting" if wa > wb + 0.2 else None
def jobs(k):
    """Periodic learning jobs (runner pos loop, 1s ticks)."""
    try:
        if k % 900 == 600: nearmiss_learn(); agent_accuracy(); best_skipped()
        lt = time.localtime()
        if lt.tm_hour == 3 and lt.tm_min == 20 and k % 60 == 0: nearmiss_learn(); regret_tune()  # 281/282 nightly replay + bounded tune
        if k % 1800 == 1200: guard_changes()
    except Exception as e: log("error", where="brain7.jobs", trace=str(e)[:200])
