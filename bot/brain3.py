"""Upgrades 161-180 + Telegram lookup, holdings rug watch, daily X recap link, weekly report (PAPER ONLY; read-only public data).
RYDER never posts to X and never touches wallets: the X recap is only a prefilled intent link sent to Braydon's own Telegram chat."""
import time, json, os, re, threading, urllib.request, urllib.parse, collections
from concurrent.futures import ThreadPoolExecutor
from common import CFG, http_json, dex_market
from logger import conn, log
import alerts, brain2
D = os.path.dirname(os.path.abspath(__file__)); RP = os.path.join(D, "reports"); os.makedirs(RP, exist_ok=True)
POOL = ThreadPoolExecutor(max_workers=8)  # 180 parallel network checks
ADDR = re.compile(r"\b[1-9A-HJ-NP-Za-km-z]{32,44}\b")
# ---------- (B)/171 holdings rug watch: Braydon's coins, read-only ----------
HOLD = {"DARK": "7KEPApdbBMByrmqihz3bht2uMhFQcatjfSFQCKq66kH3", "NIO": "7SL2VnfYsChvog5oQY9Nmtqu1wceaMiQzWoqoLQpump",
        "CATE": "Ai66LHZG9MCzg1WKdawwqduVAXpNDUuV8M3uyq5ppump", "GTA VI": "4kjruqGHDsSqkMdFfCjV7Vb62HPFhtXyWc2t6JpQzDnz",
        "STONKLANA": "GF74fBfcaeLjUiUwKpRiUbvMQtTvNyzMoo6KNyyqNyk6", "AudaCity": "DKYcjobF7HPtL9RyQBRdeRQ2iWvizpfbgWwPWNXdpump",
        "Blacklist": "CZwjVLau4LEwEsojxYdeyyagAjYtRhwbwe7jCezhpump"}  # GNS: no contract found in desk files
HS = os.path.join(D, "holdings_state.json")
def _risk(m, pair):
    flags = []
    try:
        rc = http_json(f"https://api.rugcheck.xyz/v1/tokens/{m}/report", timeout=20)
        flags += [r.get("name") for r in rc.get("risks") or [] if r.get("level") == "danger"]
        if rc.get("rugged"): flags.append("RUGGED")
        hs = brain2.holder_scores(rc)
        if hs.get("top10", 0) > 35: flags.append(f"top10 {hs['top10']}%")
    except Exception: pass
    tx = (pair.get("txns") or {}).get("m5") or {}
    if (tx.get("sells") or 0) > 3 * max(1, tx.get("buys") or 0) and (tx.get("sells") or 0) >= 15: flags.append("sell wave 5m")
    return sorted(set(f for f in flags if f))
def holdings_watch():
    try: st = json.load(open(HS))
    except Exception: st = {}
    mk = dex_market(list(dict(HOLD).values())); fut = {s: POOL.submit(_risk, m, mk.get(m) or {}) for s, m in list(HOLD.items()) if mk.get(m)}
    for s, m in list(HOLD.items()):
        pr = mk.get(m)
        if not pr: continue
        px, liq = float(pr.get("priceUsd") or 0), (pr.get("liquidity") or {}).get("usd") or 0; fl = fut[s].result(); o = st.get(s)
        msgs = []
        if o and o.get("px") and abs(px / o["px"] - 1) >= 0.15: msgs.append(f"moved {(px/o['px']-1)*100:+.0f}% since last ping")
        if o and o.get("liq") and liq < o["liq"] * 0.7: msgs.append(f"liquidity dropped {(1-liq/o['liq'])*100:.0f}% (LP pull risk)")
        new = [f for f in fl if f not in (o or {}).get("flags", [])]
        if o is not None and new: msgs.append("new risk: " + ", ".join(new))
        if msgs: alerts.send_async(f"👀 RYDER watch · {s}\n" + "\n".join(msgs) + f"\nprice ${alerts.fmt(px)} · liq ${liq:,.0f}\n{pr.get('url','')}\n(read-only watch, no trades)")
        if o is None or msgs: st[s] = dict(px=px, liq=liq, flags=fl, t=time.time())  # baseline moves only when we ping
        else: st[s]["flags"] = fl
    json.dump(st, open(HS, "w"))
# ---------- (A) Telegram coin lookup ----------
_off = [0]
def lookup(m):
    import filters, analyst, brain
    pair = dex_market([m]).get(m)
    if not pair: return f"🔎 {m[:6]}…: no DexScreener pair yet (too new or not a Solana token)."
    sym = (pair.get("baseToken") or {}).get("symbol"); res = filters.check(m, pair); ok, why = filters.verdict(res)
    st, rs, sd = brain.structure(pair); sc, parts = analyst.score(pair, dict({"top10": ("unknown", "25", "n/a")}, **res)); f = brain.features(pair, parts, sc); wp, _ = brain.win_prob(f)
    v = brain2.votes(dict(source="lookup", t=time.time()), pair, res, sc, wp, sc, brain2.HS.get(m), dict(open=0, day_pnl=0, regime=(__import__("extras").STATE.get("regime") or {}).get("mood"), impact=None, lesson_score=brain2.lesson_score()))
    go, cons, size, rsn = brain2.decide(v)
    chk = "\n".join(f"{'✅' if s == 'pass' else '❌' if s == 'fail' else '❔'} {k}: {d[:60]}" for k, (s, d, p) in res.items() if not k.startswith("_"))
    liq = (pair.get("liquidity") or {}).get("usd") or 0; mc = pair.get("marketCap") or pair.get("fdv") or 0
    verdict = "WOULD BUY (paper)" if ok and go and st != "fail" else "PASS"
    return (f"🔎 RYDER read · {sym}\n{verdict} — {rsn if ok else why[:120]}\nprice ${alerts.fmt(float(pair['priceUsd']))} · liq ${liq:,.0f} · mcap ${mc:,.0f}\n"
            f"score {sc} · win prob {wp} · structure: {sd[:80]}\nCouncil: " + ", ".join(f"{a} {x[0]:.2f}" for a, x in v.items()) + f"\n{chk}\n{pair.get('url','')}\n(paper read only, not advice)")
def tg_poll():
    cid = alerts.chat_id()
    if not cid: return
    r = alerts._api("getUpdates", offset=_off[0] + 1, timeout=0) or {}
    for u in r.get("result") or []:
        _off[0] = max(_off[0], u["update_id"]); msg = u.get("message") or {}
        if str((msg.get("chat") or {}).get("id")) != cid: continue  # only Braydon's saved chat
        for m in ADDR.findall(msg.get("text") or "")[:2]:
            def go(m=m):
                try: alerts.send(lookup(m)[:3900])
                except Exception as e: alerts.send(f"🔎 lookup failed for {m[:6]}…: {type(e).__name__}")
            POOL.submit(go)
def tg_loop():
    alerts.chat_id(); r = alerts._api("getUpdates", offset=-1) or {}  # skip backlog
    for u in r.get("result") or []: _off[0] = u["update_id"]
    while True:
        try: tg_poll()
        except Exception: pass
        time.sleep(4)
# ---------- (C) daily X recap intent link / (D)+179 weekly report ----------
def _closed(since):
    c = conn(); r = [dict(x) for x in c.execute("SELECT * FROM positions WHERE status='closed' AND version=? AND closed>?", (CFG["VERSION"], since))]; c.close(); return r
def x_recap():
    cl = _closed(time.time() - 86400); w = sum(p["pnl"] > 0 for p in cl); pnl = sum(p["pnl"] for p in cl)
    c = conn(); seen = c.execute("SELECT COUNT(*) FROM seen WHERE first_ts>?", (time.time() - 86400,)).fetchone()[0]; c.close()
    txt = f"RYDER ⭐ daily desk (paper trading)\n{seen:,} Solana coins scanned, {len(cl)} trades, {w}W/{len(cl)-w}L, P&L ${pnl:+.2f}\nSix agents, one brain. Picky on purpose."
    link = "https://x.com/intent/post?text=" + urllib.parse.quote(txt)
    alerts.send(f"📝 Daily X recap draft (tap to review & post yourself — RYDER never posts):\n\n{txt}\n\n{link}")
def weekly(send=True):
    cl = _closed(time.time() - 7 * 86400); w = sum(p["pnl"] > 0 for p in cl); pnl = sum(p["pnl"] for p in cl)
    rs = collections.Counter(p["reason"] for p in cl); best = max(cl, key=lambda p: p["pnl"], default=None)
    B = brain2.BRAIN; fn = os.path.join(RP, "weekly_" + time.strftime("%Y-%m-%d") + ".md")
    body = (f"# RYDER weekly report (paper) — week ending {time.strftime('%Y-%m-%d')}\n\n- Trades: {len(cl)} ({w}W/{len(cl)-w}L, win rate {w/max(1,len(cl)):.0%})\n- P&L: ${pnl:+.2f}\n"
            f"- Best: {best['symbol'] + ' $%+.2f' % best['pnl'] if best else 'n/a'}\n- Exit reasons: {dict(rs)}\n- Agent trust: {B['trust']}\n- Thresholds: {B['thresholds']}\n"
            f"- Lessons:\n" + "\n".join(f"  - {l}" for l in (B["lessons"][:6] or ["not enough trades yet"])) + "\n")
    body += __import__("brain6").smarter_section()  # 240
    body += __import__("brain7").week_lessons()  # 299
    open(fn, "w").write(body)
    if send: alerts.send("📚 RYDER weekly — what I learned (paper)\n" + body.replace("# ", "")[:3500])
    return fn
# ---------- 161 pre-graduation tracking ----------
def pregrad():
    ws = [m for m, t in list(brain2.WATCH.items()) if time.time() - t < 3 * 3600][-60:]
    if not ws: return
    mk = dex_market(ws); c = conn(); n = 0
    for m in ws:
        pr = mk.get(m); mc = (pr or {}).get("marketCap") or 0
        if pr and mc >= 40_000 and (pr.get("dexId") in ("pumpfun", "pump-fun")):  # ~60%+ of the bonding curve
            r = c.execute("UPDATE seen SET done=0, checks=MIN(checks,?), last_ts=0 WHERE mint=? AND done=1", (CFG["MAX_CHECKS"] - 1, m)).rowcount; n += r
    c.commit(); c.close(); brain2.STATS["pregrad_requeue"] += n
# ---------- 165 social link validity ----------
def links_ok(pair):
    ws = [w.get("url") for w in ((pair.get("info") or {}).get("websites") or []) if w.get("url")][:2]
    if not ws: return True, "no website"
    def ping(u):
        try:
            with urllib.request.urlopen(urllib.request.Request(u, method="GET", headers={"User-Agent": "Mozilla/5.0"}), timeout=5) as r: return r.status < 400
        except urllib.error.HTTPError as e: return e.code in (401, 403, 429)  # bot-blocked but alive
        except Exception: return False
    alive = list(POOL.map(ping, ws))
    return any(alive), f"{sum(alive)}/{len(ws)} websites alive"
# ---------- 167 strength-adjusted stop / 169 higher lows / 175 launch momentum ----------
def strength_stop(base, cons):
    return round(max(0.05, min(0.12, base * (0.85 + (cons or 0.55) * 0.4))), 3)
def higher_lows(mint):
    q = [x[1] for x in brain2.TK.get(mint, []) if x[1]]
    if len(q) < 9: return "unknown"
    k = len(q) // 3; lows = [min(q[:k]), min(q[k:2 * k]), min(q[2 * k:])]
    return "higher" if lows[0] < lows[1] < lows[2] else "lower" if lows[0] > lows[1] > lows[2] else "flat"
def launch_momentum(pair, holder_rate=0):
    tx = pair.get("txns") or {}; b5 = (tx.get("m5") or {}).get("buys") or 0; bh = (tx.get("h1") or {}).get("buys") or 0
    accel = b5 / max(1, bh / 12)
    return round(min(1, 0.4 * min(1, accel / 2) + 0.3 * min(1, holder_rate / 10) + 0.3 * brain2.pressure(pair)), 3)
# ---------- 172 Jupiter price cross-check ----------
def jup_ok(m, px):
    try:
        j = http_json(f"https://lite-api.jup.ag/price/v3?ids={m}", timeout=6); jp = float((j.get(m) or {}).get("usdPrice") or 0)
    except Exception: return True, "jupiter unavailable (not counted)"
    if not jp: return True, "no jupiter price (not counted)"
    dv = abs(jp / px - 1); return dv <= 0.06, f"dexscreener vs jupiter differ {dv*100:.1f}%"
# ---------- 176 best hours ----------
def scan_sec():
    return 20 if brain2.tod_score() >= 0.6 else 30
# ---------- 178 mood-adjusted max open ----------
def max_open(reg): return {"risk-off": 2, "hot": 4}.get((reg or {}).get("mood"), 3)
# ---------- 174 shadow-test a threshold change against recorded trades before adopting it ----------
def shadow_ok(cs, old, new):
    keep = lambda th: sum(p for c, p in cs if c >= th)
    return keep(new) >= keep(old), f"shadow: old bar ${keep(old):+.2f} vs new ${keep(new):+.2f}"
# ---------- scheduler (called every second from the positions loop) ----------
_last = collections.defaultdict(float); _day = {}
def jobs(k):
    now = time.time(); lt = time.localtime()
    def every(name, s, fn):
        if now - _last[name] >= s: _last[name] = now; POOL.submit(_safe, name, fn)
    every("holdings", 120, holdings_watch); every("fomo_wallet", 60, __import__("wallet_watch").tick); every("pregrad", 60, pregrad)
    CFG["SCAN_SEC"] = scan_sec() if k % 300 == 0 else CFG["SCAN_SEC"]
    d = time.strftime("%F")
    if lt.tm_hour == 21 and _day.get("x") != d: _day["x"] = d; POOL.submit(_safe, "x_recap", x_recap)
    if lt.tm_wday == 6 and lt.tm_hour == 9 and _day.get("w") != d: _day["w"] = d; POOL.submit(_safe, "weekly", weekly)
def _safe(name, fn):
    try: fn()
    except Exception as e: log("error", where="brain3." + name, trace=str(e)[:200])
def start(): threading.Thread(target=tg_loop, daemon=True).start()
