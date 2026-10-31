"""Builds the Page DATA line from desk.db only. Output: page_data_line.txt (one line: `const DATA: any = {...};`)."""
import json, collections, time, os
from logger import conn
from common import CFG, dex_market
T = lambda ts: time.strftime("%H:%M:%S", time.localtime(ts))
c = conn(); V = CFG["VERSION"]; CK = "cash" if V == "v1" else "cash_" + V
def vsum(v):
    cl = c.execute("SELECT pnl,exit,stop,reason FROM positions WHERE status='closed' AND version=?", (v,)).fetchall()
    ck = "cash" if v == "v1" else "cash_" + v
    cash = (c.execute("SELECT v FROM account WHERE k=?", (ck,)).fetchone() or [CFG["START_BALANCE"]])[0]
    sl = [(r["exit"] / r["stop"] - 1) * 100 for r in cl if r["reason"] == "stop_loss"]
    return dict(v=v, trades=len(cl), wins=sum(r["pnl"] > 0 for r in cl), pnl=round(sum(r["pnl"] for r in cl), 2), cash=round(cash, 2),
                slip=round(sum(sl) / len(sl), 1) if sl else None)
versions = [vsum(r[0]) for r in c.execute("SELECT DISTINCT version FROM positions UNION SELECT DISTINCT version FROM events ORDER BY 1")]
ev = [dict(r) for r in c.execute("SELECT * FROM events WHERE version=? ORDER BY ts", (V,))]
for e in ev: e["d"] = json.loads(e["data"])
first = {}
for e in ev:
    if e["kind"] in ("kill", "score") and e["mint"] and e["mint"] not in first: first[e["mint"]] = e["d"].get("dex", "unknown")
def fam(d):
    d = d.lower()
    for k in ("letsbonk", "pumpswap", "pumpfun", "raydium", "meteora", "orca"):
        if k in d: return k
    return "pump-origin (other)" if "pump" in d else "other/unknown"
by_dex = collections.Counter(fam(d) for d in first.values())
kills = collections.Counter(e["d"]["reason"] for e in ev if e["kind"] == "kill")
final_kills = collections.Counter(e["d"]["reason"] for e in ev if e["kind"] == "kill" and e["d"].get("final", True))
cl = [dict(r) for r in c.execute("SELECT * FROM positions WHERE status='closed' AND version=? ORDER BY closed", (V,))]
op = [dict(r) for r in c.execute("SELECT * FROM positions WHERE status='open' AND version=?", (V,))]
mkt = dex_market([p["mint"] for p in op]) if op else {}
cash = (c.execute("SELECT v FROM account WHERE k=?", (CK,)).fetchone() or [CFG["START_BALANCE"]])[0]
unreal = 0; opens = []
for p in op:
    px = float((mkt.get(p["mint"]) or {}).get("priceUsd") or p["entry"]); u = p["qty"] * px - p["cost"]; unreal += u
    opens.append(dict(sym=p["symbol"], entry=p["entry"], now=px, stop=p["stop"], trail=bool(p["trailing"]), usd=round(p["cost"], 2), pnl=round(u, 2)))
eq = CFG["START_BALANCE"]; curve = [dict(t=time.strftime("%H:%M", time.localtime(ev[0]["ts"])), v=eq)]
for p in cl: eq += p["pnl"]; curve.append(dict(t=time.strftime("%H:%M", time.localtime(p["closed"])), v=round(eq, 2)))
now_eq = cash + sum(p["cost"] for p in op) + unreal
curve.append(dict(t=time.strftime("%H:%M"), v=round(now_eq, 2)))
closed = [dict(sym=p["symbol"], entry=p["entry"], exit=p["exit"], pnl=round(p["pnl"], 2), pct=round((p["exit"]/p["entry"]-1)*100, 1), reason=p["reason"], t=time.strftime("%H:%M", time.localtime(p["closed"]))) for p in cl]
stops = [x for x in closed if x["reason"] == "stop_loss"]
slip = [round((p["exit"] / p["stop"] - 1) * 100, 1) for p in cl if p["reason"] == "stop_loss"]
last = lambda kinds: next((e for e in reversed(ev) if e["kind"] in kinds), None)
def desc(e):
    if not e: return "none yet"
    d = e["d"]; s = e["symbol"] or ""
    return {"scan": f"scan: {d.get('n_raw')} raw, {d.get('n_new_or_due')} new/due", "kill": f"killed {s}: {d.get('detail','')[:60]}",
            "score": f"scored {s} {d.get('score')}", "paper_buy": f"paper buy {s} ${d.get('usd')} @ {d.get('price')}",
            "paper_exit": f"exit {s} {d.get('pct')}% ({d.get('reason')})", "trail_on": f"trail on {s}"}.get(e["kind"], e["kind"]) + " @ " + T(e["ts"])
nk = sum(kills.values()); seen = len({e["mint"] for e in ev if e["kind"] in ("kill", "score")})
agents = [
  dict(name="Scout", stat=f"{seen} pairs scanned", last=desc(last({"scan"}))),
  dict(name="Filter", stat=f"{round(100*(seen-sum(e['kind']=='score' for e in ev))/max(seen,1))}% killed ({seen-sum(e['kind']=='score' for e in ev)}/{seen})", last=desc(last({"kill"}))),
  dict(name="Analyst", stat=f"{sum(e['kind']=='score' for e in ev)} scored", last=desc(last({"score"}))),
  dict(name="Executor", stat=f"{len(cl)+len(op)} paper trades", last=desc(last({"paper_buy"}))),
  dict(name="Risk", stat=f"{len(stops)} stops, {sum(x['reason']=='trailing_stop' for x in closed)} trail exits, {sum(e['kind']=='trail_on' for e in ev)} trails armed", last=desc(last({"paper_exit", "trail_on"}))),
  dict(name="Logger", stat=f"{len(ev)} events, {len(kills)} kill reasons", last=desc(ev[-1] if ev else None)),
]
AG = dict(entry_wait="EXECUTOR", rug_list_add="FILTER", scan="SCOUT", kill="FILTER", score="ANALYST", paper_buy="EXECUTOR", paper_exit="RISK", trail_on="RISK", start="LOGGER", error="LOGGER")
def short(e):
    d = e["d"]; s = e["symbol"] or ""; k = e["kind"]
    if k == "scan": return f"scan · {d.get('n_raw')} pairs, {d.get('n_new_or_due')} new", ""
    if k == "kill":
        lab = dict(volume_1h="1h vol < $40k", lp_locked="LP not locked", bundled="bundled launch", top10="top10 > 25%", dev_rugs="dev rug history",
                   mint_authority="mint not revoked", freeze_authority="freeze set", liquidity="liq < $25k", recheck="failed entry recheck", dev_sell="dev sold early", holder_cluster="holders share funder", pressure="sells > buys", socials="no/dupe socials", wash="wash trading").get(d.get("reason"), d.get("reason"))
        if d.get("reason") == "score<0.6": lab = "score " + d.get("detail", "")[6:] + " < 0.6"
        return f"killed {s[:14]} · {lab}", "red"
    if k == "score": return (f"{s} score {d.get('score')} ✓", "green") if d.get("score", 0) >= CFG["MIN_SCORE"] else (f"{s} score {d.get('score')} ✗", "red")
    if k == "entry_wait": return f"{s} waiting {d.get('delay')}s to recheck", ""
    if k == "rug_list_add": return f"rug wallet listed {str(d.get('wallet'))[:6]}", "red"
    if k == "paper_buy": return f"bought {s} · ${d.get('usd')}", "green"
    if k == "paper_exit": return f"sold {s} · {d.get('pct')}% ({d.get('reason')})", "green" if d.get("pnl", 0) > 0 else "red"
    return k, ""
def lastx(kinds):
    e = last(kinds); 
    if not e: return dict(text="none yet", tone="")
    t, tone = short(e); return dict(text=t, tone=tone)
dexof = {}
for e in ev:
    if e["kind"] == "score": dexof[e["mint"]] = fam(e["d"].get("dex", ""))
for x, p in zip(closed, cl): x["dex"] = dexof.get(p["mint"], "")
for x, p in zip(opens, op): x["dex"] = dexof.get(p["mint"], "")
agents2 = [dict(name=a["name"], stat=a["stat"]) for a in agents]
for a, kinds in zip(agents2, [{"scan"}, {"kill"}, {"score"}, {"paper_buy"}, {"paper_exit", "trail_on"}, set(AG)]): a.update(lastx(kinds))
agents2[0]["stat"] = f"{seen} pairs"; agents2[1]["stat"] = agents[1]["stat"].split(" (")[0]
agents2[3]["stat"] = "size ≤ 10% · 90s recheck" if V not in ("v1", "v2") else "size ≤ 10%"; agents2[4]["stat"] = "-8% · +15%"; agents2[5]["stat"] = f"{sum(kills.values())} why"
agents2[5]["text"] = f"wrote {sum(kills.values())} reasons"; agents2[5]["tone"] = ""
interesting = [e for e in ev if e["kind"] != "kill" or e["d"].get("reason") != "volume_1h"]
tail2 = [dict(t=time.strftime("%H:%M", time.localtime(e["ts"])), ag=AG.get(e["kind"], "LOGGER"), text=short(e)[0], tone=short(e)[1]) for e in interesting[-15:]]
tail = [f"{T(e['ts'])} {e['kind']:<10} {(e['symbol'] or '')[:12]:<12} " + json.dumps({k: v for k, v in e["d"].items() if k in ('reason','detail','score','price','usd','pct','pnl','n_raw','n_new_or_due')})[:110] for e in ev[-15:]]
out = dict(version=V, versions=versions, pos_sec=CFG["POS_SEC"], asof=time.strftime("%b %d %H:%M PT"), start=CFG["START_BALANCE"], equity=round(now_eq, 2), cash=round(cash, 2),
  scans=sum(e["kind"] == "scan" for e in ev), seen=seen, passed=sum(e["kind"] == "score" for e in ev), trades=len(cl) + len(op),
  wins=sum(x["pnl"] > 0 for x in closed), losses=sum(x["pnl"] <= 0 for x in closed), realized=round(sum(x["pnl"] for x in closed), 2),
  best=max(closed, key=lambda x: x["pnl"]) if closed else None, worst=min(closed, key=lambda x: x["pnl"]) if closed else None,
  stop_slippage=dict(n=len(slip), avg=round(sum(slip)/len(slip), 1) if slip else 0, worst=min(slip) if slip else 0),
  by_dex=by_dex.most_common(), kills=kills.most_common(), curve=curve, opens=opens, closed=closed[-15:], agents=agents2, tail=tail2, nkills=sum(kills.values()))
try: _hb = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "heartbeat.json")))
except Exception: _hb = {}
_lc = cl[-1] if cl else None; _recent = _lc and time.time() - _lc["closed"] < 3600
_last_act = max([e["ts"] for e in ev if e["kind"] in ("paper_buy", "paper_exit", "entry_wait")] or [0])
if (_hb.get("pending") or 0) > 0 and time.time() - _hb.get("ts", 0) < 120: out["mood"] = "alert"
elif _recent and _lc["pnl"] > 0: out["mood"] = "happy"
elif _recent and _lc["pnl"] <= 0: out["mood"] = "sad"
elif op or time.time() - _last_act < 1800: out["mood"] = "happy" if now_eq >= CFG["START_BALANCE"] and (op or cl) else ("sad" if now_eq < CFG["START_BALANCE"] else "alert")
else: out["mood"] = "sleepy"
# ---- v3 compact data fields (41-60) ----
import backtest
out["kills_live"] = _hb.get("kills_live") or [dict(t=time.strftime("%H:%M:%S", time.localtime(e["ts"])), sym=(e["symbol"] or "")[:14], reason=e["d"].get("reason")) for e in ev if e["kind"] == "kill" and e["d"].get("final", True)][-12:]
out["watchlist"] = _hb.get("watch") or []
out["reentry_watch"] = _hb.get("reentry") or []
_rk = dict(_hb.get("risk") or {}); _d0 = time.mktime(time.localtime()[:3] + (0, 0, 0, 0, 0, -1))
_today = round(sum(p["pnl"] for p in cl if p["closed"] >= _d0), 2); _lim = -0.15 * CFG["START_BALANCE"]
_st = 0
for p in reversed([p for p in cl if p["reason"] != "partial_tp"]):
    if p["pnl"] > 0: break
    _st += 1
out["risk_state"] = dict(day_pnl=_today, day_limit=_lim, day_used_pct=round(min(100, max(0, _today / _lim * 100)), 1), loss_streak=_st, paused=_today <= _lim,
    size_mult=_rk.get("size_mult", 1.0), trades_last_hour=sum(1 for p in cl + op if p["opened"] > time.time() - 3600), max_per_hour=CFG["MAX_PER_HOUR"])
out["funnel"] = dict(scanned=seen, passed_filters=sum(e["kind"] == "score" for e in ev), scored_ok=sum(e["kind"] == "score" and e["d"].get("score", 0) >= CFG["MIN_SCORE"] for e in ev),
    entry_wait=sum(e["kind"] == "entry_wait" for e in ev), traded=len({p["mint"] for p in cl + op}))
_hr = collections.defaultdict(lambda: dict(scans=0, kills=0, trades=0, pnl=0.0))
for e in ev:
    h = time.strftime("%H", time.localtime(e["ts"])); k = e["kind"]
    if k == "scan": _hr[h]["scans"] += 1
    elif k == "kill": _hr[h]["kills"] += 1
    elif k == "paper_buy": _hr[h]["trades"] += 1
for p in cl: _hr[time.strftime("%H", time.localtime(p["closed"]))]["pnl"] += p["pnl"]
out["hourly"] = [dict(h=h, **{k: (round(v, 2) if isinstance(v, float) else v) for k, v in d.items()}) for h, d in sorted(_hr.items())][-24:]
_act = collections.Counter(AG.get(e["kind"], "LOGGER") for e in ev if e["ts"] > time.time() - 3600)
out["agent_activity"] = dict(_act)
try:
    _rl = [dict(r) for r in c.execute("SELECT wallet, reason, ts FROM rug_wallets ORDER BY ts DESC")]
    out["rug_list"] = dict(count=len(_rl), recent=[dict(w=r["wallet"][:6] + "…" + r["wallet"][-4:], why=r["reason"][:60]) for r in _rl[:5]])
except Exception: out["rug_list"] = dict(count=0, recent=[])
_nb = {e["mint"]: e["d"].get("narrative") or "other" for e in ev if e["kind"] == "paper_buy"}
_ns = collections.defaultdict(lambda: dict(trades=0, pnl=0.0))
for p in cl: n = _nb.get(p["mint"], "other"); _ns[n]["trades"] += 1; _ns[n]["pnl"] = round(_ns[n]["pnl"] + p["pnl"], 2)
out["narratives"] = dict(_ns)
_reg = _hb.get("regime") or {}
_mm = _reg.get("mood") or "unknown"; out["market_mood"] = dict(mood=_mm, sol_h1=_reg.get("sol_h1"), sol_h24=_reg.get("sol_h24"), size_mult=_reg.get("size_mult", 1.0),
    gauge=max(0, min(100, round(50 + (_reg.get("sol_h24") or 0) * 5))))
out["latency"] = _hb.get("latency") or {}
out["sources"] = {h: dict(ok_rate=v.get("ok_rate"), ms=v.get("ms"), err=v.get("err")) for h, v in (_hb.get("sources") or {}).items()}
_bc = {e["mint"]: e["d"] for e in ev if e["kind"] == "paper_buy"}
for o, p in zip(opens, op):
    b = _bc.get(p["mint"], {}); o["conf"] = b.get("conf"); o["narrative"] = b.get("narrative")
    o["stop_dist_pct"] = round((o["now"] / o["stop"] - 1) * 100, 1) if o["stop"] else None; o["gain_pct"] = round((o["now"] / p["entry"] - 1) * 100, 1)
    o["trail_at"] = round(p["entry"] * (1 + CFG["TRAIL_ACTIVATE"]), 12); o["peak"] = p["peak"]
try: out["backtest"] = backtest.run(V)
except Exception: out["backtest"] = None
try: out["weights"] = __import__("analyst").weights()
except Exception: pass
out["postmortems"] = [dict(sym=e["symbol"], **{k: e["d"].get(k) for k in ("exit_pct", "peak_pct", "held_min", "reason", "lesson")}) for e in ev if e["kind"] == "postmortem"][-5:]
out["alerts"] = dict(telegram_x="not configured (needs Braydon's own bot token/chat; skipped)")
# ---- 61-120 compact fields ----
try:
    import brain, more
    out["speed"] = dict(decision_s=_hb.get("decision_s"), deep_check_s=_hb.get("deep_check_s"), inflight=_hb.get("inflight"), workers=6, ws_wake=True)
    out["brain"] = dict(model=_hb.get("model"), paused=_hb.get("paused"), drift=brain.drift(), calibration=brain.calibration(), memory_top=dict(sorted(brain.memory().items(), key=lambda kv: -kv[1]["n"])[:8]),
                        audit=brain.audit_summary(), champion=dict(promoted=brain.promoted(), challenger=next((v for v in versions if v["v"] == V + "b"), None)))
    out["lessons"] = brain.lessons()[:5]
    out["rug_timing"] = _hb.get("rug_timing") or more.rug_timing()
    out["migrations_seen"] = _hb.get("migrations", 0)
    _bw = {e["mint"]: e["d"] for e in ev if e["kind"] == "paper_buy"}
    for o, p in zip(opens, op): b = _bw.get(p["mint"], {}); o["win_prob"] = b.get("win_prob"); o["why"] = b.get("why")
    for x, p in zip(closed, cl[-15:]): b = _bw.get(p["mint"], {}); x["win_prob"] = b.get("win_prob"); x["why"] = b.get("why")
    out["skipped_features"] = ["103/104 X shill + mention velocity: needs X API access inside the bot loop", "105 curated KOL list: none supplied; uses learned smart wallets (#21)", "39 Telegram/X alerts"]
except Exception as _e: out["brain_err"] = str(_e)[:120]
# ---- near-miss watchlist (display only; does not affect trading) ----
def _near_misses(limit=10, window=3600):
    LAB = dict(volume_1h="1h volume too low", liquidity="liquidity too low / unknown", pressure="more sells than buys", socials="no or reused socials",
               mint_authority="mint not revoked", freeze_authority="freeze authority set", top10="top 10 holders too heavy", lp_locked="LP not locked",
               dev_rugs="dev has rug history", bundled="bundled launch", bundle_sizes="bundled wallets", copycat="copycat name", honeypot="possible honeypot",
               mutable_meta="metadata changeable", wash="wash trading", holder_cluster="holders share a funder", dev_sell="dev sold early", recheck="failed entry recheck")
    now = time.time(); seenm = {}; P = os.path.join(os.path.dirname(os.path.abspath(__file__)), "events.jsonl")
    try: lines = open(P).readlines()[-20000:]
    except Exception: return []
    for l in lines:
        try: e = json.loads(l)
        except Exception: continue
        if e.get("ts", 0) < now - window or e.get("version", V) != V or not e.get("mint"): continue
        k = e.get("kind"); item = None
        if k == "kill":
            ch = e.get("checks") or {}; f = [n for n, v in ch.items() if str(v).startswith("fail")]; p = [n for n, v in ch.items() if str(v).startswith("pass")]
            r = e.get("reason") or ""
            if r.startswith("score<"): item = dict(why="score just under 0.6", rank=2)
            elif len(p) >= 2 and ((not f and r) or f == [r]):
                n = f[0] if f else r; item = dict(why=LAB.get(n, n.replace("_", " ")), rank=len(p))
        elif k == "score" and (e.get("score") or 0) < CFG["MIN_SCORE"] and (e.get("score") or 0) >= CFG["MIN_SCORE"] - 0.15:
            item = dict(why=f"score {e.get('score')} just under {CFG['MIN_SCORE']}", rank=9)
        if item:
            item.update(sym=(e.get("symbol") or "?")[:14], price=e.get("px") or e.get("price"), mcap=e.get("mcap") or e.get("fdv"), dex=fam(e.get("dex") or ""),
                        t=time.strftime("%H:%M", time.localtime(e["ts"])), ts=round(e["ts"]), near_miss=True)
            seenm[e["mint"]] = item
        elif k in ("score", "paper_buy"): seenm.pop(e["mint"], None)
    L = sorted(seenm.values(), key=lambda x: (x["ts"], x["rank"]), reverse=True)[:limit]
    for x in L: x.pop("rank", None)
    return L
try:
    if not out.get("watchlist"): out["watchlist"] = _near_misses()
    else: out["watchlist"] = list(out["watchlist"]) + _near_misses(max(0, 10 - len(out["watchlist"])))
except Exception: pass
# ---- all books in versions + v3x/v3b trades in existing lists (tagged; main-book stats untouched) ----
try:
    _have = {x["v"] for x in out["versions"]}
    for _v in ("v3b", "v3x"):
        if _v not in _have: out["versions"].append(vsum(_v))
    _LBL = dict(v1="v1", v2="v2", v3="v3 main", v3b="v3b strict", v3x="v3x FOMO practice")
    for x in out["versions"]: x["label"] = _LBL.get(x["v"], x["v"])
    import fomo as _fm
    _xb = {r["mint"]: json.loads(r["data"]) for r in c.execute("SELECT mint, data FROM events WHERE kind='paper_buy' ORDER BY ts")}
    def _tag(p): return "FOMO" if (_xb.get(p["mint"]) or {}).get("fomo") or _fm.is_fomo(p["mint"]) else "practice"
    _xc = [dict(r) for r in c.execute("SELECT * FROM positions WHERE status='closed' AND version='v3x' ORDER BY closed DESC LIMIT 10")][::-1]
    _xo = [dict(r) for r in c.execute("SELECT * FROM positions WHERE status='open' AND version='v3x'")]
    for p in _xc:
        out["closed"].append(dict(sym=f"{p['symbol']} · v3x {_tag(p)}", entry=p["entry"], exit=p["exit"], pnl=round(p["pnl"], 2), pct=round((p["exit"]/p["entry"]-1)*100, 1),
            reason=p["reason"], t=time.strftime("%H:%M", time.localtime(p["closed"])), dex=dexof.get(p["mint"], ""), book="v3x", practice=True, fomo=_tag(p) == "FOMO"))
    _xm = dex_market([p["mint"] for p in _xo]) if _xo else {}
    for p in _xo:
        px = float((_xm.get(p["mint"]) or {}).get("priceUsd") or p["entry"])
        out["opens"].append(dict(sym=f"{p['symbol']} · v3x {_tag(p)}", entry=p["entry"], now=px, stop=p["stop"], trail=bool(p["trailing"]), usd=round(p["cost"], 2),
            pnl=round(p["qty"] * px - p["cost"], 2), dex=dexof.get(p["mint"], ""), book="v3x", practice=True, fomo=_tag(p) == "FOMO"))
except Exception as _e: out["books_err"] = str(_e)[:120]
try:  # copy desk vC: same rows in the existing Trades lists, labelled 'copy' (data only, no new panel)
    _cb = {r["mint"]: json.loads(r["data"]).get("copy_of") for r in c.execute("SELECT mint, data FROM events WHERE kind='paper_buy' AND data LIKE '%copy_of%'")}
    for p in [dict(r) for r in c.execute("SELECT * FROM positions WHERE status='closed' AND version='vC' ORDER BY closed DESC LIMIT 10")][::-1]:
        out["closed"].append(dict(sym=f"{p['symbol']} · copy {_cb.get(p['mint']) or ''}".strip(), entry=p["entry"], exit=p["exit"], pnl=round(p["pnl"], 2), pct=round((p["exit"]/p["entry"]-1)*100, 1),
            reason=p["reason"], t=time.strftime("%H:%M", time.localtime(p["closed"])), dex=dexof.get(p["mint"], ""), book="vC", practice=True, copy=True))
    _co = [dict(r) for r in c.execute("SELECT * FROM positions WHERE status='open' AND version='vC'")]; _cm = dex_market([p["mint"] for p in _co]) if _co else {}
    for p in _co:
        px = float((_cm.get(p["mint"]) or {}).get("priceUsd") or p["entry"])
        out["opens"].append(dict(sym=f"{p['symbol']} · copy {_cb.get(p['mint']) or ''}".strip(), entry=p["entry"], now=px, stop=p["stop"], trail=bool(p["trailing"]), usd=round(p["cost"], 2),
            pnl=round(p["qty"] * px - p["cost"], 2), dex=dexof.get(p["mint"], ""), book="vC", practice=True, copy=True))
except Exception as _e: out["copy_err"] = str(_e)[:120]
try:  # read-only Fomo wallet summary (public address, no keys)
    _ws = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "wallet_watch_state.json")))
    _top = [x for x in (_ws.get("top") or []) if x.get("usd", 0) >= 1][:3]
    if _ws.get("sol_usd"): _top = sorted(_top + [dict(sym="SOL", usd=_ws["sol_usd"])], key=lambda x: -x["usd"])[:3]
    out["fomo_wallet"] = dict(total_usd=_ws.get("total_usd"), top=_top, at=time.strftime("%H:%M", time.localtime(_ws.get("t", 0))))
except Exception: pass
line = "const DATA: any = " + json.dumps(out) + ";"
open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "page_data_line.txt"), "w").write(line)
print(line)
