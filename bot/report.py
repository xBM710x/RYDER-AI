"""Morning summary, per version (v1 = original, v2 = upgraded)."""
import json, collections, time
from logger import conn
from common import CFG, dex_market
c = conn()
VERS = [r[0] for r in c.execute("SELECT DISTINCT version FROM events ORDER BY version")]
print("=== RYDER NIGHT DESK (PAPER) REPORT ===")
for V in VERS:
    ev = c.execute("SELECT kind,data,ts,mint FROM events WHERE version=?", (V,)).fetchall()
    scans = [e for e in ev if e["kind"] == "scan"]
    kills = collections.Counter(json.loads(e["data"])["reason"] for e in ev if e["kind"] == "kill" and json.loads(e["data"]).get("final", True))
    scores = [json.loads(e["data"])["score"] for e in ev if e["kind"] == "score"]
    seen = len({e["mint"] for e in ev if e["kind"] in ("kill", "score")})
    cl = c.execute("SELECT * FROM positions WHERE status='closed' AND version=?", (V,)).fetchall()
    op = c.execute("SELECT * FROM positions WHERE status='open' AND version=?", (V,)).fetchall()
    ck = "cash" if V == "v1" else "cash_" + V
    cash = (c.execute("SELECT v FROM account WHERE k=?", (ck,)).fetchone() or {"v": CFG["START_BALANCE"]})["v"]
    print(f"\n##### {V} #####")
    if ev: print("Window:", time.strftime("%m-%d %H:%M", time.localtime(ev[0]["ts"])), "->", time.strftime("%m-%d %H:%M", time.localtime(ev[-1]["ts"])), "(PT)")
    print(f"Scan cycles: {len(scans)} | tokens evaluated: {seen}")
    print("Killed by reason (final):"); [print(f"  {k:<18} {v}") for k, v in kills.most_common()]
    print(f"Scored: {len(scores)}  (avg {sum(scores)/len(scores):.2f})" if scores else "Scored: 0")
    w = [p for p in cl if p["pnl"] > 0]; print(f"Closed trades: {len(cl)} | wins {len(w)} | losses {len(cl)-len(w)} | realized ${sum(p['pnl'] for p in cl):+.2f}")
    for p in cl:
        sl = (p["exit"] / p["stop"] - 1) * 100 if p["reason"] == "stop_loss" else None
        print(f"  {p['symbol']:<10} {p['entry']:.8g} -> {p['exit']:.8g}  ${p['pnl']:+.2f} ({(p['exit']/p['entry']-1)*100:+.1f}%)  {p['reason']}" + (f"  slippage past stop {sl:.1f}%" if sl is not None else ""))
    mkt = dex_market([p["mint"] for p in op]) if op else {}; unreal = 0
    print(f"Open positions: {len(op)}")
    for p in op:
        px = float((mkt.get(p["mint"]) or {}).get("priceUsd") or p["entry"]); u = p["qty"] * px - p["cost"]; unreal += u
        print(f"  {p['symbol']:<10} entry {p['entry']:.8g} now {px:.8g} stop {p['stop']:.8g} {'TRAIL' if p['trailing'] else ''} ${u:+.2f}")
    eq = cash + sum(p["cost"] for p in op) + unreal
    print(f"Paper cash ${cash:.2f} | equity ${eq:.2f} | P&L ${eq-CFG['START_BALANCE']:+.2f} vs ${CFG['START_BALANCE']:.0f} start")
