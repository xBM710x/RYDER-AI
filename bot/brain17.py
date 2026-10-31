"""Fail-mode upgrades (2026-10-31, approved by Braydon). PAPER ONLY. Everything here only ADDS rejects/pauses/exits; nothing is loosened.
1 7-factor scorecard (rug, hype, holders, dev, bundle, originality, timing; each 0-1) from data RYDER already has (filters.check res + DexScreener pair).
  Any factor below its floor -> reject 'weak_<factor>' (one bad answer can't be averaged away). Unknown data -> 0.5 (floors bite on evidence only).
2 Plain-English 'why I bought it' + scorecard stored on each paper_buy event (exported per trade in data.json calendar.list).
3 Copy desk: wallet demoted after 3 losing copies in a row; max 20% of copy-desk equity open in one copied wallet.
4 Stale-data breaker: no new entry if the price data is older than STALE_S seconds (exits unaffected).
5 Liquidity-drop breaker: pool liquidity down >30% within 5 min -> no new buys on that coin for 30 min; open positions exit ('liq_drop').
6 Breaker self-tests (selftest()): run at startup + hourly; failure -> log 'breaker_selftest' + Telegram alert."""
import time, re, json, os, threading, collections
from logger import conn, log
FLOORS = dict(rug=0.35, hype=0.25, holders=0.35, dev=0.35, bundle=0.35, originality=0.35, timing=0.25)
STALE_S = 60; LIQ_DROP = 0.30; LIQ_WIN = 300; LIQ_PAUSE = 1800; DEMOTE_AFTER = 3; WALLET_CAP = 0.20
STATS = collections.Counter(); LIQH = {}; LIQBLOCK = {}; _L = threading.Lock(); LAST_TEST = {}
def _st(res, k): return ((res or {}).get(k) or ("unknown",))[0]
def _sc(res, keys):
    s = [_st(res, k) for k in keys if k in (res or {})]
    if not s: return 0.5
    if "fail" in s: return 0.0
    return round(0.5 + 0.5 * s.count("pass") / len(s), 3)
def _f(x):
    try: return float(x)
    except Exception: return None
def scorecard(pair, res):
    pair = pair or {}; res = res or {}; tx = pair.get("txns") or {}; h1 = tx.get("h1") or {}; m5 = tx.get("m5") or {}
    rug = _sc(res, ("mint_authority", "freeze_authority", "lp_locked", "honeypot", "mutable_meta"))
    if rug and res.get("_backup_check"): rug = min(rug, 0.75)
    vol = _f((pair.get("volume") or {}).get("h1")); liq = _f((pair.get("liquidity") or {}).get("usd"))
    b, s = (h1.get("buys") or 0), (h1.get("sells") or 0)
    if vol is None or not liq or b + s == 0: hype = 0.5
    else: hype = round(0.5 * min(1, vol / liq / 2) + 0.5 * (b / (b + s)), 3)
    hold = _sc(res, ("top10",)); mt = re.search(r"([\d.]+)%", str((res.get("top10") or ("", ""))[1]))
    if hold and mt: hold = round(max(0.0, min(1.0, 1 - float(mt.group(1)) / 40)), 3)
    dev = _sc(res, ("dev_rugs", "_creator"))
    bun = _sc(res, ("bundled", "holder_cluster", "wash"))
    orig = _sc(res, ("copycat", "clone_contract", "socials"))
    pc = pair.get("priceChange") or {}; c5, c1 = _f(pc.get("m5")), _f(pc.get("h1"))
    if c5 is None and c1 is None: tim = 0.5
    else:
        tim = 1.0
        if c1 is not None and c1 > 300: tim -= min(0.6, (c1 - 300) / 1000)  # very late: already +300%..+900% in 1h
        if c5 is not None and c5 < -10: tim -= min(0.6, (-c5 - 10) / 30)  # dumping right now
        if c5 is not None and c5 > 60: tim -= 0.3  # vertical candle chase
        if (m5.get("sells") or 0) > 2 * max(1, m5.get("buys") or 0): tim -= 0.2
        tim = round(max(0.0, tim), 3)
    return dict(rug=rug, hype=hype, holders=hold, dev=dev, bundle=bun, originality=orig, timing=tim)
def weak(sc):
    w = [k for k, v in sc.items() if v < FLOORS[k]]
    return ("weak_" + min(w, key=lambda k: sc[k] - FLOORS[k])) if w else None
WORD = dict(rug="rug safety", hype="hype", holders="holder spread", dev="dev trust", bundle="no bundling", originality="originality", timing="timing")
def why_bought(sym, sc, pair, extra=None):
    good = [WORD[k] for k, v in sorted(sc.items(), key=lambda kv: -kv[1]) if v >= 0.8][:3]
    low = min(sc, key=sc.get); liq = _f(((pair or {}).get("liquidity") or {}).get("usd")); vol = _f(((pair or {}).get("volume") or {}).get("h1"))
    s = f"Bought {sym}: " + (("strong on " + ", ".join(good)) if good else "passed every check, no standout") + f"; weakest was {WORD[low]} ({sc[low]:.2f}, floor {FLOORS[low]:.2f})."
    if liq: s += f" Pool ${liq:,.0f}" + (f", 1h volume ${vol:,.0f}." if vol else ".")
    if (extra or {}).get("copy_of"): s += f" Copied wallet {extra['copy_of']} (graded good)."
    return s
def gate(mint, sym, pair, res, ver, extra):
    """Called by executor.buy for v3+ desks. Returns (ok, extra_with_scorecard)."""
    sc = scorecard(pair, res); w = weak(sc); STATS["scored"] += 1
    if w:
        STATS[w] += 1; log("kill", mint, sym, reason=w, detail=f"{w[5:]} {sc[w[5:]]:.2f} < floor {FLOORS[w[5:]]:.2f}", final=True, scorecard=sc, book=ver); return False, extra
    return True, dict(extra or {}, scorecard=sc, why_bought=why_bought(sym, sc, pair, extra))
# ---------- 4 stale data ----------
def stale(pair, now=None):
    ts = (pair or {}).get("_ts"); now = now or time.time()
    if ts is None: return None  # source without a timestamp (fallback quotes): unchanged behaviour
    return f"stale_data: price {now - ts:.0f}s old > {STALE_S}s" if now - ts > STALE_S else None
# ---------- 5 liquidity drop ----------
def note_liq(mint, liq, now=None):
    """Record pool liquidity; returns True when it fell > LIQ_DROP from the max of the last LIQ_WIN seconds."""
    now = now or time.time(); liq = _f(liq)
    if not liq: return False
    with _L:
        h = [x for x in LIQH.get(mint, []) if now - x[0] <= LIQ_WIN] + [(now, liq)]; LIQH[mint] = h[-40:]
        if len(LIQH) > 3000: [LIQH.pop(k) for k in list(LIQH)[:1000]]
    hi = max(x[1] for x in h)
    if hi > 0 and liq < hi * (1 - LIQ_DROP):
        if mint not in LIQBLOCK or now - LIQBLOCK[mint] > 60: STATS["liq_drop"] += 1
        LIQBLOCK[mint] = now; return True
    return False
def liq_blocked(mint, pair=None, now=None):
    now = now or time.time()
    if pair is not None and note_liq(mint, (pair.get("liquidity") or {}).get("usd"), now): return f"liq_drop: pool liquidity fell >{LIQ_DROP:.0%} in {LIQ_WIN//60} min"
    t = LIQBLOCK.get(mint)
    return f"liq_drop: pool drained recently (paused {LIQ_PAUSE//60} min)" if t and now - t < LIQ_PAUSE else None
# ---------- 3 copy wallet demotion + allocation cap ----------
def copy_results(c=None):
    """who -> list of closed full-exit pnl, oldest first (vC positions joined to their paper_buy copy_of)."""
    c0 = c or conn(); out = collections.defaultdict(list)
    buys = {}
    for m, ts, d in c0.execute("SELECT mint, ts, data FROM events WHERE kind='paper_buy' AND data LIKE '%copy_of%'"):
        try: buys.setdefault(m, []).append((ts, json.loads(d).get("copy_of")))
        except Exception: pass
    for m, op, pnl in c0.execute("SELECT mint, opened, pnl FROM positions WHERE version='vC' AND status='closed' AND pnl IS NOT NULL ORDER BY closed"):
        w = [who for ts, who in buys.get(m, []) if abs(ts - op) < 120]
        if w: out[w[0]].append(pnl)
    if c is None: c0.close()
    return out
def demoted(who, results=None):
    r = (results if results is not None else copy_results()).get(who, [])
    return len(r) >= DEMOTE_AFTER and all(p <= 0 for p in r[-DEMOTE_AFTER:])
def wallet_open_usd(who, c=None):
    c0 = c or conn(); tot = 0.0
    opn = {m: (op, cost) for m, op, cost in c0.execute("SELECT mint, opened, cost FROM positions WHERE version='vC' AND status='open'")}
    for m, ts, d in c0.execute("SELECT mint, ts, data FROM events WHERE kind='paper_buy' AND data LIKE ?", ('%"copy_of": "' + who + '"%',)):
        if m in opn and abs(ts - opn[m][0]) < 120: tot += opn[m][1] or 0
    if c is None: c0.close()
    return tot
def copy_block(who, size_usd, equity):
    if demoted(who): STATS["copy_demoted"] += 1; return f"copy_demoted: {who} lost {DEMOTE_AFTER} copies in a row"
    if wallet_open_usd(who) + size_usd > WALLET_CAP * equity: STATS["copy_wallet_cap"] += 1; return f"copy_wallet_cap: {who} already near {WALLET_CAP:.0%} of copy desk"
    return None
# ---------- 6 self-tests ----------
def selftest(alert=True):
    import brain15, brain16, executor, inspect
    R = {}
    def t(name, fn):
        try: R[name] = bool(fn())
        except Exception as e: R[name] = False; log("error", where="b17_selftest:" + name, trace=str(e)[:160])
    def dd():
        o, oM, oD = brain15._trades, dict(brain15._M), dict(brain15.DDON)
        try:
            brain15._trades = lambda c, v: [dict(pnl=p, reason="x", opened=i, closed=i + 1, cost=10) for i, p in enumerate([20, -25, -20])]
            brain15._M.pop("_t", None); m, why = brain15.size_mult("_t"); return m <= 0.5 and any("drawdown" in w for w in why)
        finally: brain15._trades = o; brain15._M.clear(); brain15._M.update(oM); brain15.DDON.clear(); brain15.DDON.update(oD)
    t("drawdown", dd)
    src = inspect.getsource(executor.buy)
    t("losing_streak", lambda: "if streak >= 2: size *= 0.5 if streak >= 3 else 0.75" in src and next((i for i, p in enumerate([-1, -2, -3]) if p > 0), 3) >= 3)
    t("per_coin_cap", lambda: executor.MAX_COIN_PCT <= 0.12 and "per-coin exposure cap" in src)
    t("stale_data", lambda: stale(dict(_ts=time.time() - STALE_S - 5)) and not stale(dict(_ts=time.time())) and "brain17" in src)
    def lq():
        k = "_selftest_mint"; LIQH.pop(k, None); LIQBLOCK.pop(k, None); n = time.time()
        a = note_liq(k, 10000, n - 120); b = note_liq(k, 6000, n); blk = liq_blocked(k, None, n + 60)
        LIQH.pop(k, None); LIQBLOCK.pop(k, None); return (not a) and b and blk
    t("liquidity_drop", lq)
    def chase():
        logs = []; oL, oD, oP = brain16.log, brain16.dex_market, dict(brain16.PENDING)
        try:
            brain16.PENDING.clear(); brain16.PENDING["_st"] = dict(t=0, px0=1.0, sym="TEST", who="x")
            brain16.log = lambda *a, **k: logs.append((a, k)); brain16.dex_market = lambda ms: {"_st": {"priceUsd": "1.2"}}
            brain16.run_pending(); return any(k.get("reason") == "copy_chased" for a, k in logs) and brain16.CHASE <= 0.10
        finally: brain16.log, brain16.dex_market = oL, oD; brain16.PENDING.clear(); brain16.PENDING.update(oP)
    t("max_chase", chase)
    t("wallet_demotion", lambda: demoted("w", {"w": [5, -1, -2, -3]}) and not demoted("w", {"w": [-1, -2, 4]}) and not demoted("w", {"w": [-1, -2]}))
    t("scorecard_floor", lambda: weak(scorecard({"priceChange": {"m5": -40}, "txns": {"m5": {"sells": 30, "buys": 2}}}, {"top10": ("pass", "top10 5%")})) == "weak_timing" and weak(scorecard({}, {})) is None)
    LAST_TEST.clear(); LAST_TEST.update(R, at=round(time.time()))
    bad = [k for k, v in R.items() if not v]
    log("breaker_selftest", ok=not bad, failed=bad, n=len(R))
    if bad and alert:
        try: __import__("alerts").send_async("⚠️ RYDER breaker self-test FAILED (paper): " + ", ".join(bad) + " — a safety brake may not be firing.")
        except Exception: pass
    return R
def jobs(k):
    if k % 3600 == 30: threading.Thread(target=selftest, daemon=True, name="b17-selftest").start()
def status(): return dict(stats=dict(STATS), floors=FLOORS, stale_s=STALE_S, liq_paused=sum(1 for t in LIQBLOCK.values() if time.time() - t < LIQ_PAUSE), selftest=LAST_TEST)
