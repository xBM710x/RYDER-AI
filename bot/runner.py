"""Night Desk runner (PAPER ONLY). v3: scan every 30s + live websocket launches, positions every 1s, delayed entry with recheck."""
import time, sys, traceback, threading
from common import CFG, dex_market
from logger import conn, log
import scout, filters, analyst, executor, risk, detect, feed, json, os, extras, collections, brain, more
REENTRY = {}  # 34: mint -> (exit price, ts, sym)
ENTRYLIQ = {}  # 26: mint -> liquidity at entry
LAT = collections.deque(maxlen=50); KILLS = collections.deque(maxlen=12)
PENDING = {}  # mint -> entry candidate waiting ENTRY_DELAY
HB = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'heartbeat.json')
DEVBAL = {}  # open-position mint -> (creator, baseline balance, last check ts)
def scan():
    t0 = time.time(); _scan(); LAT.append(round(time.time() - t0, 1))
POOL = __import__("concurrent.futures", fromlist=["x"]).ThreadPoolExecutor(max_workers=6)
DEC = collections.deque(maxlen=200)  # decision latency per coin (s, first seen -> verdict)
DEEP = collections.deque(maxlen=100)  # deep-check time per coin (s)
INFLIGHT = set()
def _scan():
    cands, total = scout.scout(); cands = [c for c in cands if c["mint"] not in INFLIGHT]
    mkt = dex_market([c["mint"] for c in cands]) if cands else {}
    if total or cands: log("scan", n_raw=total, n_new_or_due=len(cands))
    for cd in cands:
        INFLIGHT.add(cd["mint"]); POOL.submit(_eval_safe, cd, mkt.get(cd["mint"]))
def _eval_safe(cd, pair):
    try: evaluate(cd, pair)
    except Exception: log("error", where="evaluate", trace=traceback.format_exc()[-800:])
    finally: INFLIGHT.discard(cd["mint"])
def kill(m, sym, reason, detail, final=True, pair=None, **kw):
    if final: KILLS.append(dict(t=time.strftime("%H:%M:%S"), sym=(sym or "")[:14], reason=reason))
    log("kill", m, sym, reason=reason, detail=detail, final=final, px=float((pair or {}).get("priceUsd") or 0) or None, **kw)
def evaluate(cd, pair):
    t0 = time.time(); m = cd["mint"]; sym = (pair or {}).get("baseToken", {}).get("symbol") or cd["name"]
    if pair and cd["dex"].startswith("unknown"): cd["dex"] = scout.tag(pair.get("dexId", ""), m)
    res = filters.check(m, pair); ok, why = filters.verdict(res)
    c = conn(); r = c.execute("SELECT checks, first_ts FROM seen WHERE mint=?", (m,)).fetchone()
    checks = (r["checks"] if r else 0) + 1; first = (r["first_ts"] if r else t0) or t0
    final = not ((why.startswith("volume_1h") or why.startswith("liquidity")) and checks < CFG["MAX_CHECKS"]) or ok
    c.execute("UPDATE seen SET checks=?, last_ts=?, done=? WHERE mint=?", (checks, time.time(), int(final), m)); c.commit(); c.close()
    if len(res) > 2: DEEP.append(round(time.time() - t0, 2))
    if not ok:
        kill(m, sym, why.split(":")[0], why, final, pair, dex=cd["dex"], source=cd["source"], checks={k: v[0] + "/" + v[2] for k, v in res.items()})
        if checks == 1: DEC.append(round(time.time() - first, 2))
        return
    if CFG["VERSION"] not in ("v1", "v2"):
        st, rs, d = brain.structure(pair)
        if st == "fail": DEC.append(round(time.time() - first, 2)); return kill(m, sym, rs, d, True, pair, dex=cd["dex"])
        cr = res.get("_creator", ("", ""))[1]
        try: dst, drs, dd, dscore = brain.dev_check(cr)
        except Exception as e: dst, drs, dd, dscore = "pass", "", f"dev check unavailable ({str(e)[:40]})", 0.5
        if dst == "fail": DEC.append(round(time.time() - first, 2)); detect.add_rugger(cr, dd) if drs == "linked_launch" else None; return kill(m, sym, drs, dd, True, pair, dex=cd["dex"])
        try:
            imp = brain.impact(m)
            if imp > 3: DEC.append(round(time.time() - first, 2)); return kill(m, sym, "price_impact", f"$30 buy moves price {imp:.1f}%", True, pair)
        except Exception: imp = None
    sc, parts = analyst.score(pair, res)
    f = brain.features(pair, parts, sc); narr = extras.narrative(sym); bk = brain.bucket(f, cd["dex"], narr)
    adj, why_adj = brain.bucket_adj(bk, brain.memory()); sc2 = round(sc + adj, 3)
    dp = brain.dump_pattern(f)
    log("score", m, sym, score=sc2, base_score=sc, adj=adj, parts=parts, dex=cd["dex"], filters={k: v for k, v in res.items()})
    DEC.append(round(time.time() - first, 2))
    if dp: return kill(m, sym, "dump_pattern", dp, True, pair)
    if sc2 < CFG["MIN_SCORE"]: return kill(m, sym, "score<0.6", f"score {sc2}", True, pair, dex=cd["dex"])
    cr = res.get("_creator", ("", ""))[1]
    hn, hr = (res.get("_holders", ("", "0|0"))[1].split("|") + ["0"])[:2]
    PENDING[m] = dict(t=time.time(), sym=sym, price=float(pair["priceUsd"]), score=sc2, creator=cr, res=res, rate=float(hr or 0), holders=int(hn or 0),
                      owners=[], dex=cd["dex"], feats=f, bucket=bk, why_adj=why_adj, struct=locals().get("d", ""), dev=locals().get("dd", ""), impact=locals().get("imp"),
                      devbal=detect.dev_balance(cr, m) if cr else None, tx5=(pair.get("txns") or {}).get("m5"), liq0=(pair.get("liquidity") or {}).get("usd"))
    log("entry_wait", m, sym, price=float(pair["priceUsd"]), delay=CFG["ENTRY_DELAY"], score=sc2)
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
        pz = brain.paused()
        if pz: log("skip", m, p["sym"], reason=pz); continue
        g, pmult = more.guards(extras.narrative(p["sym"]))
        if g: log("skip", m, p["sym"], reason=g); continue
        fl = more.flow(p, pair)
        if fl["imbalance"] == "sell": log("kill", m, p["sym"], reason="orderflow", detail=f"sells outran buys during wait ({fl})", final=True); continue
        pok, pd = more.price_ok(m, float(pair["priceUsd"]))
        if not pok: log("kill", m, p["sym"], reason="price_mismatch", detail=pd, final=True); continue
        reg = extras.regime(); tm, _ = extras.tod_mult()
        conf = extras.confidence(p["score"], p.get("res", {}), extras.smart_hits(p.get("owners"), m), p.get("rate", 0), reg)
        conf = round(min(1, conf + (0.05 if more.good_dev(p["creator"]) else 0) + (0.03 if fl["liq_add"] else 0)), 3)  # 102 / 110
        ex = dict(narrative=extras.narrative(p["sym"]), stage=extras.launch_stage(pair).get("stage"), holders=p.get("holders"), holder_rate=p.get("rate"))
        f = p.get("feats") or brain.features(pair, {}, p["score"]); wp, wsrc = brain.win_prob(f); sm = brain.size_mult(conf, wp)
        mult = round(reg.get("size_mult", 1) * tm * sm * pmult, 3)
        ex.update(flow=fl, price_check=pd, feats=f, bucket=p.get("bucket"), win_prob=wp, win_src=wsrc, size_x=mult, impact=p.get("impact"),
                  why=brain.explain(p["sym"], p["score"], wp, wsrc, conf, mult, p.get("why_adj") or [], p.get("struct") or "n/a", p.get("dev") or "n/a"))
        ok = executor.buy(m, p["sym"], pair, p["score"], mult=mult, stop_pct=extras.vol_stop(pair), conf=conf, extra=ex)
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
                more.remember_rug(p["mint"], pr); executor.sell(p, price, "dev_sell"); detect.add_rugger(dv[0], "sold while we held " + p["mint"][:8]); DEVBAL.pop(p["mint"], None); continue
        el = ENTRYLIQ.get(p["mint"]); liq = (pr.get("liquidity") or {}).get("usd") or 0
        if el and liq < el * 0.5:  # 26: LP pulled -> instant exit
            more.remember_rug(p["mint"], pr); executor.sell(p, price, "lp_pull"); extras.postmortem(p, price, "lp_pull"); detect.add_rugger(DEVBAL.get(p["mint"], ("",))[0], "LP pulled on " + p["mint"][:8]); continue
        v3 = p.get("version") not in ("v1", "v2")
        tx5 = (pr.get("txns") or {}).get("m5") or {}; spike = v3 and (tx5.get("sells") or 0) > 2 * max(1, tx5.get("buys") or 0) and (tx5.get("sells") or 0) >= 10
        if v3 and time.time() - p["opened"] > 600:  # 83 volume decay exit
            v5, v1h = (pr.get("volume") or {}).get("m5") or 0, (pr.get("volume") or {}).get("h1") or 0
            if v1h and v5 < 0.2 * v1h / 12 and price < p["entry"] * 1.05:
                executor.sell(p, price, "volume_decay"); extras.postmortem(p, price, "volume_decay"); continue
        if v3 and time.time() - HOLDCHK.get(p["mint"], (0, None))[0] > 300:  # 71 holder concentration trend
            t10 = top10(p["mint"]); prev = HOLDCHK.get(p["mint"], (0, None))[1]; HOLDCHK[p["mint"]] = (time.time(), t10 if prev is None else prev)
            if t10 is not None and prev is not None and t10 > prev + 10:
                executor.sell(p, price, "holder_concentration"); extras.postmortem(p, price, "holder_concentration"); continue
        u = risk.update(p, price, trail_pct=extras.vol_stop(pr) + 0.02 if v3 else None, sell_spike=spike)
        if u["time_stop"]: executor.sell(p, price, "time_stop"); extras.postmortem(p, price, "time_stop"); continue
        if u["partial"]: executor.partial(p, price, u["partial"]); p = dict(p, qty=p["qty"] / 2, cost=p["cost"] / 2, tp_done=u["partial"])
        if u["exit"]:
            rs = "trailing_stop" if u["trailing"] else ("breakeven_stop" if u["stop"] >= p["entry"] * 0.999 else "stop_loss"); executor.sell(p, price, rs); extras.postmortem(p, price, rs)
            if rs == "stop_loss" and p.get("version") == CFG["VERSION"]: brain.on_stop()  # 81 cooldown
            if rs == "trailing_stop" and price > p["entry"] and p.get("version") == CFG["VERSION"]: REENTRY[p["mint"]] = (price, time.time(), p["symbol"])
            continue
        c = conn(); c.execute("UPDATE positions SET peak=?,stop=?,trailing=? WHERE id=?", (u["peak"], u["stop"], u["trailing"], p["id"])); c.commit(); c.close()
        if u["trailing"] and not p["trailing"]: log("trail_on", p["mint"], p["symbol"], price=price, stop=u["stop"])
HOLDCHK = {}
def top10(mint):
    try:
        rc = __import__("common").http_json(f"https://api.rugcheck.xyz/v1/tokens/{mint}/report", timeout=20)
        kn = rc.get("knownAccounts") or {}
        return round(sum(h.get("pct", 0) for h in [h for h in (rc.get("topHolders") or []) if (kn.get(h.get("owner")) or {}).get("type") not in ("AMM", "LOCKER")][:10]), 1)
    except Exception: return None
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
MODELN = lambda: brain.MODEL["n"]
def jobs(k):
    if k % 900 == 0: brain.audit(); brain.check_promotion(); brain.drift(); brain.train()
    lt = time.localtime()
    if lt.tm_hour == 3 and lt.tm_min == 0 and k % 60 == 0: brain.nightly()
    if lt.tm_wday == 6 and lt.tm_hour == 8 and lt.tm_min == 0 and k % 60 == 0: brain.weekly_report()
def state():
    from common import HEALTH
    now = time.time()
    return dict(ts=now, pending=len(PENDING), ws=feed.STATS,
        watch=[dict(sym=p["sym"][:14], mint=m, wait_left=max(0, round(CFG["ENTRY_DELAY"] - (now - p["t"]))), price=p["price"], score=p["score"]) for m, p in list(PENDING.items())[:10]],
        reentry=[dict(sym=v[2], exit=v[0], mins_left=round(60 - (now - v[1]) / 60)) for v in REENTRY.values()],
        kills_live=list(KILLS), risk=executor.RISK, regime=extras.STATE.get("regime"),
        decision_s=dict(avg=round(sum(DEC) / len(DEC), 2) if DEC else None, p90=sorted(DEC)[int(len(DEC) * 0.9)] if DEC else None, n=len(DEC)),
        deep_check_s=dict(avg=round(sum(DEEP) / len(DEEP), 1) if DEEP else None, max=max(DEEP) if DEEP else None, n=len(DEEP)), inflight=len(INFLIGHT),
        paused=brain.paused(), rug_timing=more.rug_timing(), migrations=feed.STATS.get("migrations", 0), model=dict(trained=MODELN(), src="ml" if brain.MODEL["m"] is not None else "rules"),
        latency=dict(scan_s_avg=round(sum(LAT) / len(LAT), 1) if LAT else None, scan_s_last=LAT[-1] if LAT else None, pos_check_s=CFG["POS_SEC"],
                     ws_last_event_s=round(now - feed.STATS["last"]) if feed.STATS.get("last") else None),
        sources={h: dict(v, ok_rate=round(v["ok"] / max(1, v["ok"] + v["err"]), 2)) for h, v in HEALTH.items()})
def main(cycles=None):
    log("start", mode="PAPER", cfg=CFG); n = 0
    try: ST = more.selftest()  # 120
    except Exception: ST = {}
    if not ST.get("dexscreener", {}).get("ok", True): log("skip", reason="selftest: DexScreener down at startup; brain.paused() will hold buys until it recovers")
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
                jobs(k)
                if k % 600 == 1: extras.regime()
                if k % 5 == 0: json.dump(state(), open(HB + ".tmp", "w"), default=str); os.replace(HB + ".tmp", HB)
            except Exception: log("error", where="positions", trace=traceback.format_exc()[-800:])
            time.sleep(CFG["POS_SEC"])
    threading.Thread(target=pos_loop, daemon=True).start()
    while cycles is None or n < cycles:
        t0 = time.time()
        try: scan(); n += 1
        except Exception: log("error", where="scan", trace=traceback.format_exc()[-800:])
        while time.time() - t0 < CFG["SCAN_SEC"] and not feed.NEW: time.sleep(1)  # wake immediately on live launches
        time.sleep(0.5)
if __name__ == "__main__": main(int(sys.argv[1]) if len(sys.argv) > 1 else None)
