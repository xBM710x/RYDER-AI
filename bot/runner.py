"""Night Desk runner (PAPER ONLY). v3: scan every 30s + live websocket launches, positions every 1s, delayed entry with recheck."""
import time, sys, traceback, threading
from common import CFG, dex_market
from logger import conn, log
import scout, filters, analyst, executor, risk, detect, feed, json, os, extras, collections
REENTRY = {}  # 34: mint -> (exit price, ts, sym)
ENTRYLIQ = {}  # 26: mint -> liquidity at entry
LAT = collections.deque(maxlen=50); KILLS = collections.deque(maxlen=12)
PENDING = {}  # mint -> entry candidate waiting ENTRY_DELAY
HB = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'heartbeat.json')
DEVBAL = {}  # open-position mint -> (creator, baseline balance, last check ts)
def scan():
    t0 = time.time(); _scan(); LAT.append(round(time.time() - t0, 1))
def _scan():
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
            if final: KILLS.append(dict(t=time.strftime("%H:%M:%S"), sym=sym[:14], reason=why.split(":")[0]))
            log("kill", m, sym, reason=why.split(":")[0], detail=why, final=final, dex=cd["dex"], source=cd["source"],
                checks={k: v[0] + "/" + v[2] for k, v in res.items()}); continue
        sc, parts = analyst.score(pair, res)
        log("score", m, sym, score=sc, parts=parts, dex=cd["dex"], filters={k: v for k, v in res.items()})
        if sc < CFG["MIN_SCORE"]: log("kill", m, sym, reason="score<0.6", detail=f"score {sc}", final=True, dex=cd["dex"]); continue
        cr = res.get("_creator", ("", ""))[1]
        hn, hr = (res.get("_holders", ("", "0|0"))[1].split("|") + ["0"])[:2]
        PENDING[m] = dict(t=time.time(), sym=sym, price=float(pair["priceUsd"]), score=sc, creator=cr, res=res, rate=float(hr or 0), holders=int(hn or 0),
                          owners=[], dex=cd["dex"],
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
        reg = extras.regime(); tm, _ = extras.tod_mult()
        conf = extras.confidence(p["score"], p.get("res", {}), extras.smart_hits(p.get("owners"), m), p.get("rate", 0), reg)
        ex = dict(narrative=extras.narrative(p["sym"]), stage=extras.launch_stage(pair).get("stage"), holders=p.get("holders"), holder_rate=p.get("rate"))
        ok = executor.buy(m, p["sym"], pair, p["score"], mult=reg.get("size_mult", 1) * tm, stop_pct=extras.vol_stop(pair), conf=conf, extra=ex)
        if p["score"] >= CFG["AB_SCORE"]: executor.buy(m, p["sym"], pair, p["score"], ver=CFG["VERSION"] + "b", conf=conf, extra=ex)  # 38: B book = stricter score, fixed -8%
        if ok: ENTRYLIQ[m] = (pair.get("liquidity") or {}).get("usd") or 0
        if ok and p["creator"]: DEVBAL[m] = (p["creator"], detect.dev_balance(p["creator"], m), time.time())
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
        el = ENTRYLIQ.get(p["mint"]); liq = (pr.get("liquidity") or {}).get("usd") or 0
        if el and liq < el * 0.5:  # 26: LP pulled -> instant exit
            executor.sell(p, price, "lp_pull"); extras.postmortem(p, price, "lp_pull"); detect.add_rugger(DEVBAL.get(p["mint"], ("",))[0], "LP pulled on " + p["mint"][:8]); continue
        u = risk.update(p, price)
        if u["time_stop"]: executor.sell(p, price, "time_stop"); extras.postmortem(p, price, "time_stop"); continue
        if u["partial"]: executor.partial(p, price); p = dict(p, qty=p["qty"] / 2, cost=p["cost"] / 2, tp_done=1)
        if u["exit"]:
            rs = "trailing_stop" if u["trailing"] else "stop_loss"; executor.sell(p, price, rs); extras.postmortem(p, price, rs)
            if rs == "trailing_stop" and price > p["entry"] and p.get("version") == CFG["VERSION"]: REENTRY[p["mint"]] = (price, time.time(), p["symbol"])
            continue
        c = conn(); c.execute("UPDATE positions SET peak=?,stop=?,trailing=? WHERE id=?", (u["peak"], u["stop"], u["trailing"], p["id"])); c.commit(); c.close()
        if u["trailing"] and not p["trailing"]: log("trail_on", p["mint"], p["symbol"], price=price, stop=u["stop"])
def reentry():  # 34: re-enter winners on a 12-25% pullback within 60 min (goes through the normal entry wait/recheck)
    for m, (px, t, sym) in list(REENTRY.items()):
        if time.time() - t > 3600: REENTRY.pop(m); continue
    if not REENTRY: return
    mk = dex_market(list(REENTRY))
    for m, (px, t, sym) in list(REENTRY.items()):
        q = float((mk.get(m) or {}).get("priceUsd") or 0)
        if q and px * 0.75 < q <= px * 0.88 and m not in PENDING:
            REENTRY.pop(m); PENDING[m] = dict(t=time.time(), sym=sym, price=q, score=0.6, creator="", res={}, rate=0, holders=0, owners=[], dex="", devbal=None)
            log("entry_wait", m, sym, price=q, delay=CFG["ENTRY_DELAY"], reentry=True)
def state():
    from common import HEALTH
    now = time.time()
    return dict(ts=now, pending=len(PENDING), ws=feed.STATS,
        watch=[dict(sym=p["sym"][:14], mint=m, wait_left=max(0, round(CFG["ENTRY_DELAY"] - (now - p["t"]))), price=p["price"], score=p["score"]) for m, p in list(PENDING.items())[:10]],
        reentry=[dict(sym=v[2], exit=v[0], mins_left=round(60 - (now - v[1]) / 60)) for v in REENTRY.values()],
        kills_live=list(KILLS), risk=executor.RISK, regime=extras.STATE.get("regime"),
        latency=dict(scan_s_avg=round(sum(LAT) / len(LAT), 1) if LAT else None, scan_s_last=LAT[-1] if LAT else None, pos_check_s=CFG["POS_SEC"],
                     ws_last_event_s=round(now - feed.STATS["last"]) if feed.STATS.get("last") else None),
        sources={h: dict(v, ok_rate=round(v["ok"] / max(1, v["ok"] + v["err"]), 2)) for h, v in HEALTH.items()})
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
                if k % 30 == 0: reentry()
                if k % 600 == 1: extras.regime()
                if k % 5 == 0: json.dump(state(), open(HB + ".tmp", "w"), default=str); os.replace(HB + ".tmp", HB)
            except Exception: log("error", where="positions", trace=traceback.format_exc()[-800:])
            time.sleep(CFG["POS_SEC"])
    threading.Thread(target=pos_loop, daemon=True).start()
    while cycles is None or n < cycles:
        t0 = time.time()
        try: scan(); n += 1
        except Exception: log("error", where="scan", trace=traceback.format_exc()[-800:])
        time.sleep(max(1, CFG["SCAN_SEC"] - (time.time() - t0)))
if __name__ == "__main__": main(int(sys.argv[1]) if len(sys.argv) > 1 else None)
