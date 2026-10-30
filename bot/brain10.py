"""RYDER upgrades 441-490 (PAPER ONLY): early-mover detection, near-miss re-check watchlist, smarter use of DexScreener boosts/profiles
and GeckoTerminal discovery, near-miss outcome learning, exit quality, reliability. Hard rug/safety checks and main-desk bars unchanged:
everything here only (a) re-queues coins for the SAME full evaluate() path, (b) adds small bounded score adjustments, or (c) exits earlier."""
import time, json, os, collections, threading
from common import CFG, dex_market
from logger import conn, log
D = os.path.dirname(os.path.abspath(__file__)); SF = os.path.join(D, "brain10.json")
def _load():
    try: return json.load(open(SF))
    except Exception: return {}
S = _load(); [S.setdefault(k, v) for k, v in dict(nm_out={}, accel_out=[0, 0], src_accel={}).items()]
STATS = collections.Counter(); LOCK = threading.Lock()
WATCH = {}      # 441 mint -> dict(sym, reason, t, px0, vol0, liq0, hist=[(t, vol_h1, m5vol, px, liq)], n_requeue, src)
QUEUE = []      # 444 coins due for a full re-evaluation
BOOST = {}      # 461 mint -> dict(amt, n, first, last)
TREND = collections.defaultdict(list)  # 466 mint -> poll timestamps seen on gecko trending/volume
OUTCOME = {}    # 471 near-miss -> price checkpoints for learning
def save():
    try: json.dump(S, open(SF + ".tmp", "w"), default=str); os.replace(SF + ".tmp", SF)
    except Exception: pass
def _f(x):
    try: return float(x or 0)
    except Exception: return 0.0
def _bar_vol(): return CFG.get("MIN_VOL_H1") or 28_000
def _bar_liq(): return CFG.get("MIN_LIQ") or 18_000
# ---------- 441-450 near-miss re-check watchlist + acceleration ----------
def note_kill(m, sym, reason, pair, src=None):
    """441/442: volume/liquidity near-misses (>=30% of the vol bar or >=50% of the liq bar, or boosted/trending) go on a 45-min watch.
    Safety kills are never watched."""
    if reason not in ("volume_1h", "liquidity") or not pair: return
    v = _f((pair.get("volume") or {}).get("h1")); lq = _f((pair.get("liquidity") or {}).get("usd")); px = _f(pair.get("priceUsd"))
    hot = m in BOOST or len(TREND.get(m, [])) >= 1
    if not px or not (v >= 0.30 * _bar_vol() or lq >= 0.5 * _bar_liq() or hot): return
    with LOCK:
        if m in WATCH: return
        if len(WATCH) >= 120: WATCH.pop(min(WATCH, key=lambda k: WATCH[k]["t"]), None)  # 449 bounded
        WATCH[m] = dict(sym=sym, reason=reason, t=time.time(), px0=px, vol0=v, liq0=lq, hist=[], n=0, src=src)
        OUTCOME.setdefault(m, dict(t=time.time(), px0=px, reason=reason, sym=sym))
    STATS["watch_add"] += 1
def unwatch(m):
    with LOCK: WATCH.pop(m, None)
    OUTCOME.pop(m, None)
def accel(pair, hist=None):
    """443: acceleration signal. 5m volume run-rate vs 1h volume, buy share, 5m price, and growth since the last look.
    Returns (score 0..1, why)."""
    vol = pair.get("volume") or {}; tx = (pair.get("txns") or {}).get("m5") or {}; pc = pair.get("priceChange") or {}
    v5, v1 = _f(vol.get("m5")), _f(vol.get("h1")); b, s = _f(tx.get("buys")), _f(tx.get("sells"))
    rr = (v5 * 12) / max(1.0, v1)                     # run-rate ratio: >1.5 = this 5m is much busier than the hour average
    bs = (b + 1) / (b + s + 2); p5 = _f(pc.get("m5"))
    g = 0.0
    if hist:
        dv = v1 - hist[-1][1]; g = dv / max(1.0, hist[-1][1])  # 445 hour-volume growth since last poll
    sc = 0.35 * min(1, max(0, (rr - 1) / 2)) + 0.25 * min(1, max(0, (bs - 0.5) * 4)) + 0.2 * min(1, max(0, p5 / 15)) + 0.2 * min(1, max(0, g / 0.5))
    if p5 > 60: sc *= 0.3                             # 446 parabolic candle is not an early move
    return round(sc, 3), f"rr {rr:.1f}x buys {bs:.0%} m5 {p5:+.0f}% dv {g:+.0%}"
def poll_watch():
    """444/445/447/448: every 30s re-price the watchlist (one batched DexScreener call per 30 mints); queue a full re-evaluation when
    volume crosses ~90% of the bar, or the coin is accelerating (score >= 0.55) and volume >= 60% of the bar. Max 3 re-queues per coin."""
    now = time.time()
    with LOCK:
        for m in [k for k, w in WATCH.items() if now - w["t"] > 2700 or w["n"] >= 3]: WATCH.pop(m, None)  # 448 45-min expiry
        ms = list(WATCH)
    if not ms: return
    mk = dex_market(ms); hot = 0
    for m in ms:
        pr = mk.get(m); w = WATCH.get(m)
        if not pr or not w: continue
        v1 = _f((pr.get("volume") or {}).get("h1")); lq = _f((pr.get("liquidity") or {}).get("usd")); px = _f(pr.get("priceUsd"))
        a, why = accel(pr, w["hist"]); w["hist"] = (w["hist"] + [(now, v1, _f((pr.get("volume") or {}).get("m5")), px, lq)])[-20:]
        if a >= 0.55: hot += 1
        if px and w["px0"] and px / w["px0"] - 1 < -0.35: WATCH.pop(m, None); STATS["watch_drop_dumped"] += 1; continue  # 450 dumped -> drop
        vol_ok = v1 >= 0.9 * _bar_vol() or (a >= 0.55 and v1 >= 0.6 * _bar_vol())
        liq_ok = lq >= 0.9 * _bar_liq()
        if vol_ok and liq_ok and now - w.get("last_q", 0) > 120:
            w["n"] += 1; w["last_q"] = now; w["accel"] = a
            QUEUE.append(dict(mint=m, name=w["sym"] or "", source="accel-watch", dex="unknown", recheck=True, vol=v1, accel=a))
            STATS["requeue"] += 1; log("watch_requeue", m, w["sym"], accel=a, why=why, vol_h1=round(v1), liq=round(lq), n=w["n"])
    SURGE[0] = hot; SURGE[1] = now
SURGE = [0, 0]
def due():
    """444: scout pulls queued re-checks. Resets the seen-row check count so the normal evaluate() (all safety checks) runs again."""
    out = []
    while QUEUE: out.append(QUEUE.pop(0))
    if out:
        c = conn()
        for d in out: c.execute("UPDATE seen SET done=0, checks=MIN(checks, 2) WHERE mint=?", (d["mint"],))
        c.commit(); c.close()
    return out
def scan_hint(ss):
    """451/452: faster re-scans when the market wakes up: 2+ watched coins accelerating -> scan every 10s; 1 -> 20s."""
    if time.time() - SURGE[1] > 90: return ss
    return min(ss, 10 if SURGE[0] >= 2 else 20 if SURGE[0] == 1 else ss)
def accel_adj(m, pair):
    """453: bounded score nudge for coins that arrived via the accel watch or are accelerating now: -0.02..+0.03."""
    if not pair: return 0.0
    a, _ = accel(pair, (WATCH.get(m) or {}).get("hist"))
    return round(0.03 if a >= 0.7 else 0.015 if a >= 0.55 else -0.02 if a < 0.1 and _f((pair.get("priceChange") or {}).get("m5")) < -5 else 0.0, 3)
# ---------- 461-470 DexScreener boosts/profiles + GeckoTerminal discovery ----------
def note_boost(t, url):
    """461/462: record boost amount and repeat boosts; profile-only listings tracked separately."""
    m = t.get("tokenAddress"); 
    if not m: return
    b = BOOST.setdefault(m, dict(amt=0, n=0, first=time.time(), last=0, profile=False))
    if "boosts" in url: b["amt"] = max(b["amt"], _f(t.get("totalAmount") or t.get("amount"))); b["n"] += 1; b["last"] = time.time()
    else: b["profile"] = True
    if len(BOOST) > 3000: [BOOST.pop(k) for k in list(BOOST)[:500]]
def note_trend(m, src):
    """466: count consecutive GeckoTerminal trending/top-volume appearances."""
    TREND[m] = [x for x in TREND[m] if time.time() - x < 1800] + [time.time()]
    if len(TREND) > 3000: [TREND.pop(k) for k in list(TREND)[:500]]
def feed_adj(m, pair):
    """463/464/467/468: bounded -0.03..+0.03. Big boost with weak organic volume = paid hype (-), repeat organic trending (+),
    profile + boost + rising volume (+). Replaces nothing; adds to the existing +0.03 boost bump."""
    b = BOOST.get(m); tr = len(TREND.get(m, [])); v = _f(((pair or {}).get("volume") or {}).get("h1")); adj = 0.0
    if b and b["amt"] >= 500 and v < 0.5 * _bar_vol(): adj -= 0.03          # 463 paid hype
    elif b and b["n"] >= 2 and v >= _bar_vol(): adj += 0.01                # 464 repeat boost backed by volume
    if tr >= 3: adj += 0.02                                                   # 467 trending 3+ polls in 30 min
    elif tr == 2: adj += 0.01
    if b and b.get("profile") and v >= _bar_vol(): adj += 0.005               # 468 paid profile + real volume
    return round(max(-0.03, min(0.03, adj)), 3)
# ---------- 471-478 near-miss / accel learning ----------
def outcome_job():
    """471/472: re-price near-misses at 30 and 60 min; per kill reason, how often a skipped coin ran +30% (missed winner) or -30%."""
    now = time.time(); due_ = [m for m, o in OUTCOME.items() if (now - o["t"] > 1800 and "p30" not in o) or now - o["t"] > 3600]
    if not due_: return
    mk = dex_market(due_[:60])
    for m in due_[:60]:
        o = OUTCOME.get(m); px = _f((mk.get(m) or {}).get("priceUsd"))
        if not o: continue
        if now - o["t"] > 3600 or not px:
            g = (px / o["px0"] - 1) if px else -1.0; r = S["nm_out"].setdefault(o["reason"], [0, 0, 0])
            r[0] += 1; r[1] += g >= 0.30; r[2] += g <= -0.30; OUTCOME.pop(m, None)
            if g >= 0.30: STATS["missed_winner"] += 1; log("nearmiss_outcome", m, o["sym"], reason=o["reason"], gain=round(g, 2))
        else: o["p30"] = px
    if len(OUTCOME) > 2000: [OUTCOME.pop(k) for k in list(OUTCOME)[:400]]
    save()
def accel_trade(won):
    """473: win/loss of trades that came through the accel watch (feeds the 474 confidence)."""
    S["accel_out"][0] += 1; S["accel_out"][1] += bool(won); save()
def accel_conf():
    """474: once 10+ accel trades exist, scale the 453 nudge by observed win rate (0.5x..1.5x)."""
    n, w = S["accel_out"]; return 1.0 if n < 10 else max(0.5, min(1.5, (w / n) / 0.45))
def decay():
    """478: nightly 14-day half-life on near-miss stats."""
    for k, r in S["nm_out"].items(): S["nm_out"][k] = [round(x * 0.952, 2) for x in r]
    save()
# ---------- 479-486 exits ----------
def exit_check(p, price, pr):
    """479 volume dry-up while green: held 8+ min, +3%..+15%, 5m volume < 25% of the hour average and m5 red -> sell.
    480 liquidity pull: pool liquidity < 70% of entry liquidity -> sell now. 481 sell wall: 5m sells >= 2.5x buys (15+ sells) and below entry+2% -> sell.
    482 fade from peak for FOMO trades: +6% peak given back to below +1% -> sell. Returns reason or None."""
    e = p["entry"]; g = price / e - 1; pk = max(p.get("peak") or e, price); held = time.time() - p["opened"]
    vol = pr.get("volume") or {}; v5, v1 = _f(vol.get("m5")), _f(vol.get("h1")); m5 = _f((pr.get("priceChange") or {}).get("m5"))
    tx = (pr.get("txns") or {}).get("m5") or {}; b, s = _f(tx.get("buys")), _f(tx.get("sells")); liq = _f((pr.get("liquidity") or {}).get("usd"))
    l0 = _f(p.get("liq0") or ENTRYLIQ.get(p["mint"]))
    if l0 and liq and liq < 0.70 * l0: return "liq_pull"
    if s >= 15 and s >= 2.5 * max(1, b) and g < 0.02: return "sell_wall"
    if held > 480 and 0.03 <= g <= 0.15 and v1 > 0 and v5 * 12 < 0.25 * v1 and m5 < 0: return "volume_dry"
    if p.get("version") == "v3x" and pk / e - 1 >= 0.06 and g < 0.01: return "fomo_fade"
    return None
ENTRYLIQ = {}
# ---------- 487-490 reliability ----------
FAILS = collections.deque(maxlen=50)
def guarded(name, fn, *a):
    """487: wrap brain10 jobs; 5 consecutive failures of one job -> back off 5 min (logged once)."""
    if time.time() < BACKOFF.get(name, 0): return
    try: fn(*a); ERRS[name] = 0
    except Exception as ex:
        ERRS[name] = ERRS.get(name, 0) + 1; FAILS.append((time.strftime("%H:%M:%S"), name, str(ex)[:120]))
        if ERRS[name] >= 5: BACKOFF[name] = time.time() + 300; ERRS[name] = 0; log("error", where="brain10." + name, trace=str(ex)[:200], backoff=300)
ERRS, BACKOFF = {}, {}
_BUSY = set()
def _bg(name, fn):
    """488: jobs run off the positions thread (no blocking exits); one instance at a time."""
    if name in _BUSY: return
    _BUSY.add(name)
    def run():
        try: guarded(name, fn)
        finally: _BUSY.discard(name)
    threading.Thread(target=run, daemon=True).start()
def jobs(k):
    if k % 30 == 10: _bg("poll_watch", poll_watch)            # 444 every ~30s
    if k % 300 == 200: _bg("outcome", outcome_job)            # 471 every ~5 min
    lt = time.localtime()
    if lt.tm_hour == 3 and lt.tm_min == 45 and k % 60 == 0: _bg("decay", decay)
def status():
    """489/490: heartbeat block."""
    hot = sorted(((w.get("accel") or 0, w["sym"]) for w in WATCH.values()), reverse=True)[:5]
    return dict(stats=dict(STATS), watch=len(WATCH), queued=len(QUEUE), surge=SURGE[0], hot=hot, boosts=len(BOOST), trending=sum(1 for v in TREND.values() if v),
                nearmiss_outcomes=S["nm_out"], accel_trades=S["accel_out"], recent_fail=list(FAILS)[-3:])
