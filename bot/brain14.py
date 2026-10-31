"""Six upgrades (PAPER ONLY), 2026-10-30 night. Nothing here loosens a bar or a safety check; every vote change is downward,
every exit change only sells earlier or protects a winner with a trailing floor.
1 snapshots: pair shape stored at council time so the agent rules can be backtested later (backtest14.py).
2 mood-aware FOMO (v3x) exits: weak SOL -> TP +6%/stop -4%; hot SOL -> at +8% trail 3% under peak (floor +5%) instead of selling.
3 copycat-rug memory: name/image/symbol/creator of coins that died fed into rug_assets; Risk vote penalised on a match.
4 Fomo-wallet hints: wallet buys -> 45-min re-check watch + note on Scout's vote (no score bump, no trading from it).
5 Telegram buy alerts carry the six agent votes with short reasons.
6 freeze watchdog: positions loop silent 90s -> restart just that thread (generation token); brain10 jobs stuck >10 min freed."""
import time, json, threading, collections
from logger import conn, log
STATS = collections.Counter(); D = __import__("os").path.dirname(__import__("os").path.abspath(__file__)); HANG = D + "/hang.log"
def _f(x):
    try: return float(x or 0)
    except Exception: return 0.0
def _hang(msg):
    try: open(HANG, "a").write(f"\n===== {time.strftime('%F %T')} [brain14 watchdog] {msg}\n")
    except Exception: pass
# ---------- 1 snapshots ----------
def _snapt(c): c.execute("CREATE TABLE IF NOT EXISTS snapshots(mint TEXT, ts REAL, data TEXT, px1 REAL, liq1 REAL, PRIMARY KEY(mint, ts))")
def snapshot(m, pair, cd, v=None, go=None):
    try:
        tx = pair.get("txns") or {}; d = dict(src=(cd or {}).get("source"), dex=pair.get("dexId"), age=pair.get("pairCreatedAt"), liq=_f((pair.get("liquidity") or {}).get("usd")),
            mc=_f(pair.get("marketCap") or pair.get("fdv")), m5=_f((pair.get("priceChange") or {}).get("m5")), tx5=tx.get("m5"), tx1=tx.get("h1"), px=_f(pair.get("priceUsd")),
            votes={a: x[0] for a, x in (v or {}).items()}, go=go, sym=(pair.get("baseToken") or {}).get("symbol"))
        c = conn(); _snapt(c); c.execute("INSERT OR IGNORE INTO snapshots VALUES(?,?,?,NULL,NULL)", (m, round(time.time(), 1), json.dumps(d))); c.commit(); c.close(); STATS["snap"] += 1
    except Exception: pass
def reprice_snapshots():
    from common import dex_market
    c = conn(); _snapt(c); rows = c.execute("SELECT mint, ts FROM snapshots WHERE px1 IS NULL AND ts<? LIMIT 60", (time.time() - 3600,)).fetchall(); c.close()
    if not rows: return
    mk = dex_market([r[0] for r in rows]); c = conn()
    for m, ts in rows:
        p = mk.get(m) or {}; c.execute("UPDATE snapshots SET px1=?, liq1=? WHERE mint=? AND ts=?", (_f(p.get("priceUsd")), _f((p.get("liquidity") or {}).get("usd")), m, ts))
    c.commit(); c.close()
# ---------- 2 mood-aware FOMO exits ----------
PEAK = {}
def fomo_exit(p, price, mood):
    """Returns sell reason or None. Replaces the flat +8% TP for v3x FOMO trades; the -5% stop on the position and the 10-min flat
    time-stop stay in force. Weak mood only adds earlier exits; hot mood holds past +8% with a trailing floor that never goes below +5%."""
    import fomo
    e = p["entry"]; g = price / e - 1; pk = PEAK[p["mint"]] = max(PEAK.get(p["mint"], e), price, p.get("peak") or 0); gp = pk / e - 1
    if mood == "risk-off":
        if g >= 0.06: return "fomo_tp_weak"
        if g <= -0.04: return "fomo_stop_weak"
        return None
    if mood == "hot":
        if gp >= fomo.TP_PCT:
            floor = max(e * 1.05, pk * 0.97)
            if price <= floor: PEAK.pop(p["mint"], None); return "fomo_trail_hot"
            return None
        return None
    if g >= fomo.TP_PCT: return "fomo_tp"
    return None
# ---------- 3 copycat-rug memory ----------
def _rt(c): c.execute("CREATE TABLE IF NOT EXISTS rug_assets(kind TEXT, val TEXT, mint TEXT, PRIMARY KEY(kind,val))")
def remember(m, pair, creator=None):
    bt = (pair or {}).get("baseToken") or {}; info = (pair or {}).get("info") or {}; c = conn(); _rt(c); n = 0
    for kind, val in (("img", info.get("imageUrl")), ("name14", (bt.get("name") or "").strip().lower()), ("sym", (bt.get("symbol") or "").strip().lower()), ("creator", creator)):
        if val and (kind != "sym" or len(val) >= 3): n += c.execute("INSERT OR IGNORE INTO rug_assets VALUES(?,?,?)", (kind, val, m)).rowcount
    c.commit(); c.close(); STATS["rug_assets_added"] += n
def match(m, pair, creator=None):
    bt = (pair or {}).get("baseToken") or {}; info = (pair or {}).get("info") or {}; hits = []
    c = conn(); _rt(c)
    for kind, val in (("img", info.get("imageUrl")), ("name14", (bt.get("name") or "").strip().lower()), ("sym", (bt.get("symbol") or "").strip().lower()), ("creator", creator)):
        if val:
            r = c.execute("SELECT mint FROM rug_assets WHERE kind=? AND val=? AND mint!=?", (kind, val, m)).fetchone()
            if r: hits.append(f"{kind} of dead {r[0][:6]}")
    c.close(); return hits
def sweep_dead_cf():
    """Coins re-priced ~1h after a kill (counterfactual) that died (-90% or liq < $1k) -> their name/image/symbol/creator remembered."""
    from common import dex_market
    c = conn(); c.execute("CREATE TABLE IF NOT EXISTS rug_seen14(mint TEXT PRIMARY KEY)")
    ms = [r[0] for r in c.execute("SELECT mint FROM counterfactual WHERE pct<=-90 AND mint NOT IN (SELECT mint FROM rug_seen14) ORDER BY ts DESC LIMIT 120")]
    cr = dict(c.execute("SELECT mint, creator FROM creators").fetchall()); c.close()
    if not ms: return 0
    mk = dex_market(ms); n = 0
    for m in ms:
        p = mk.get(m)
        if p: remember(m, p, cr.get(m)); n += 1
        elif cr.get(m): remember(m, None, cr.get(m))
    c = conn(); c.executemany("INSERT OR IGNORE INTO rug_seen14 VALUES(?)", [(m,) for m in ms]); c.commit(); c.close()
    return n
# ---------- 4 Fomo-wallet hints ----------
def fomo_hint(m):
    try:
        st = json.load(open(D + "/wallet_watch_state.json")); return (st.get("bal") or {}).get(m, 0) > 0
    except Exception: return False
def note_fomo_buy(m, sym, pair=None):
    import brain10
    with brain10.LOCK:
        if m not in brain10.WATCH:
            brain10.WATCH[m] = dict(sym=sym, reason="fomo-wallet", t=time.time(), px0=0, vol0=0, liq0=0, hist=[], n=0, src="fomo-wallet")
    STATS["fomo_hint"] += 1
# ---------- council hook ----------
def adjust(v, pair, cd, m, creator=None):
    """Lower-only: copycat-of-dead-coin -> Risk -0.35 (same image or creator, usually a veto), -0.15 (same name), -0.08 (symbol only). Fomo-wallet holding -> note only."""
    h = match(m, pair, creator)
    if h:
        strong = any(x.startswith(("img", "creator")) for x in h); d = 0.35 if strong else 0.08 if all(x.startswith("sym") for x in h) else 0.15  # backtest14: symbol-only matches flag 23% of coins (dead 12.3% vs 8.7%) -> soft
        v["risk"] = (round(max(0, v["risk"][0] - d), 3), v["risk"][1] + "; copycat of dead coin: " + ", ".join(h)[:80]); STATS["copycat_flag"] += 1
    if fomo_hint(m): v["scout"] = (v["scout"][0], v["scout"][1] + "; your Fomo wallet holds it (hint only)")
    return v
# ---------- 5 Telegram vote lines ----------
NAMES = dict(scout="Scout", filter="Filter", analyst="Analyst", executor="Executor", risk="Risk", logger="Logger")
def votes_text(council):
    vs = (council or {}).get("votes") or {}
    if not vs: return ""
    out = []
    for a, x in vs.items():
        vote, why = (x[0], x[1]) if isinstance(x, (list, tuple)) else (x, "")
        out.append(f"{'✅' if vote >= 0.5 else '⚠️'} {NAMES.get(a, a)} {vote:.2f}: {str(why).split(';')[0][:70]}")
    return "🗳 Agent votes (consensus " + f"{(council or {}).get('consensus', 0):.2f}" + ")\n" + "\n".join(out)
# ---------- 6 freeze watchdog ----------
GEN = [0]; RESTART = [None]; _RL = []; SGEN = [0]; SCAN_RESTART = [None]; _SRL = []; PAUSES = []
def watchdog():
    """Also detects whole-process / box pauses: if this thread's own 15s sleep overran by 30s+, every thread was frozen (9:37 PM PT 2026-10-30:
    all runner threads AND the separate publisher process went silent together for ~150s) -> logged as a pause, loop stamps reset, no restart."""
    import brain11, brain10
    last = time.time()
    while True:
        time.sleep(15)
        try:
            now = time.time(); gap = now - last; last = now
            if gap > 45:
                PAUSES.append((time.strftime("%H:%M:%S"), round(gap))); del PAUSES[:-20]; STATS["process_pause"] += 1
                _hang(f"whole process paused {gap:.0f}s (watchdog thread itself did not run) -> box/CPU stall, not a RYDER loop; no restart")
                log("process_pause", sec=round(gap)); brain11.LOOP_T["pos"] = brain11.LOOP_T["scan"] = now; continue
            ts = brain11.LOOP_T.get("scan")
            if ts and now - ts > 120 and SCAN_RESTART[0] and not [x for x in _SRL if now - x < 600]:
                _SRL.append(now); SGEN[0] += 1; STATS["scan_restart"] += 1
                _hang(f"scan loop silent {now - ts:.0f}s -> restarted scan thread only (gen {SGEN[0]})")
                log("selfheal", what="scan_loop_stuck", silent_s=round(now - ts), gen=SGEN[0]); brain11.LOOP_T["scan"] = now; SCAN_RESTART[0]()
            t = brain11.LOOP_T.get("pos")
            if t and now - t > 90 and RESTART[0] and not [x for x in _RL if now - x < 300]:
                _RL.append(now); GEN[0] += 1; STATS["pos_restart"] += 1
                _hang(f"positions loop silent {now - t:.0f}s (step {brain11.CUR.get('pos')}) -> restarted positions thread only (gen {GEN[0]})")
                log("selfheal", what="pos_loop_stuck", silent_s=round(now - t), gen=GEN[0]); brain11.LOOP_T["pos"] = now; RESTART[0]()
            for name in list(brain10._BUSY):
                s = BUSY_T.setdefault(name, now)
                if now - s > 600: brain10._BUSY.discard(name); BUSY_T.pop(name, None); STATS["job_freed"] += 1; _hang(f"job {name} stuck >10 min -> freed so the next run can start")
            for name in list(BUSY_T):
                if name not in brain10._BUSY: BUSY_T.pop(name, None)
        except Exception: pass
BUSY_T = {}
def start(restart_fn):
    RESTART[0] = restart_fn; threading.Thread(target=watchdog, daemon=True, name="b14-watchdog").start()
# ---------- rugcheck-unavailable retry ----------
RC = {}  # mint -> [due_ts, tries, sym]
def rc_retry(m, sym, reason, detail, final):
    """62 coins in 24h passed volume + liquidity and were then killed only because rugcheck.xyz had no report yet ('unable to generate report').
    Retry them through the SAME full evaluate() (fail-closed, every check re-run) after 150s and 300s. Max 2 retries; nothing is loosened."""
    if not final or "rugcheck unavailable" not in str(detail): return
    r = RC.setdefault(m, [0, 0, sym])
    if r[1] >= 2: return
    r[0] = time.time() + 150 * (r[1] + 1); STATS["rc_retry_sched"] += 1
    if len(RC) > 2000: [RC.pop(k) for k in list(RC)[:500]]
def rc_due():
    import brain10, brain2
    now = time.time()
    for m, r in list(RC.items()):
        if r[0] and now >= r[0]:
            r[0] = 0; r[1] += 1; brain2.REJ.pop(m, None); STATS["rc_retry"] += 1
            brain10.QUEUE.append(dict(mint=m, name=r[2] or "", source="rugcheck-retry", dex="unknown", recheck=True))
def jobs(k):
    import brain10
    if k % 15 == 7: rc_due()
    if k % 600 == 450: brain10._bg("b14_rugsweep", sweep_dead_cf)
    if k % 300 == 222: brain10._bg("b14_snap", reprice_snapshots)
def status():
    c = conn(); _rt(c); n = c.execute("SELECT kind, COUNT(*) FROM rug_assets GROUP BY kind").fetchall(); c.close()
    return dict(stats=dict(STATS), rug_assets=dict(n), gen=GEN[0], scan_gen=SGEN[0], pauses=PAUSES[-5:])
