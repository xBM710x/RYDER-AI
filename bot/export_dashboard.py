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
line = "const DATA: any = " + json.dumps(out) + ";"
open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "page_data_line.txt"), "w").write(line)
print(line)
