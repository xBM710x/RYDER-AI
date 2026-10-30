"""Upgrades 221-260 (PAPER ONLY; read-only public data; no wallets, keys or signing)."""
import time, json, math, collections, statistics, threading
from common import CFG, http_json, dex_market
from logger import conn, log
import brain2, brain5
B = brain2.BRAIN; STATS = brain2.STATS
# ---------- 222/223/227/242/252 live per-coin trade stream (PumpPortal subscribeTokenTrade; pump.fun/pumpswap coins) ----------
TR = collections.defaultdict(lambda: collections.deque(maxlen=400)); SUBS = set(); WANT = set()
def on_trade(m):
    TR[m["mint"]].append((time.time(), m.get("txType"), float(m.get("solAmount") or 0), m.get("traderPublicKey"))); STATS["trade_events"] += 1
def want(mints): WANT.update(mints)
def sync(ws):
    """called from the feed thread: subscribe new mints (open positions + waiting coins), drop stale ones."""
    add = list(WANT - SUBS)[:50]; rem = list(SUBS - WANT)[:50]
    if add: ws.send(json.dumps({"method": "subscribeTokenTrade", "keys": add})); SUBS.update(add)
    if rem: ws.send(json.dumps({"method": "unsubscribeTokenTrade", "keys": rem})); SUBS.difference_update(rem)
def recent(m, s):
    t = time.time(); return [x for x in TR.get(m, ()) if t - x[0] <= s]
def big_sell(m, sol=5.0, s=3):  # 223
    return [x for x in recent(m, s) if x[1] == "sell" and x[2] >= sol]
def single_wallet(m, s=120):  # 227 one wallet driving the buys
    b = [x for x in recent(m, s) if x[1] == "buy"]; tot = sum(x[2] for x in b)
    if len(b) < 6 or tot < 3: return None
    by = collections.Counter(); [by.update({x[3]: x[2]}) for x in b]; w, v = by.most_common(1)[0]
    return f"one wallet = {v/tot:.0%} of {tot:.1f} SOL buys in {s}s" if v / tot > 0.4 else None
def churn_wallets(m, s=300):  # 252 same wallets buying and selling repeatedly
    xs = recent(m, s); bw = collections.Counter(x[3] for x in xs if x[1] == "buy"); sw = collections.Counter(x[3] for x in xs if x[1] == "sell")
    both = [w for w in bw if bw[w] >= 2 and sw.get(w, 0) >= 2]
    return f"{len(both)} wallets both buying and selling repeatedly" if len(both) >= 3 else None
def smart_first_minute(m):  # 242
    xs = [x[3] for x in recent(m, 600) if x[1] == "buy"][:60]
    if not xs: return 0
    c = conn(); q = ",".join("?" * len(set(xs)))
    try: n = c.execute(f"SELECT COUNT(*) FROM smart_wallets WHERE wallet IN ({q})", list(set(xs))).fetchone()[0]
    except Exception: n = 0
    c.close(); return n
# ---------- 225 fastest-source routing for prices ----------
def fallback_prices(mints):
    out = {}
    try:
        j = http_json("https://lite-api.jup.ag/price/v3?ids=" + ",".join(mints[:50]), timeout=6)
        for m in mints:
            p = (j.get(m) or {}).get("usdPrice")
            if p: out[m] = dict(priceUsd=str(p), liquidity=dict(usd=(j[m].get("liquidity") or 0)), _src="jupiter")
    except Exception: pass
    STATS["price_fallback"] += len(out); return out
# ---------- 229 dip-buyer reaction ----------
def dip_reaction(m):
    q = list(brain2.TK.get(m, []))
    if len(q) < 8: return None
    lo = min(range(len(q)), key=lambda i: q[i][1])
    if lo >= len(q) - 2: return None
    rec = (q[-1][1] / q[lo][1] - 1) * 100 if q[lo][1] else 0; buys = q[-1][2] - q[lo][2]
    return round(min(1, max(0, rec / 8 + buys / 30)), 2)
# ---------- 230 worst-case loss forecast ----------
def stop_slip():
    c = conn(); r = [json.loads(x["data"]).get("slip_pct") for x in c.execute("SELECT data FROM events WHERE kind='paper_exit' AND data LIKE '%stop%' ORDER BY ts DESC LIMIT 30")]; c.close()
    r = [abs(x) for x in r if isinstance(x, (int, float))]
    return round(statistics.median(r) / 100, 4) if r else 0.03
def worst_case(usd, stop, slip):
    return round(usd * (stop + stop_slip() + slip + 2 * CFG["FEE"]), 2)
# ---------- 232 30-day theme memory / 251 theme heat velocity / 245 mcap range ----------
def theme_memory(narr):
    tr = [p for p in brain5._all(30) if (p["buy"].get("narrative") or "other") == narr]
    if len(tr) < 3: return 0.0
    return round(max(-0.1, min(0.1, sum(p["tot"] * p["w"] for p in tr) / 50)), 3)
def theme_velocity():
    c = conn(); t = time.time(); now, prev = collections.Counter(), collections.Counter()
    import extras
    for r in c.execute("SELECT symbol, ts FROM events WHERE kind='score' AND ts>?", (t - 9000,)):
        (now if r["ts"] > t - 1800 else prev)[extras.narrative(r["symbol"] or "")] += 1
    c.close()
    return sorted([(n, round(now[n] / max(1, prev[n] / 4), 2)) for n in now if now[n] >= 3], key=lambda x: -x[1])[:5]
def mcap_bucket(mc): return "<100k" if mc < 1e5 else "<500k" if mc < 5e5 else "<2m" if mc < 2e6 else "2m+"
def mcap_adj(mc):
    tr = [p for p in brain5._all(30) if p["buy"].get("feats")]; b = mcap_bucket(mc)
    s = [p for p in tr if mcap_bucket((p["buy"]["feats"].get("mcap_k") or 0) * 1000) == b]
    if len(s) < 4: return 0.0
    return round((sum(p["tot"] > 0 for p in s) / len(s) - 0.45) * 0.2, 3)
# ---------- 233 strong agreement ----------
def all_agree(v): return all(x[0] >= 0.7 for x in v.values())
# ---------- 234 daily paper profit goal pause / 235 rug-prone hours ----------
def day_goal_hit():
    c = conn(); d0 = time.mktime(time.localtime()[:3] + (0, 0, 0, 0, 0, -1))
    pnl = c.execute("SELECT COALESCE(SUM(pnl),0) FROM positions WHERE status='closed' AND version=? AND closed>=?", (CFG["VERSION"], d0)).fetchone()[0]; c.close()
    return f"daily paper goal hit (+${pnl:.2f}); protecting the day" if pnl >= 0.15 * CFG["START_BALANCE"] else None
def rug_hour():
    c = conn(); h = time.localtime().tm_hour
    n = sum(1 for r in c.execute("SELECT closed FROM positions WHERE reason IN ('dev_sell','lp_pull','holder_concentration','sell_spike_5s')") if time.localtime(r["closed"]).tm_hour == h); c.close()
    return n >= 2
# ---------- 236 learned wait ----------
def learned_wait():
    c = conn(); t = time.time() - 86400; ch = du = 0
    for r in c.execute("SELECT data FROM events WHERE kind='kill' AND ts>? AND data LIKE '%during wait%'", (t,)):
        d = r["data"]; ch += "chasing" in d; du += "dumping" in d or "dumped" in d
    c.close(); w = CFG.get("ENTRY_DELAY", 90)
    if ch + du >= 6: w = 60 if ch > 2 * du else 120 if du > 2 * ch else 90
    B["learned_wait"] = w; return w
# ---------- 237 chart-shape similarity ----------
def shape(m, n=12):
    q = [x[1] for x in brain2.TK.get(m, []) if x[1]]
    if len(q) < n: return None
    step = len(q) / n; s = [q[int(i * step)] for i in range(n)]; return [round(x / s[0] - 1, 4) for x in s]
def shape_sim(sh):
    if not sh: return None
    tr = [p for p in brain5._all(30) if p["buy"].get("shape")]
    if len(tr) < 5: return None
    def corr(a, b):
        try: return statistics.correlation(a, b)
        except Exception: return 0
    near = sorted(tr, key=lambda p: -corr(sh, p["buy"]["shape"]))[:5]
    return round(sum((p["tot"] > 0) * p["w"] for p in near) / sum(p["w"] for p in near), 2)
# ---------- 238 A/B rule tests on v3x ----------
ARMS = {"A": 0.20, "B": 0.35}
def arm(): return "A" if int(time.time() // 60) % 2 == 0 else "B"
def ab_tally():
    t = collections.defaultdict(lambda: [0, 0.0])
    for p in brain5._trades(brain5.EXP, 30):
        a = p["buy"].get("ab_arm")
        if a: t[a][0] += 1; t[a][1] += p["tot"]
    return {a: dict(n=v[0], pnl=round(v[1], 2)) for a, v in t.items()}
# ---------- 239 latency monitor ----------
_lat = dict(slow_since=None, last_alert=0)
def latency_check(dec_p90, scan_avg):
    slow = (dec_p90 or 0) > 60 or (scan_avg or 0) > 45
    if not slow: _lat["slow_since"] = None; return
    _lat["slow_since"] = _lat["slow_since"] or time.time()
    if time.time() - _lat["slow_since"] > 600 and time.time() - _lat["last_alert"] > 3600:
        _lat["last_alert"] = time.time(); __import__("alerts").send_async(f"🐢 RYDER is running slow: decisions p90 {dec_p90}s, scan {scan_avg}s for 10+ min (paper desk still safe)")
# ---------- 241/253 live position health (incl. LP health) ----------
HEALTH = {}
def health(p, price, pair, entry_liq):
    pnl = price / p["entry"] - 1; liq = (pair.get("liquidity") or {}).get("usd") or 0; mc = pair.get("marketCap") or pair.get("fdv") or 1
    lp = min(1, (liq / entry_liq if entry_liq else 1)) * (1 if 0.05 <= liq / mc <= 0.6 else 0.7)  # 253
    sp = brain2.spike(p["mint"], 10); pres = brain2.pressure(pair)
    h = 0.35 * max(0, min(1, 0.5 + pnl * 2)) + 0.25 * pres + 0.25 * lp + 0.15 * (0 if sp["sells"] > 2 * max(1, sp["buys"]) else 1)
    HEALTH[p["mint"]] = dict(sym=p["symbol"], book=p.get("version"), health=round(h, 2), lp=round(lp, 2), pnl_pct=round(pnl * 100, 1)); return round(h, 2)
# ---------- 243 holders rising while price flat ----------
def gecko_holders(m):
    try: return ((http_json(f"https://api.geckoterminal.com/api/v2/networks/solana/tokens/{m}/info", timeout=8)["data"]["attributes"].get("holders") or {}).get("count"))
    except Exception: return None
# ---------- 244 fresh-wallet top holders ----------
def fresh_holders(owners):
    from onchain import r
    owners = [o for o in owners if o][:5]
    if len(owners) < 4: return None
    fresh = 0
    for o in owners:
        try: fresh += len(r("getSignaturesForAddress", [o, {"limit": 10}]) or []) < 10
        except Exception: return None
    return f"{fresh}/{len(owners)} top holders are brand-new wallets" if fresh >= 4 else None
# ---------- 246 faster profit taking when market turns ----------
def market_turning(reg): return (reg or {}).get("mood") == "risk-off" or ((reg or {}).get("sol_h1") or 0) <= -1.5
# ---------- 247 split-buy fill simulation ----------
def split_slip(usd, pair):
    from brain4 import slip
    return round((slip(usd / 2, pair) + slip(usd / 2, pair) * 1.15) / 2, 4)  # 2 halves; second half pays a little drift
# ---------- 248 per-minute rug re-check ----------
RC = {}
def rug_recheck(m):
    try: rc = http_json(f"https://api.rugcheck.xyz/v1/tokens/{m}/report/summary", timeout=8)
    except Exception: return None
    dg = sorted(r.get("name") for r in rc.get("risks") or [] if r.get("level") == "danger"); old = RC.get(m); RC[m] = dg
    if rc.get("rugged"): return "rugcheck flags RUGGED"
    if old is not None and set(dg) - set(old): return "new danger: " + ", ".join(set(dg) - set(old))
# ---------- 249 anti-chase / 250 pump duration ----------
def chasing(pair):
    pc = pair.get("priceChange") or {}
    return f"already +{pc.get('h1')}% in 1h and +{pc.get('m5')}% in 5m (anti-chase)" if (pc.get("h1") or 0) > 80 and (pc.get("m5") or 0) > 10 else None
def learn_pump(ct, mins_to_peak):
    e = B.setdefault("pump_minutes", {}).setdefault(ct, None); B["pump_minutes"][ct] = round(mins_to_peak if e is None else 0.7 * e + 0.3 * mins_to_peak, 1)
# ---------- 254 starter buy + add on confirmation ----------
STARTER = 0.6
# ---------- 256 data source accuracy trust ----------
def source_trust(dex_px, others):
    for name, px in others.items():
        if px: d = abs(px / dex_px - 1); s = B.setdefault("source_err", {}).setdefault(name, [0, 0.0]); s[0] += 1; s[1] = round(s[1] + d, 4)
# ---------- 258 v3x back-off ----------
def v3x_backoff():
    x = sorted(brain5._trades(brain5.EXP, 2), key=lambda p: p["closed"])[-5:]; s = 0
    for p in reversed(x):
        if p["tot"] < 0: s += 1
        else: break
    if s >= 3 and time.time() - x[-1]["closed"] < 1800: return None, f"v3x back-off: {s} straight losses, 30 min pause"
    return (0.5 if s == 2 else 1.0), None
# ---------- 259 counterfactuals / 260 smartest & worst move ----------
def counterfactual(rows):
    if not rows: return 0
    mk = dex_market([r[0] for r in rows]); c = conn(); n = 0
    c.execute("CREATE TABLE IF NOT EXISTS counterfactual(mint TEXT PRIMARY KEY, rule TEXT, px0 REAL, px1 REAL, pct REAL, ts REAL)")
    for m, rule, px in rows:
        q = float((mk.get(m) or {}).get("priceUsd") or 0)
        if px and q: c.execute("INSERT OR REPLACE INTO counterfactual VALUES(?,?,?,?,?,?)", (m, rule, px, q, round((q / px - 1) * 100, 1), time.time())); n += 1
    c.commit(); c.close(); return n
def best_worst_line():
    c = conn(); t = time.time() - 86400
    try:
        sm = c.execute("SELECT rule, pct FROM counterfactual WHERE ts>? AND pct<-20 ORDER BY pct ASC LIMIT 1", (t,)).fetchone()
        mw = c.execute("SELECT rule, pct FROM counterfactual WHERE ts>? AND pct>20 ORDER BY pct DESC LIMIT 1", (t,)).fetchone()
    except Exception: sm = mw = None
    bt = c.execute("SELECT symbol, pnl FROM positions WHERE status='closed' AND version=? AND closed>? ORDER BY pnl DESC LIMIT 1", (CFG["VERSION"], t)).fetchone()
    wt = c.execute("SELECT symbol, pnl FROM positions WHERE status='closed' AND version=? AND closed>? ORDER BY pnl ASC LIMIT 1", (CFG["VERSION"], t)).fetchone(); c.close()
    parts = []
    if sm: parts.append(f"smartest pass: '{sm['rule']}' dodged a {sm['pct']:+.0f}% coin")
    if bt and bt["pnl"] > 0: parts.append(f"best trade {bt['symbol']} ${bt['pnl']:+.2f}")
    if mw and mw["pct"] > 0: parts.append(f"worst pass: '{mw['rule']}' skipped a {mw['pct']:+.0f}% coin")
    if wt and wt["pnl"] < 0: parts.append(f"worst trade {wt['symbol']} ${wt['pnl']:+.2f}")
    return "Smartest/worst: " + ("; ".join(parts) if parts else "not enough data yet")
# ---------- 240 'how much smarter' weekly section ----------
def smarter_section():
    t, n = brain5.calib_table(); g = B.get("decision_grades") or {}
    return (f"\n## How much smarter this week\n- Calibration table (by confidence band): {t} on {n} weighted trades\n- Decision grades: {g}\n"
            f"- Agent trust: {B['trust']} · mentor: {B.get('mentor')}\n- Learned wait: {B.get('learned_wait')}s · pump minutes by type: {B.get('pump_minutes')}\n"
            f"- v3x A/B arms (target 20% vs 35%): {ab_tally()}\n- Data source error (avg): {({k: round(v[1]/max(1,v[0]),4) for k, v in (B.get('source_err') or {}).items()})}\n")
