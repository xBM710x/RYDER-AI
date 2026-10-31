"""RYDER upgrades 401-440 (PAPER ONLY): decision quality, exit management, learning from live trades, speed. Hard rug checks unchanged."""
import time, json, os, collections
from common import CFG, dex_market
from logger import conn, log
D = os.path.dirname(os.path.abspath(__file__)); SF = os.path.join(D, "brain9.json")
def _load():
    try: return json.load(open(SF))
    except Exception: return {}
S = _load(); [S.setdefault(k, v) for k, v in dict(exit_cf={}, entry_cf=[], delay=None, stops={}, margins=[], milestones={}).items()]
STATS = collections.Counter()
def save(): json.dump(S, open(SF + ".tmp", "w"), default=str); os.replace(SF + ".tmp", SF)
def _f(x):
    try: return float(x or 0)
    except Exception: return 0.0
def pressure_verdict(b5, s5, bh, sh):
    """401/403 (bug fix): pressure was a kill when sells exceeded buys by even 1 trade (BIRB 645b/703s). Now kill only on clear selling
    (5m sells > 1.3x buys with 10+ sells, or 1h sells > 1.4x buys); otherwise pass with a graded score adj."""
    if (s5 >= 10 and s5 > 1.3 * max(1, b5)) or sh > 1.4 * max(1, bh): return "fail", 0.0
    r = (b5 + 1) / (s5 + 1); return "pass", round(max(-0.03, min(0.03, (r - 1) * 0.05)), 3)
def pump_canonical(mint, mtype, pct):
    """402 (data fix, approx): graduated pump.fun coins on PumpSwap (pump_fun_amm) show 0% 'locked' on RugCheck, but the canonical
    migration pool's LP is burned/held by the pump program, not the dev. Only for mints that originated on pump.fun (end in 'pump')."""
    return False  # REVERTED 2026-10-30 (Braydon approved): LP-lock check strict again on all desks
# ---------- exits ----------
def exit_check(p, price, pr, reg):
    """404/406/407/409/410/427/428/436 exit rules. Returns (reason, 'sell'|'partial'|'stop', new_stop) or None."""
    e = p["entry"]; pk = max(p.get("peak") or e, price); g = price / e - 1; gp = pk / e - 1; held = time.time() - p["opened"]
    liq = _f((pr.get("liquidity") or {}).get("usd")); m5 = _f((pr.get("priceChange") or {}).get("m5"))
    if held < 300 and g >= 0.40 and (p.get("tp_done") or 0) < 2: return ("spike_take", "partial", None)  # 410 sell into a +40% spike
    if gp >= 0.12: ns = e * 1.03  # 404 profit-protect: once +12%, stop no lower than +3%
    elif gp >= 0.08 and p.get("version") == CFG["VERSION"]: ns = e * 1.0  # 427 breakeven after +8% (was +10%)
    elif gp >= 0.05 and p.get("version") == "v3x" and __import__("fomo").is_fomo(p["mint"]): ns = e * 1.005  # 428 FOMO: breakeven+ after +5%
    else: ns = None
    if liq and liq < 20_000 and g < 0: ns = max(ns or 0, e * 0.94)  # 436 thin pool -> stop -6% (exit slippage)
    if gp >= 0.08 and price < pk * 0.94 and m5 < 0 and g > 0.02: return ("momentum_stall", "sell", None)  # 406
    if held > 90 * 60 and not p.get("trailing"): return ("max_hold", "sell", None)  # 409
    if ns and ns > (p.get("stop") or 0): return ("ratchet", "stop", ns)
    return None
def entry_liq_drain(p, liq, entry_liq):
    """407: liquidity drained 15%+ since entry -> tighten stop to -3%."""
    return entry_liq and liq and liq < entry_liq * 0.85 and p["entry"] * 0.97 > (p.get("stop") or 0)
# ---------- decision ----------
def pre_entry(pair, reg, first_seen_age_min=None):
    """416/418/419/420/421: decision checks before a coin enters the wait. Returns (kill_reason, detail) or (None, score_adj)."""
    pc = pair.get("priceChange") or {}; tx = pair.get("txns") or {}; h1 = tx.get("h1") or {}
    if _f(pc.get("m5")) > 60: return ("parabolic", f"+{_f(pc.get('m5')):.0f}% in 5 min"), 0
    if _f(pc.get("h1")) < -30 and _f(pc.get("m5")) <= 0: return ("dumping_1h", f"{_f(pc.get('h1')):.0f}% 1h, no bounce"), 0
    if (h1.get("buys") or 0) + (h1.get("sells") or 0) < 50: return ("few_trades", f"only {(h1.get('buys') or 0) + (h1.get('sells') or 0)} trades in 1h"), 0
    v = pair.get("volume") or {}; age = (time.time() * 1000 - (pair.get("pairCreatedAt") or 0)) / 3.6e6
    if age > 3 and _f(v.get("h6")) / 6 > 2 * _f(v.get("h1")): return ("fading_coin", "1h volume under half its 6h average"), 0
    mood = (reg or {}).get("mood"); return None, (-0.02 if mood == "risk-off" else 0.01 if mood == "hot" else 0.0)
def open_cap_ok(reg, ver):
    """417: wire the existing (unused) regime max-open cap: risk-off 2, neutral 3, hot 4."""
    import brain3; c = conn(); n = c.execute("SELECT COUNT(*) FROM positions WHERE status='open' AND version=?", (ver,)).fetchone()[0]; c.close()
    return n < brain3.max_open(reg), n
def coin_blocked(m):
    """434/435: one re-entry max per coin per day; blacklist after 2 stop-outs."""
    c = conn(); r = c.execute("SELECT COUNT(*), SUM(reason IN ('stop_loss','early_stop')) FROM positions WHERE mint=? AND version='v3' AND opened>? AND reason!='partial_tp'", (m, time.time() - 86400)).fetchone(); c.close()
    if (r[1] or 0) >= 2: return "stopped out twice on this coin"
    if (r[0] or 0) >= 2: return "already traded this coin twice today"
    return None
REST = {}
def stop_reentry_watch(p):
    """429: after a stop, watch 20 min; if price reclaims entry with buyers, allow one re-entry through the normal checks."""
    REST[p["mint"]] = (p["entry"], time.time(), p["symbol"])
def reentries():
    now = time.time(); [REST.pop(m) for m, v in list(REST.items()) if now - v[1] > 1200]
    if not REST: return []
    mk = dex_market(list(REST)); out = []
    for m, (e, t, s) in list(REST.items()):
        pr = mk.get(m); q = _f((pr or {}).get("priceUsd")); t5 = ((pr or {}).get("txns") or {}).get("m5") or {}
        if q >= e and (t5.get("buys") or 0) > 1.5 * max(1, t5.get("sells") or 0): out.append((m, s, q)); REST.pop(m)
    return out
def tie_break(pending):
    """437: when several coins are due together, order by RYDER confidence proxy (score + b7 adj)."""
    return sorted(pending, key=lambda m: -(pending[m]["score"] + ((pending[m].get("b7") or {}).get("adj") or 0)))
# ---------- learning ----------
EXITQ = []
def note_exit(p, price, reason):
    """411: re-price 15 min after every exit -> did the exit save money or cost a run?"""
    EXITQ.append((time.time(), p["mint"], price, reason))
def exit_cf_job():
    due = [x for x in EXITQ if time.time() - x[0] >= 900]
    if not due: return
    for x in due: EXITQ.remove(x)
    mk = dex_market([x[1] for x in due])
    for t, m, px, r in due:
        q = _f((mk.get(m) or {}).get("priceUsd"))
        if q and px: s = S["exit_cf"].setdefault(r, [0, 0, 0.0]); s[0] += 1; s[1] += q > px * 1.2; s[2] = round(s[2] + (q / px - 1) * 100, 1)
    save()
def exit_rule_ok(reason):
    """412: an exit rule that, 8+ times, sold coins that then ran +20% more than 40% of the time gets skipped (bounded, logged)."""
    n, ran, _ = S["exit_cf"].get(reason, [0, 0, 0])
    ok = not (n >= 8 and ran / n > 0.4)
    if not ok: STATS["412_skipped_" + reason] += 1
    return ok
ENTQ = []
def note_entry(m, price):
    """413: price 2 min after entry -> learn entry delay (bad early prices -> wait longer; good -> shorter), bounded 45-120s."""
    ENTQ.append((time.time(), m, price))
def entry_cf_job():
    due = [x for x in ENTQ if time.time() - x[0] >= 120]
    if not due: return
    for x in due: ENTQ.remove(x)
    mk = dex_market([x[1] for x in due])
    for t, m, px in due:
        q = _f((mk.get(m) or {}).get("priceUsd"))
        if q and px: S["entry_cf"] = (S["entry_cf"] + [round(q / px - 1, 4)])[-40:]
    xs = S["entry_cf"]
    if len(xs) >= 8:
        avg = sum(xs[-8:]) / 8; cur = CFG["ENTRY_DELAY"]
        new = max(45, min(120, cur + (15 if avg < -0.03 else -10 if avg > 0.03 else 0)))
        if new != cur: CFG["ENTRY_DELAY"] = new; S["delay"] = new; log("entry_delay_learned", old=cur, new=new, avg_2min=round(avg * 100, 1))
    save()
def note_margins(pair, m):
    """414: record how far above each bar a bought coin was (vol/liq margins) for later win analysis."""
    v = _f((pair.get("volume") or {}).get("h1")); l = _f((pair.get("liquidity") or {}).get("usd"))
    S["margins"] = (S["margins"] + [dict(m=m, vol=round(v / max(1, CFG["MIN_VOL_H1"]), 2), liq=round(l / max(1, CFG["MIN_LIQ"]), 2), t=time.time())])[-200:]; save()
def decay_learning():
    """438: half-life ~14 days on brain7 learned counts (applied daily: x0.952)."""
    import brain7
    for k in ("checks", "tod"):
        for v in brain7.S[k].values(): v[0] = round(v[0] * 0.952, 3); v[1] = round(v[1] * 0.952, 3)
    brain7.save(); log("learning_decay")
def milestone(kind):
    """433: log first-trade-of-day milestones."""
    d = time.strftime("%F"); k = kind + d
    if k not in S["milestones"]: S["milestones"][k] = time.time(); save(); log("milestone", what=f"first {kind} of {d}")
def jobs(k):
    try:
        if k % 30 == 15: exit_cf_job(); entry_cf_job()
        if k % 60 == 45 and REST:
            import runner
            for m, s, q in reentries():
                if m not in runner.PENDING and not coin_blocked(m):
                    runner.PENDING[m] = dict(t=time.time(), t0=time.time(), sym=s, price=q, score=0.6, creator="", res={}, rate=0, holders=0, owners=[], dex="", devbal=None); log("entry_wait", m, s, price=q, reentry_after_stop=True)
        lt = time.localtime()
        if lt.tm_hour == 3 and lt.tm_min == 40 and k % 60 == 0: decay_learning()
    except Exception as e: log("error", where="brain9.jobs", trace=str(e)[:200])
def status():
    """440: heartbeat block."""
    return dict(stats=dict(STATS), exit_cf=S["exit_cf"], entry_delay=CFG["ENTRY_DELAY"], entry_2min=S["entry_cf"][-5:], reentry_watch=len(REST))
