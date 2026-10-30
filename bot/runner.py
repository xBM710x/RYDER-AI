"""Night Desk runner (PAPER ONLY). v3: scan every 30s + live websocket launches, positions every 1s, delayed entry with recheck."""
import time, sys, traceback, threading
from common import CFG, dex_market
from logger import conn, log
import scout, filters, analyst, executor, risk, detect, feed, json, os
PENDING = {}  # mint -> entry candidate waiting ENTRY_DELAY
HB = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'heartbeat.json')
DEVBAL = {}  # open-position mint -> (creator, baseline balance, last check ts)
def scan():
    cands, total = scout.scout(); mkt = dex_market([c["mint"] for c in cands]) if cands else {}
    log("scan", n_raw=total, n_new_or_due=len(cands))
    for cd in cands:
        m = cd["mint"]; pair = mkt.get(m); sym = (pair or {}).get("baseToken", {}).get("symbol") or cd["name"]
        if pair and cd["dex"].startswith("unknown"): cd["dex"] = scout.tag(pair.get("dexId", ""), m)
        res = filters.check(m, pair); ok, why = filters.verdict(res)
        c = conn(); r = c.execute("SELECT checks FROM seen WHERE mint=?", (m,)).fetchone()
        checks = (r["checks"] if r else 0) + 1
        # only volume kills are retryable (young tokens grow); safety kills are final
        final = not ((why.startswith("volume_1h") or why.startswith("liquidity")) and checks < CFG["MAX_CHECKS"]) or ok
        c.execute("UPDATE seen SET checks=?, last_ts=?, done=? WHERE mint=?", (checks, time.time(), int(final), m)); c.commit(); c.close()
        if not ok:
            log("kill", m, sym, reason=why.split(":")[0], detail=why, final=final, dex=cd["dex"], source=cd["source"],
                checks={k: v[0] + "/" + v[2] for k, v in res.items()}); continue
        sc, parts = analyst.score(pair, res)
        log("score", m, sym, score=sc, parts=parts, dex=cd["dex"], filters={k: v for k, v in res.items()})
        if sc < CFG["MIN_SCORE"]: log("kill", m, sym, reason="score<0.6", detail=f"score {sc}", final=True, dex=cd["dex"]); continue
        cr = res.get("_creator", ("", ""))[1]
        PENDING[m] = dict(t=time.time(), sym=sym, price=float(pair["priceUsd"]), score=sc, creator=cr,
                          devbal=detect.dev_balance(cr, m) if cr else None)
        log("entry_wait", m, sym, price=float(pair["priceUsd"]), delay=CFG["ENTRY_DELAY"], score=sc)
        time.sleep(0.3)
def pending():
    due = [m for m, p in PENDING.items() if time.time() - p["t"] >= CFG["ENTRY_DELAY"]]
    if not due: return
    mkt = dex_market(due)
    for m in due:
        p = PENDING.pop(m); pair = mkt.get(m)
        if not pair or not pair.get("priceUsd"): log("kill", m, p["sym"], reason="recheck", detail="no price on recheck", final=True); continue
        ch = float(pair["priceUsd"]) / p["price"] - 1
        if ch > CFG["MAX_PUMP"]: log("kill", m, p["sym"], reason="recheck", detail=f"pumped {ch*100:+.1f}% during wait (chasing)", final=True); continue
        if ch < CFG["MAX_DUMP"]: log("kill", m, p["sym"], reason="recheck", detail=f"dumping {ch*100:+.1f}% during wait", final=True); continue
        if p["creator"]:
            now = detect.dev_balance(p["creator"], m)
            if detect.dev_sold(p["devbal"], now):
                log("kill", m, p["sym"], reason="dev_sell", detail=f"dev sold {p['devbal']:.0f}->{now:.0f} during wait", final=True)
                detect.add_rugger(p["creator"], "sold early on " + m[:8]); continue
        executor.buy(m, p["sym"], pair, p["score"])
        if p["creator"]: DEVBAL[m] = (p["creator"], detect.dev_balance(p["creator"], m), time.time())
def positions():
    c = conn(); ps = [dict(r) for r in c.execute("SELECT * FROM positions WHERE status='open'")]; c.close()
    if not ps: return
    mkt = dex_market([p["mint"] for p in ps])
    for p in ps:
        pr = mkt.get(p["mint"])
        if not pr or not pr.get("priceUsd"): continue
        price = float(pr["priceUsd"])
        dv = DEVBAL.get(p["mint"])
        if dv and time.time() - dv[2] > 30:  # v3: dev-sell watch on open positions, every 30s
            nb = detect.dev_balance(dv[0], p["mint"]); DEVBAL[p["mint"]] = (dv[0], dv[1], time.time())
            if detect.dev_sold(dv[1], nb):
                executor.sell(p, price, "dev_sell"); detect.add_rugger(dv[0], "sold while we held " + p["mint"][:8]); DEVBAL.pop(p["mint"], None); continue
        u = risk.update(p, price)
        if u["time_stop"]: executor.sell(p, price, "time_stop"); continue
        if u["partial"]: executor.partial(p, price); p = dict(p, qty=p["qty"] / 2, cost=p["cost"] / 2, tp_done=1)
        if u["exit"]: executor.sell(p, price, "trailing_stop" if u["trailing"] else "stop_loss"); continue
        c = conn(); c.execute("UPDATE positions SET peak=?,stop=?,trailing=? WHERE id=?", (u["peak"], u["stop"], u["trailing"], p["id"])); c.commit(); c.close()
        if u["trailing"] and not p["trailing"]: log("trail_on", p["mint"], p["symbol"], price=price, stop=u["stop"])
def main(cycles=None):
    log("start", mode="PAPER", cfg=CFG); n = 0
    feed.start()
    def pos_loop():
        k = 0
        while True:
            k += 1
            try:
                positions()
                if k % 5 == 0: pending()
                if k % 600 == 0: detect.sweep_dead(); analyst.retune()
                if k % 10 == 0: json.dump(dict(ts=time.time(), pending=len(PENDING), ws=feed.STATS), open(HB, "w"))
            except Exception: log("error", where="positions", trace=traceback.format_exc()[-800:])
            time.sleep(CFG["POS_SEC"])
    threading.Thread(target=pos_loop, daemon=True).start()
    while cycles is None or n < cycles:
        t0 = time.time()
        try: scan(); n += 1
        except Exception: log("error", where="scan", trace=traceback.format_exc()[-800:])
        time.sleep(max(1, CFG["SCAN_SEC"] - (time.time() - t0)))
if __name__ == "__main__": main(int(sys.argv[1]) if len(sys.argv) > 1 else None)
