"""Night Desk runner (PAPER ONLY). v3: scan every 30s + live websocket launches, positions every 1s, delayed entry with recheck."""
import time, sys, traceback, threading
from common import CFG, dex_market
from logger import conn, log
import brain12, brain11, brain10, brain9, runner_start, brain8, brain7, brain6, brain5, brain4, brain3, brain2, scout, filters, analyst, executor, risk, detect, feed, json, os, extras, collections, brain, more, alerts, fomo
REENTRY = {}  # 34: mint -> (exit price, ts, sym)
ENTRYLIQ = {}  # 26: mint -> liquidity at entry
brain10.ENTRYLIQ = ENTRYLIQ  # 480 shared entry liquidity
LAT = collections.deque(maxlen=50); KILLS = collections.deque(maxlen=12)
PENDING = {}  # mint -> entry candidate waiting ENTRY_DELAY
HB = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'heartbeat.json')
DEVBAL = {}  # open-position mint -> (creator, baseline balance, last check ts)
def scan():
    t0 = time.time(); _scan(); LAT.append(round(time.time() - t0, 1))
POOL = __import__("concurrent.futures", fromlist=["x"]).ThreadPoolExecutor(max_workers=8)  # 290: 6 -> 8 parallel evaluations
DEC = collections.deque(maxlen=200)  # decision latency per coin (s, first seen -> verdict)
DEEP = collections.deque(maxlen=100)  # deep-check time per coin (s)
INFLIGHT = set()
def _scan():
    cands, total = scout.scout(); cands = [c for c in cands if c["mint"] not in INFLIGHT and not brain2.rejected(c["mint"])]  # 138
    mkt = dex_market([c["mint"] for c in cands]) if cands else {}
    if total or cands: log("scan", n_raw=total, n_new_or_due=len(cands))
    for cd in cands:
        INFLIGHT.add(cd["mint"]); POOL.submit(_eval_safe, cd, mkt.get(cd["mint"]))
def _eval_safe(cd, pair):
    try: evaluate(cd, pair)
    except Exception: log("error", where="evaluate", trace=traceback.format_exc()[-800:])
    finally: INFLIGHT.discard(cd["mint"])
def kill(m, sym, reason, detail, final=True, pair=None, **kw):
    brain8.count("gate:" + str(reason))  # 369 every evaluate gate
    if final: brain2.reject(m, reason); brain2.rule_hit(reason)
    if final: KILLS.append(dict(t=time.strftime("%H:%M:%S"), sym=(sym or "")[:14], reason=reason))
    if pair and reason in ("volume_1h", "liquidity"): brain10.note_kill(m, sym, reason, pair)  # 441
    elif final: brain10.unwatch(m)  # 442 any other final kill (safety) removes it from the watch
    log("kill", m, sym, reason=reason, detail=detail, final=final, px=float((pair or {}).get("priceUsd") or 0) or None, **kw)
def evaluate(cd, pair, relax=False):
    t0 = time.time(); m = cd["mint"]; sym = (pair or {}).get("baseToken", {}).get("symbol") or cd["name"]
    if pair and cd["dex"].startswith("unknown"): cd["dex"] = scout.tag(pair.get("dexId", ""), m)
    if not pair and brain7.dead_skip(m): return  # 335
    fr = None if relax else (brain7.fast_reject(m, pair, sym) or brain7.relaunch(sym))  # 293/295/296/313 sub-1s fast path
    if fr: DEC.append(round(time.time() - t0, 3)); return kill(m, sym, fr[0], fr[1], True, pair, dex=cd["dex"], fast=True)
    if pair and CFG["VERSION"] not in ("v1", "v2"):
        pg = brain7.pregrad_guard(pair) or brain7.theme_cooldown(sym)  # 268 / 328
        if pg: return kill(m, sym, "pregrad" if "graduate" in pg else "theme_cooldown", pg, False, pair, dex=cd["dex"])
    res = filters.check(m, pair, relax); ok, why = filters.verdict(res)
    brain8.count("seen"); brain8.count("fomo_eval") if isinstance(relax, float) else None
    if res.get("volume_1h", ("",))[0] == "pass": brain8.count("vol_pass")
    brain8.count("kill:" + why.split(":")[0]) if not ok else brain8.count("safety_pass")  # 369
    if relax: checks, first, final = 2, t0, True
    else:
        c = conn(); r = c.execute("SELECT checks, first_ts FROM seen WHERE mint=?", (m,)).fetchone()
        checks = (r["checks"] if r else 0) + 1; first = (r["first_ts"] if r else t0) or t0
        final = not ((why.startswith("volume_1h") or why.startswith("liquidity")) and checks < brain8.max_checks(cd, pair)) or ok  # 365
        c.execute("UPDATE seen SET checks=?, last_ts=?, done=? WHERE mint=?", (checks, time.time(), int(final), m)); c.commit(); c.close()
    if len(res) > 2: DEEP.append(round(time.time() - t0, 2))
    if not ok:
        kill(m, sym, why.split(":")[0], why, final, pair, dex=cd["dex"], source=cd["source"], checks={k: v[0] + "/" + v[2] for k, v in res.items()})
        if checks == 1: DEC.append(round(time.time() - first, 2))
        if final and not pair: brain7.mark_dead(m)  # 335
        vol = ((pair or {}).get("volume") or {}).get("h1") or 0
        if not relax and CFG["VERSION"] not in ("v1", "v2") and why.startswith("volume_1h") and vol >= 0.5 * brain4.vol_bar(pair) and m not in PENDING \
                and sum(1 for q in PENDING.values() if q.get("exp")) < 5:
            return evaluate(cd, pair, relax=True)  # v3x: soft volume reject -> full safety checks at a relaxed volume bar, experimental desk only
        if not relax and CFG["VERSION"] not in ("v1", "v2") and (why.startswith("volume_1h:fail") or why.startswith("liquidity:fail")) and m not in PENDING \
                and sum(1 for q in PENDING.values() if q.get("fomo")) < 2 and fomo.factor():
            return evaluate(cd, pair, relax=fomo.factor())  # FOMO (v3x only): idle desk -> soft bars relaxed, ALL hard safety checks still run
        return
    if CFG["VERSION"] not in ("v1", "v2"):
        st, rs, d = brain.structure(pair)
        if st == "fail": DEC.append(round(time.time() - first, 2)); return kill(m, sym, rs, d, True, pair, dex=cd["dex"])
        cr = res.get("_creator", ("", ""))[1]
        fimp = brain3.POOL.submit(brain.impact, m); flk = brain3.POOL.submit(brain3.links_ok, pair)  # 180 parallel
        try: dst, drs, dd, dscore = brain.dev_check(cr)
        except Exception as e: dst, drs, dd, dscore = "pass", "", f"dev check unavailable ({str(e)[:40]})", 0.5
        if dst == "fail": DEC.append(round(time.time() - first, 2)); detect.add_rugger(cr, dd) if drs == "linked_launch" else None; return kill(m, sym, drs, dd, True, pair, dex=cd["dex"])
        try:
            imp = fimp.result(timeout=20)
            if imp > 3: DEC.append(round(time.time() - first, 2)); return kill(m, sym, "price_impact", f"$30 buy moves price {imp:.1f}%", True, pair)
        except Exception: imp = None
        lok, ld = flk.result(timeout=15)
        if not lok: DEC.append(round(time.time() - first, 2)); return kill(m, sym, "dead_links", ld, True, pair)  # 165
        for chk in (brain2.hype(pair), brain2.wash(pair), None if relax else (("chasing", brain6.chasing(pair)) if brain6.chasing(pair) else None)):  # 135 / 136 / 249
            if chk and not brain2.pruned(chk[0]): DEC.append(round(time.time() - first, 2)); return kill(m, sym, chk[0], chk[1], True, pair, dex=cd["dex"])
    if CFG["VERSION"] not in ("v1", "v2"):
        c4 = conn(); ow = [r[0] for r in c4.execute("SELECT wallet FROM holders WHERE mint=?", (m,))]; c4.close()
        fh = brain6.fresh_holders(ow)  # 244
        if fh: DEC.append(round(time.time() - first, 2)); return kill(m, sym, "fresh_holders", fh, True, pair)
    pe9, pa9 = brain9.pre_entry(pair, extras.STATE.get("regime")) if CFG["VERSION"] not in ("v1", "v2") and not relax else (None, 0)  # 416/418-421
    if pe9: DEC.append(round(time.time() - first, 2)); return kill(m, sym, pe9[0], pe9[1], True, pair, dex=cd["dex"])
    sc, parts = analyst.score(pair, res)
    pr9 = res.get("pressure", ("", ""))[1]
    f = brain.features(pair, parts, sc); narr = extras.narrative(sym); bk = brain.bucket(f, cd["dex"], narr)
    adj, why_adj = brain.bucket_adj(bk, brain.memory()); adj = round(adj + scout.boost_bump(m), 3)
    b7 = {}
    if CFG["VERSION"] not in ("v1", "v2"):  # 264-269 / 279 / 301-312 / 341-346 brain7 score layer (bounded -0.15..+0.12)
        lg, lgr = brain7.liq_growth(m, pair); cp, t10 = brain7.conc_penalty(res); hv = brain7.holder_velocity((res.get("_holders", ("", "0|0"))[1].split("|") + ["0", "0"])[1])
        sl_, sld = brain7.serial_launcher(res.get("_creator", ("", ""))[1])
        if sl_ is None: DEC.append(round(time.time() - first, 2)); return kill(m, sym, "serial_launcher", sld, True, pair, dex=cd["dex"])
        wb, wpen = brain7.whale_block(m)
        if wb: return kill(m, sym, wb[0], wb[1], True, pair, dex=cd["dex"])
        cpg, cpp = brain7.curve_progress(pair); tda, _ = brain7.tod_adj()
        tg = brain7.tags_for(dict(liq_g=lg, hv=hv, t10=t10, boosted=scout.boost_bump(m) > 0, pair=pair))
        parts7 = dict(liq_growth=lg, conc=cp, holder_vel=hv, serial=sl_, tod=tda, accel=brain7.momentum_accel(pair), size_growth=brain7.buy_size_growth(pair), liq_mcap=brain7.liq_mcap(pair),
                      age=brain7.learned_bucket_adj("age", brain7.age_bucket(pair)), src=brain7.learned_bucket_adj("src", cd.get("source")), dexl=brain7.learned_bucket_adj("dex", cd["dex"]),
                      breadth=brain7.breadth(pair), curve=cpg, socials=brain7.socials_q(pair), paid_hype=brain7.paid_hype(pair), heat=brain7.theme_heat(sym), lp=brain7.lp_unlock_pen(res),
                      holders=wpen, rugsim=brain7.rug_similar(f), learned=brain7.learned_adj(tg), tight=-brain7.S["tight"].get("entry", 0))
        a7 = round(max(-0.15, min(0.12, sum(parts7.values()))), 3); adj = round(adj + a7, 3); b7 = dict(parts=parts7, adj=a7, tags=tg, t10=t10, liq_g=lgr, curve=brain7.curve_progress(pair)[1])
    if CFG["VERSION"] not in ("v1", "v2") and pair:
        tx9 = (pair.get("txns") or {}); adj = round(adj + pa9 + brain9.pressure_verdict((tx9.get("m5") or {}).get("buys") or 0, (tx9.get("m5") or {}).get("sells") or 0, (tx9.get("h1") or {}).get("buys") or 0, (tx9.get("h1") or {}).get("sells") or 0)[1], 3)  # 403/416
        adj = round(adj + round(brain10.accel_adj(m, pair) * brain10.accel_conf(), 3) + brain10.feed_adj(m, pair), 3)  # 453/474/463-468
        adj = round(adj + brain8.staying_power(checks, pair) - (0.05 if res.get("socials", ("", "", ""))[2] == "soft-366" else 0), 3)  # 379 / 366
    sc2 = round(sc + adj, 3); brain8.count("scored")
    dp = brain.dump_pattern(f)
    log("score", m, sym, score=sc2, base_score=sc, adj=adj, parts=parts, b7=b7, dex=cd["dex"], filters={k: v for k, v in res.items()})
    DEC.append(round(time.time() - first, 2))
    if dp: return kill(m, sym, "dump_pattern", dp, True, pair)
    if not relax and CFG["VERSION"] not in ("v1", "v2") and sc2 < CFG["MIN_SCORE"] and fomo.factor() and sc2 >= fomo.score_bar(fomo.factor(), CFG["MIN_SCORE"]) \
            and sum(1 for q in PENDING.values() if q.get("fomo")) < 2: relax = fomo.factor()  # FOMO: near-bar score -> v3x only
    bar8 = ((fomo.score_bar(relax, CFG["MIN_SCORE"]) if isinstance(relax, float) else 0.5) if relax else brain8.min_score(CFG["MIN_SCORE"]))  # 373
    if sc2 < bar8: brain8.second_chance(m, sc2, bar8, pair)  # 372
    if sc2 < bar8: brain8.count("kill:score"); return kill(m, sym, "score<0.6", f"score {sc2}", True, pair, dex=cd["dex"])
    cr = res.get("_creator", ("", ""))[1]
    hn, hr = (res.get("_holders", ("", "0|0"))[1].split("|") + ["0"])[:2]
    ok_q, drop = (True, None) if relax else brain4.admit(PENDING, sc2)  # 190/196 (v3x has its own cap of 5 waiting)
    if not ok_q: return kill(m, sym, "queue_full", f"score {sc2} below every waiting coin", False, pair)
    if drop: dp_ = PENDING.pop(drop, None); dp_ and log("kill", drop, dp_["sym"], reason="swapped", detail=f"swapped for better coin {sym} ({sc2})", final=False)
    brain6.want([m])  # 222 stream trades while it waits
    PENDING[m] = dict(h0f=brain3.POOL.submit(brain6.gecko_holders, m), exp=bool(relax), fomo=isinstance(relax, float), fomo_f=relax if isinstance(relax, float) else None, t=time.time(), sym=sym, price=float(pair["priceUsd"]), score=sc2, creator=cr, res=res, rate=float(hr or 0), holders=int(hn or 0),
                      owners=[], dex=cd["dex"], cd=dict(source=cd.get("source"), t=cd.get("t")), feats=f, bucket=bk, why_adj=why_adj, struct=locals().get("d", ""), dev=locals().get("dd", ""), impact=locals().get("imp"),
                      b7=b7, t0=time.time(), devbal=detect.dev_balance(cr, m) if cr else None, tx5=(pair.get("txns") or {}).get("m5"), liq0=(pair.get("liquidity") or {}).get("usd"))
    brain8.count("entry_wait"); log("entry_wait", m, sym, price=float(pair["priceUsd"]), delay=CFG["ENTRY_DELAY"], score=sc2)
def pending():
    brain6.WANT.clear(); brain6.WANT.update(set(PENDING) | OPENM)  # 222 stream only what we wait on or hold
    early = [m for m, p in PENDING.items() if time.time() - p["t"] < CFG["ENTRY_DELAY"]]
    if early:  # 124: 5s ticks on waiting coins; dumps abort early, strong ones fast-track at 45s
        mk = dex_market(early)
        for m in early:
            pr = mk.get(m)
            if not pr: continue
            brain2.tick(m, pr); q = float(pr.get("priceUsd") or 0); p = PENDING.get(m)
            if p and q and q / p["price"] - 1 < CFG["MAX_DUMP"]: PENDING.pop(m, None); log("kill", m, p["sym"], reason="recheck", detail=f"dumped {(q/p['price']-1)*100:+.1f}% mid-wait (early abort)", final=True)
            elif p and p["score"] >= 0.75 and time.time() - p["t"] >= 45 and brain2.pressure(pr) > 0.6: p["t"] -= CFG["ENTRY_DELAY"]
            elif p and p["score"] >= 0.65 and time.time() - p["t"] >= 60 and brain7.holds_level(m)[0] != "spike_fade": p["t"] -= CFG["ENTRY_DELAY"]  # 368
            elif p and CFG["VERSION"] not in ("v1", "v2") and brain7.confirm_buyers(m, time.time() - p["t"]) == "fast" and brain7.holds_level(m)[0] != "spike_fade" and brain7.dip_entry(m, pr, 0)[0] == "ok":
                p["t"] -= CFG["ENTRY_DELAY"]; p["fast"] = True  # 261 buyers confirmed in 20-60s -> enter now
    due = [m for m, p in PENDING.items() if time.time() - p["t"] >= CFG["ENTRY_DELAY"]]
    if not due: return
    mkt = dex_market(due)
    for m in brain9.tie_break({x: PENDING[x] for x in due}):  # 190 / 437 best first
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
        if CFG["VERSION"] not in ("v1", "v2"):  # 261-263 / 267 / 314-317 entry-wait checks
            wc7 = brain7.wait_checks(m, p, pair) or (("early_sellers", brain7.early_sellers(pair)) if brain7.early_sellers(pair) else None)
            hl7, hld7 = brain7.holds_level(m)
            if not wc7 and hl7 == "spike_fade": wc7 = ("spike_fade", hld7)
            if not wc7 and brain7.confirm_buyers(m, time.time() - p["t"]) == "weak": wc7 = ("no_buyers", "sells outnumbered buys while waiting")
            if wc7: log("kill", m, p["sym"], reason=wc7[0], detail=wc7[1], final=True); brain2.reject(m, wc7[0]); continue
            de, dd7 = brain7.dip_entry(m, pair, time.time() - p.get("t0", p["t"]))
            if de == "wait": p["t"] = time.time() - CFG["ENTRY_DELAY"] + 15; PENDING[m] = p; continue  # 267 re-check in 15s
            if de == "skip": log("kill", m, p["sym"], reason="no_dip", detail=dd7, final=True); continue
            p["dip"] = bool(dd7); p["hold"] = hl7
        sw = brain6.single_wallet(m) or brain6.churn_wallets(m)  # 227 / 252
        if sw: log("kill", m, p["sym"], reason="wallet_pump", detail=sw, final=True); brain2.reject(m, "wallet_pump"); continue
        pz = brain.paused() or brain7.market_pause(extras.STATE.get("regime")) if p.get("exp") else brain.paused() or brain7.market_pause(extras.STATE.get("regime")) or brain6.day_goal_hit() or brain2.two_loss_cooldown()  # 297  # 234 or brain2.market_dump(extras.STATE.get("regime"))  # 132 / 155
        if pz: log("skip", m, p["sym"], reason=pz); continue
        if not p.get("exp"):
            cb9 = brain9.coin_blocked(m); oc9, n9 = brain9.open_cap_ok(extras.STATE.get("regime"), CFG["VERSION"])  # 434/435 / 417
            if cb9 or not oc9: log("skip", m, p["sym"], reason=cb9 or f"max open positions for this market ({n9})"); continue
        g, pmult = (None, 1) if p.get("exp") else more.guards(extras.narrative(p["sym"]))
        if g: log("skip", m, p["sym"], reason=g); continue
        fl = more.flow(p, pair)
        if fl["imbalance"] == "sell": log("kill", m, p["sym"], reason="orderflow", detail=f"sells outran buys during wait ({fl})", final=True); continue
        pok, pd = more.price_ok(m, float(pair["priceUsd"]))
        if pok:
            pok, pd2 = brain3.jup_ok(m, float(pair["priceUsd"])); pd = pd + "; " + pd2  # 172
            mm_ = __import__("re").search(r"jupiter differ ([\d.]+)%", pd2)
            if mm_: brain6.source_trust(1.0, {"jupiter": 1 + float(mm_.group(1)) / 100})  # 256
        hl = brain3.higher_lows(m)
        if hl == "lower": log("kill", m, p["sym"], reason="lower_lows", detail="lower lows during entry wait", final=True); continue  # 169
        if not pok: log("kill", m, p["sym"], reason="price_mismatch", detail=pd, final=True); continue
        reg = extras.regime(); tm, _ = extras.tod_mult()
        conf = extras.confidence(p["score"], p.get("res", {}), extras.smart_hits(p.get("owners"), m), p.get("rate", 0), reg)
        conf = round(min(1, conf + (0.05 if more.good_dev(p["creator"]) else 0) + (0.03 if fl["liq_add"] else 0)), 3)  # 102 / 110
        ex = dict(narrative=extras.narrative(p["sym"]), stage=extras.launch_stage(pair).get("stage"), holders=p.get("holders"), holder_rate=p.get("rate"))
        f = p.get("feats") or brain.features(pair, {}, p["score"]); wp, wsrc = brain.win_prob(f); sm = brain.size_mult(conf, wp)
        rs_ = brain4.rel_strength(pair, reg); rm = reg.get("size_mult", 1)
        if rm < 1 and rs_ > 20: rm = 0.75  # 189 relative strength in a falling market
        mult = round(rm * tm * sm * pmult, 3)
        ex.update(flow=fl, price_check=pd, feats=f, bucket=p.get("bucket"), win_prob=wp, win_src=wsrc, size_x=mult, impact=p.get("impact"),
                  why=brain.explain(p["sym"], p["score"], wp, wsrc, conf, mult, p.get("why_adj") or [], p.get("struct") or "n/a", p.get("dev") or "n/a"))
        council = None
        if CFG["VERSION"] not in ("v1", "v2"):  # 141-152 agent council
            c0 = conn(); opn = c0.execute("SELECT COUNT(*) FROM positions WHERE status='open' AND version=?", (CFG["VERSION"],)).fetchone()[0]
            d0 = time.mktime(time.localtime()[:3] + (0, 0, 0, 0, 0, -1)); dp = c0.execute("SELECT COALESCE(SUM(pnl),0) FROM positions WHERE status='closed' AND version=? AND closed>=?", (CFG["VERSION"], d0)).fetchone()[0]; c0.close()
            ctx = dict(open=opn, day_pnl=dp, regime=reg.get("mood"), creator=p.get("creator"), impact=p.get("impact"), lesson_score=brain2.lesson_score(), holder_rate=p.get("rate", 0), rel_strength=rs_, liq_add=fl.get("liq_add"), steady=brain4.steadiness(m), smart=extras.smart_hits(p.get("owners"), m))
            cdd = p.get("cd") or {}; v = brain2.votes(cdd, pair, p.get("res", {}), p["score"], wp, conf, brain2.HS.get(m), ctx)
            v["filter"] = (round(v["filter"][0] * brain5.rule_weight(), 3), v["filter"][1])  # 212
            try: h0 = p["h0f"].result(timeout=1) if p.get("h0f") else None
            except Exception: h0 = None
            h1_ = brain6.gecko_holders(m) if h0 else None; rising = bool(h0 and h1_ and h1_ > h0 * 1.1 and abs(ch) < 0.05)  # 243
            dr = brain6.dip_reaction(m); sm1 = brain6.smart_first_minute(m); sh = brain6.shape(m); ss_ = brain6.shape_sim(sh)  # 229 / 242 / 237
            mc_ = pair.get("marketCap") or pair.get("fdv") or 0; nar_ = ex.get("narrative") or "other"; hv = dict(brain6.theme_velocity())  # 232 / 245 / 251
            aadj = brain6.theme_memory(nar_) + brain6.mcap_adj(mc_) + (0.05 * (ss_ - 0.5) if ss_ is not None else 0) + 0.03 * min(sm1, 3)
            v["analyst"] = (round(min(1, max(0, v["analyst"][0] + aadj)), 3), v["analyst"][1] + f", theme30d/mcap/shape adj {aadj:+.2f}")
            v["executor"] = (round(min(1, v["executor"][0] + (0.05 if rising else 0) + (0.05 * (dr - 0.5) if dr is not None else 0)), 3), v["executor"][1] + (", holders rising on flat price" if rising else "") + (f", dip reaction {dr}" if dr is not None else ""))
            if hv.get(nar_, 0) > 1.5: v["scout"] = (round(min(1, v["scout"][0] + 0.04), 3), v["scout"][1] + f", theme heating x{hv[nar_]}")
            if brain6.rug_hour(): v["risk"] = (round(max(0, v["risk"][0] - 0.1), 3), v["risk"][1] + ", rug-prone hour")  # 235
            ex.update(shape=sh, holders_rising=rising, dip_reaction=dr, smart_first_min=sm1)
            v, deb = brain5.debate(v)  # 205
            go, cons, smul, rsn = brain2.decide(v)
            if deb: rsn += " · " + deb
            if go and CFG["VERSION"] not in ("v1", "v2"):
                go_b, deb7 = brain7.borderline(v, cons, m)  # 284
                if deb7: rsn += " · " + deb7
                go = go and go_b
            if go and brain2.second_opinion(cons):  # 151 borderline -> fresh look at 5s flow before committing
                sp = brain2.spike(m, 10)
                if sp["sells"] > sp["buys"] + 3: go, rsn = False, f"second opinion: sells {sp['sells']} > buys {sp['buys']} in 10s"
            line = brain2.one_line(p["sym"], v, cons, rsn)
            council = dict(consensus=cons, size=smul, votes={a: list(x) for a, x in v.items()}, reason=line, pattern=brain2.pattern_key(cdd, pair))
            stp = brain3.strength_stop(extras.vol_stop(pair), cons); plan_ = None
            if go:  # 201-209 / 213-217: calibrated confidence, EV gate, Kelly size, plan
                go, kmul, plan_, ev_why = brain5.decide(p["sym"], m, pair, v, cons, f, ex.get("narrative"), stp, p.get("impact"), reg)
                rsn += " · " + ev_why; line = brain2.one_line(p["sym"], v, cons, rsn); council.update(reason=line)
                if go: smul = round(smul * kmul, 3)
            council["plan"] = plan_
            if not go and not p.get("exp") and "veto" not in str(line).lower() and 0.55 <= cons < 0.60 and conf >= 0.6:  # 381 council near-miss -> half-size starter
                go = True; smul = round((smul or 1) * 0.5, 3); rsn += " · near-miss starter (0.5x)"; line = brain2.one_line(p["sym"], v, cons, rsn); council.update(reason=line); brain8.count("nearmiss_starter")
            if p.get("exp") or not go:
                if not p.get("exp"): log("kill", m, p["sym"], reason="council", detail=line, final=True, council=council); brain2.reject(m, "council")
                # 211 v3x experimental desk: soft rejects only (never vetoes / rug look-alikes / hard safety fails), vote >= 0.45, EV > 0, max 5 open, small size
                c1 = conn(); xo = c1.execute("SELECT COUNT(*) FROM positions WHERE status='open' AND version=?", (brain5.EXP,)).fetchone()[0]; c1.close()
                bmul, bo = brain6.v3x_backoff()  # 258
                if bo: log("skip", m, p["sym"], reason=bo, book=brain5.EXP)
                elif "veto" not in str(line).lower() and cons >= (0.40 if p.get("fomo") else 0.45) and xo < 5:
                    arm_ = brain6.arm(); stp = round(stp * (1.25 if arm_ == "B" else 1.0), 3)  # 238 A/B: normal vs 25% wider stop
                    g2, k2, pl2, w2 = brain5.decide(p["sym"], m, pair, v, cons, f, ex.get("narrative"), stp, p.get("impact"), reg, exp=True)
                    if g2 and p.get("fomo"):
                        if executor.buy(m, p["sym"], pair, p["score"], ver=brain5.EXP, mult=fomo.size_mult(pair) * bmul, stop_pct=fomo.STOP_PCT, conf=conf, extra=dict(ex, council=council, plan=pl2, experimental=True, fomo=True, fomo_factor=p.get("fomo_f"))):
                            fomo.mark(m); brain8.count("fomo_buy"); alerts.send_async(f"⚡ FOMO paper buy (v3x practice desk): {p['sym']} · {"quarter" if fomo.size_mult(pair) < fomo.SIZE_MULT else "half"} size · stop -5% · out flat after 10 min")
                    elif g2: executor.buy(m, p["sym"], pair, p["score"], ver=brain5.EXP, mult=0.3 * bmul, stop_pct=stp, conf=conf, extra=dict(ex, council=council, plan=pl2, experimental=True, relaxed_volume=bool(p.get("exp")), ab_arm=arm_))
                    else: log("skip", m, p["sym"], reason="v3x: " + w2, book=brain5.EXP)
                continue
            b7 = p.get("b7") or {}; tg7 = (b7.get("tags") or []) + (["buyers_confirmed"] if p.get("fast") else []) + (["dip_entry"] if p.get("dip") else []) + (["holding_level"] if p.get("hold") == "holding" else [])
            rc7 = brain7.ryder_conf(p["score"], conf, wp, cons, brain7.stale_decay(p))  # 270 / 334
            evok7, evd7 = brain7.ev_floor(rc7); g7 = brain7.slot_budget(rc7) or (None if evok7 else evd7)  # 319 / 333
            usd7 = executor.equity(conn()) * CFG["MAX_PCT_PER_TRADE"] * mult * smul
            pg7, pm7 = brain7.portfolio_guards(p["sym"], CFG["VERSION"], usd7)  # 329-332
            el7, eld7 = brain7.exit_liq_ok(usd7, pair)  # 347
            if g7 or pg7 or not el7: log("kill", m, p["sym"], reason="portfolio" if pg7 else "exit_liquidity" if not el7 else "budget", detail=g7 or pg7 or eld7, final=False); continue
            _, tm7 = brain7.tod_adj()
            smul = round(smul * brain7.size_x(rc7) * brain7.dispersion_mult(v) * pm7 * tm7 * brain7.offhours_mult(), 3)  # 285-287 / 318 / 349 / 279
            ex.update(ryder_conf=rc7, tags7=tg7, why1=brain7.why_buy(p["sym"], rc7, tg7))  # 298
            brain7.journal_ctx(m, p["sym"], pair, tg7, rc7, dict(p, feats=f))  # 320
            if plan_:  # 230 worst-case loss forecast (Risk veto if > 2% of start balance)
                wc = brain6.worst_case(executor.equity(conn()) * CFG["MAX_PCT_PER_TRADE"] * mult * smul * brain6.STARTER, stp, brain4.slip(30, pair)); plan_["worst_case_usd"] = wc
                if wc > 0.02 * CFG["START_BALANCE"]: log("kill", m, p["sym"], reason="worst_case", detail=f"worst-case loss ${wc} > 2% of bankroll", final=True); continue
                plan_["text"] += f" · worst case −${wc}"
            ex["plan"] = plan_
            votes_line = "Votes: " + " · ".join(f"{a} {x[0]:.2f} ({x[1][:38]})" for a, x in v.items())  # 255
            if plan_: ex["why"] = plan_["text"] + "\n" + votes_line + "\n" + ex["why"]
            if brain6.all_agree(v): log("strong_agreement", m, p["sym"], council=cons); alerts.send_async(f"🤝 RYDER strong agreement (paper): all six agents ≥0.70 on {p['sym']} · council {cons:.2f}")  # 233
            mult = round(mult * smul, 3); ex["why"] = line + " | " + str(ex.get("why", ""))[:200]
        ex["council"] = council
        if council: mult = round(mult * brain6.STARTER, 3); ex["starter"] = True  # 254 starter buy; add-on after confirmation
        ok = executor.buy(m, p["sym"], pair, p["score"], mult=mult, stop_pct=brain3.strength_stop(extras.vol_stop(pair), (council or {}).get("consensus")), conf=conf, extra=ex)
        if p["score"] >= CFG["AB_SCORE"]: executor.buy(m, p["sym"], pair, p["score"], ver=CFG["VERSION"] + "b", conf=conf, extra=ex)  # 38: B book = stricter score, fixed -8%
        if ok: ENTRYLIQ[m] = (pair.get("liquidity") or {}).get("usd") or 0; brain8.count("bought")
        if ok and p["creator"]: DEVBAL[m] = (p["creator"], detect.dev_balance(p["creator"], m), time.time())
def positions():
    c = conn(); ps = [dict(r) for r in c.execute("SELECT * FROM positions WHERE status='open'")]; c.close()
    if not ps: return
    mkt = dex_market([p["mint"] for p in ps]); OPENM.clear(); OPENM.update(p["mint"] for p in ps)
    miss = [p["mint"] for p in ps if not (mkt.get(p["mint"]) or {}).get("priceUsd")]
    if miss: mkt.update(brain6.fallback_prices(miss))  # 225 route to Jupiter when DexScreener misses
    for p in ps:
        pr = mkt.get(p["mint"])
        if not pr or not pr.get("priceUsd"): continue
        price = float(pr["priceUsd"]); brain2.tick(p["mint"], pr)
        if p.get("version") not in ("v1", "v2"):
            bs = brain6.big_sell(p["mint"])  # 223 event-driven: big sell just hit the stream
            if bs and (len(bs) >= 2 or price < p["entry"] * 1.03): executor.sell(p, price, "big_sell"); extras.postmortem(p, price, "big_sell"); continue
            rf = RUGF.pop(p["mint"], None)  # 248 per-minute rug re-check result
            if rf: executor.sell(p, price, "rug_recheck"); extras.postmortem(p, price, "rug_recheck"); more.remember_rug(p["mint"], pr); continue
            if time.time() - RUGT.get(p["mint"], 0) > 60:
                RUGT[p["mint"]] = time.time(); brain3.POOL.submit(_rugchk, p["mint"])
            hl_ = brain6.health(p, price, pr, ENTRYLIQ.get(p["mint"]))  # 241 / 253
            if hl_ < 0.2 and price < p["entry"] and time.time() - p["opened"] > 120: executor.sell(p, price, "low_health"); extras.postmortem(p, price, "low_health"); continue
            if p.get("version") == CFG["VERSION"] and p["mint"] not in ADDED and time.time() - p["opened"] < 300 and price >= p["entry"] * 1.04 and brain2.pressure(pr) > 0.6:  # 254 / 383 (+5% -> +4%) add on confirmation
                ADDED.add(p["mint"]); executor.add(p, price, p["cost"] * (1 - brain6.STARTER) / brain6.STARTER, pr); continue
            brain7.mae_track(p, price)  # 324
            x9 = brain9.exit_check(p, price, pr, extras.STATE.get("regime"))  # 404/406/409/410/427/428/436
            if x9 and x9[1] == "partial": executor.partial(p, price, (p.get("tp_done") or 0) + 1); p = dict(p, qty=p["qty"] / 2, cost=p["cost"] / 2, tp_done=(p.get("tp_done") or 0) + 1, trailing=1)
            elif x9 and x9[1] == "sell" and brain9.exit_rule_ok(x9[0]): executor.sell(p, price, x9[0]); extras.postmortem(p, price, x9[0]); continue
            elif x9 and x9[1] == "stop": p = dict(p, stop=x9[2])
            x10 = brain10.exit_check(p, price, pr) if p.get("version") in (CFG["VERSION"], "v3x") else None  # 479-482
            if x10 and brain9.exit_rule_ok(x10): executor.sell(p, price, x10); extras.postmortem(p, price, x10); continue
            if brain9.entry_liq_drain(p, (pr.get("liquidity") or {}).get("usd"), ENTRYLIQ.get(p["mint"])): p = dict(p, stop=p["entry"] * 0.97)  # 407
            bf7 = brain7.buy_fade(p, price) if brain9.exit_rule_ok("buy_fade") else None  # 273 / 412
            if bf7: executor.sell(p, price, "buy_fade"); extras.postmortem(p, price, "buy_fade"); continue
            if time.time() - p["opened"] > brain7.flat_minutes(extras.STATE.get("regime")) * 60 and not p["trailing"] and abs(price / p["entry"] - 1) < 0.04:  # 274/276
                executor.sell(p, price, "flat_time"); extras.postmortem(p, price, "flat_time"); continue
            if brain7.partial15(p, price) and not fomo.is_fomo(p["mint"]):  # 272 first partial at +15%
                executor.partial(p, price, 1); p = dict(p, qty=p["qty"] / 2, cost=p["cost"] / 2, tp_done=1, trailing=1)
            sp = brain2.spike(p["mint"], 5)
            if sp["sells"] >= 8 and sp["sells"] > 2 * sp["buys"] and sp["px"] <= -4:  # 124 5s sell spike -> instant exit
                executor.sell(p, price, "sell_spike_5s"); extras.postmortem(p, price, "sell_spike_5s"); continue
            if brain4.near_stop_exit(p, price, sp): executor.sell(p, price, "early_stop"); extras.postmortem(p, price, "early_stop"); continue  # 185
            eh = brain2.BRAIN.get("exit_hold_min")
            if eh and time.time() - p["opened"] > max(15, 2 * eh) * 60 and price < p["entry"] * 1.05 and not p["trailing"]:  # 154 learned exit timing
                executor.sell(p, price, "learned_time"); extras.postmortem(p, price, "learned_time"); continue
        dv = DEVBAL.get(p["mint"])
        if dv and time.time() - dv[2] > 10:  # 275: dev-wallet watch every 10s (was 30s)  # v3: dev-sell watch on open positions, every 30s
            nb = detect.dev_balance(dv[0], p["mint"]); DEVBAL[p["mint"]] = (dv[0], dv[1], time.time())
            if detect.dev_sold(dv[1], nb):
                more.remember_rug(p["mint"], pr); executor.sell(p, price, "dev_sell"); detect.add_rugger(dv[0], "sold while we held " + p["mint"][:8]); DEVBAL.pop(p["mint"], None); continue
        el = ENTRYLIQ.get(p["mint"]); liq = (pr.get("liquidity") or {}).get("usd") or 0
        if el and liq < el * 0.7:  # 26/128 (tightened 50%->30% pull): LP pulled -> instant exit
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
        if p.get("version") == brain5.EXP and fomo.is_fomo(p["mint"]):  # FOMO exits: quick TP, flat time-stop
            if price >= p["entry"] * (1 + fomo.TP_PCT): executor.sell(p, price, "fomo_tp"); extras.postmortem(p, price, "fomo_tp"); continue
            if time.time() - p["opened"] > fomo.FLAT_MIN * 60 and price < p["entry"] * (1 + fomo.FLAT_BAND): executor.sell(p, price, "fomo_time"); extras.postmortem(p, price, "fomo_time"); continue
        tp0 = ((0.04 if (v3 and brain6.market_turning(extras.STATE.get('regime')) and price > p['entry'] * 1.10) else None) or (brain2.trail_pct(extras.vol_stop(pr) + 0.02, pr, p['peak'] / p['entry'] - 1) + (0.02 if brain4.buyers_arriving(brain2.spike(p['mint'], 5), pr) else 0))) if v3 else None  # 191
        u = risk.update(p, price, trail_pct=brain7.regime_trail(brain7.trail_tighten(tp0, p['peak'] / p['entry'] - 1), extras.STATE.get('regime')) if v3 else None, sell_spike=spike)  # 271 / 276
        if u["time_stop"]: executor.sell(p, price, "time_stop"); extras.postmortem(p, price, "time_stop"); continue
        if u["partial"]: executor.partial(p, price, u["partial"]); p = dict(p, qty=p["qty"] / 2, cost=p["cost"] / 2, tp_done=u["partial"])
        if u["exit"]:
            rs = "trailing_stop" if u["trailing"] else ("breakeven_stop" if u["stop"] >= p["entry"] * 0.999 else "stop_loss"); executor.sell(p, price, rs); extras.postmortem(p, price, rs)
            if rs == "stop_loss" and p.get("version") == CFG["VERSION"]: brain.on_stop()  # 81 cooldown
            if rs == "trailing_stop" and price > p["entry"] and p.get("version") == CFG["VERSION"]: REENTRY[p["mint"]] = (price, time.time(), p["symbol"])
            continue
        c = conn(); c.execute("UPDATE positions SET peak=?,stop=?,trailing=? WHERE id=?", (u["peak"], u["stop"], u["trailing"], p["id"])); c.commit(); c.close()
        if u["trailing"] and not p["trailing"]: log("trail_on", p["mint"], p["symbol"], price=price, stop=u["stop"])
HOLDCHK = {}; RUGF = {}; RUGT = {}; ADDED = set(); OPENM = set()
def _rugchk(m):
    r = brain6.rug_recheck(m)
    if r: RUGF[m] = r
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
        if q and px * 0.75 < q <= px * 0.88 and m not in PENDING and brain7.reentry_ok(m):  # 327
            REENTRY.pop(m); PENDING[m] = dict(t=time.time(), sym=sym, price=q, score=0.6, creator="", res={}, rate=0, holders=0, owners=[], dex="", devbal=None)
            log("entry_wait", m, sym, price=q, delay=CFG["ENTRY_DELAY"], reentry=True)
MODELN = lambda: brain.MODEL["n"]
def recap():
    c = conn(); V = CFG["VERSION"]; d0 = time.time() - 86400
    cl = [dict(x) for x in c.execute("SELECT * FROM positions WHERE status='closed' AND version=? AND closed>?", (V, d0))]
    cash = (c.execute("SELECT v FROM account WHERE k=?", ("cash_" + V,)).fetchone() or [CFG["START_BALANCE"]])[0]
    opn = c.execute("SELECT COUNT(*), COALESCE(SUM(cost),0) FROM positions WHERE status='open' AND version=?", (V,)).fetchone()
    seen = c.execute("SELECT COUNT(*) FROM seen WHERE first_ts>?", (d0,)).fetchone()[0]; c.close()
    eq = cash + opn[1]; w = sum(p["pnl"] > 0 for p in cl)
    return (f"☀️ RYDER morning recap (paper)\nEquity ${eq:.2f} (start ${CFG['START_BALANCE']:.0f}, {eq/CFG['START_BALANCE']-1:+.1%})\n"
            f"Last 24h: {len(cl)} trades, {w}W/{len(cl)-w}L, P&L ${sum(p['pnl'] for p in cl):+.2f}\n{seen} coins scanned · {opn[0]} open\n"
            "Lessons: " + "; ".join(brain.lessons()[:2]) + "\n" + brain4.missed_line() + "\n" + brain5.goals_line() + "\n" + brain5.exp_tally() + "\n" + brain6.best_worst_line() + "\n" + brain12.line() + "\nToday: " + brain5.day_mode(extras.STATE.get("regime")) + " · mentor agent: " + str(brain2.BRAIN.get("mentor")) + "\n" + brain7.recap_lines() + "\n" + brain8.funnel_line() + "\nAgent trust: " + ", ".join(f"{a} {t:.2f}" for a, t in brain2.BRAIN["trust"].items()))
SHEAL = {}
def jobs(k):
    if k % 60 == 7: SHEAL.update(brain2.selfheal({}, lambda n: None)); brain2.set_regime(extras.STATE.get("regime"))  # 139 / 152
    if k % 900 == 450:  # 153 shadow replay of coins killed 60-75 min ago
        c = conn(); ks = [(r["mint"], json.loads(r["data"]).get("reason"), json.loads(r["data"]).get("px")) for r in c.execute("SELECT mint,data FROM events WHERE kind='kill' AND ts BETWEEN ? AND ?", (time.time() - 4500, time.time() - 3600))][:60]; c.close()
        threading.Thread(target=brain2.shadow, args=([x for x in ks if x[2]],), daemon=True).start()
        c = conn(); ks2 = [(r["mint"], json.loads(r["data"]).get("reason"), json.loads(r["data"]).get("px")) for r in c.execute("SELECT mint,data FROM events WHERE kind='kill' AND ts BETWEEN ? AND ? ORDER BY ts DESC LIMIT 300", (time.time() - 4500, time.time() - 3600))]; c.close()
        brain3.POOL.submit(brain3._safe, "counterfactual", lambda: brain6.counterfactual([x for x in ks2 if x[2]]))  # 259 every pass gets an 'if I had bought' record
    if k % 60 == 20:
        st = state(); brain6.latency_check(st["decision_s"].get("p90"), st["latency"].get("scan_s_avg"))  # 239
    if k % 3600 == 100: CFG["ENTRY_DELAY"] = brain6.learned_wait()  # 236
    if time.localtime().tm_hour == 3 and time.localtime().tm_min == 5 and k % 60 == 0: brain2.nightly_review()  # 159
    if k % 900 == 0: brain10._bg("brain_learn", lambda: (brain.audit(), brain.check_promotion(), brain.drift(), brain.train()))  # 534 off the positions thread
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
        paused=brain.paused(), b7=brain7.status(), b8=brain8.status(), b9=brain9.status(), b10=brain10.status(), b11=brain11.status(), b12=brain12.status(), council=brain2.summary(), pos_health=brain6.HEALTH, stream=dict(subs=len(brain6.SUBS), events=brain6.STATS.get('trade_events', 0)), selfheal=SHEAL, rug_timing=more.rug_timing(), migrations=feed.STATS.get("migrations", 0), model=dict(trained=MODELN(), src="ml" if brain.MODEL["m"] is not None else "rules"),
        latency=dict(scan_s_avg=round(sum(LAT) / len(LAT), 1) if LAT else None, scan_s_last=LAT[-1] if LAT else None, pos_check_s=CFG["POS_SEC"],
                     ws_last_event_s=round(now - feed.STATS["last"]) if feed.STATS.get("last") else None),
        sources={h: dict(v, ok_rate=round(v["ok"] / max(1, v["ok"] + v["err"]), 2)) for h, v in HEALTH.items()})
def main(cycles=None):
    if CFG["VERSION"] not in ("v1", "v2"): CFG["MIN_LIQ"] = brain2.BRAIN["thresholds"]["min_liq"]  # 145 self-tuned Filter threshold
    if CFG["VERSION"] not in ("v1", "v2"): CFG["MIN_VOL_H1"] = brain2.BRAIN["thresholds"].get("min_vol_h1", CFG["MIN_VOL_H1"])  # 181
    try: BUILD = brain4.register_build(max(__import__("glob").glob("/workspace/backup_pre*"), key=os.path.getmtime))  # 200
    except Exception: BUILD = {}
    log("start", mode="PAPER", cfg=CFG, build=BUILD); n = 0
    try: brain8.enforce_ceiling(); brain8.invariants(); brain8.patience()  # 361 / 395
    except Exception as e: log("error", where="brain8.start", trace=str(e)[:200])
    try: brain7.paper_invariants()  # 358
    except Exception: pass
    try: ST = more.selftest()  # 120
    except Exception: ST = {}
    if not ST.get("dexscreener", {}).get("ok", True): log("skip", reason="selftest: DexScreener down at startup; brain.paused() will hold buys until it recovers")
    feed.start(); brain3.start(); brain11.start()  # 509
    def pos_loop():
        k = 0
        while True:
            k += 1; brain11.tick("pos")
            try:
                brain11.timed("positions", positions)
                if k % 3 == 0: brain11.timed("pending", pending)  # 422: 5s -> 3s
                if k % 600 == 0: detect.sweep_dead(); analyst.retune()
                if k % 30 == 0: reentry()
                for jn_, jf_ in (("jobs", jobs), ("brain3", brain3.jobs), ("brain7", brain7.jobs), ("brain9", brain9.jobs), ("brain10", brain10.jobs), ("brain12", brain12.jobs)):
                    brain11.timed(jn_, jf_, k)  # 532 per-job timing; >3s logs slow_step
                if k % 60 == 30: brain8.patience()  # 367
                if k % 3600 == 3599: brain8.hourly()  # 370/389
                if k % 300 == 150: brain3.POOL.submit(brain3._safe, "requeue_volume", brain4.requeue_volume)  # 188
                if k % 3600 == 1800: brain3.POOL.submit(brain3._safe, "loosen", brain4.loosen)  # 181
                if k % 1800 == 900: brain3.POOL.submit(brain3._safe, "rollback", brain4.check_rollback)  # 200
                if k % 60 == 3: threading.Thread(target=alerts.tick, args=(recap,), daemon=True).start()
                if k % 60 == 1: brain3.POOL.submit(extras.regime)  # mood fix: checked every minute (refresh 5 min / retry 60s), off the positions thread
                if k % 5 == 0: json.dump(state(), open(HB + ".tmp", "w"), default=str); os.replace(HB + ".tmp", HB)
            except Exception: log("error", where="positions", trace=traceback.format_exc()[-800:])
            time.sleep(CFG["POS_SEC"])
    PL = [threading.Thread(target=pos_loop, daemon=True)]; PL[0].start()
    def guard():  # 139 per-minute self-heal of the positions thread
        while True:
            time.sleep(60)
            if not PL[0].is_alive(): log("selfheal", what="pos_loop"); PL[0] = threading.Thread(target=pos_loop, daemon=True); PL[0].start()
    threading.Thread(target=guard, daemon=True).start()
    while cycles is None or n < cycles:
        t0 = time.time(); brain11.tick("scan")
        try: scan(); n += 1
        except Exception: log("error", where="scan", trace=traceback.format_exc()[-800:])
        ss = brain10.scan_hint(brain4.scan_sec(feed.STATS, len(INFLIGHT) + len(PENDING), CFG["SCAN_SEC"]))  # 198 / 451
        while time.time() - t0 < ss and not feed.NEW: time.sleep(1)  # wake immediately on live launches
        time.sleep(0.5)
if __name__ == "__main__": main(int(sys.argv[1]) if len(sys.argv) > 1 else None)
