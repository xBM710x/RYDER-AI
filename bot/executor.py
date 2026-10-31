"""Stage 4: Executor. PAPER fills at DexScreener priceUsd. No wallets, no signing, no real orders."""
import time
from common import CFG
from logger import conn, log
import risk, alerts
CK = 'cash' if CFG['VERSION'] == 'v1' else 'cash_' + CFG['VERSION']
RISK = {}  # last computed risk state (exported)
def balance(c, ck=None):
    ck = ck or CK; r = c.execute("SELECT v FROM account WHERE k=?", (ck,)).fetchone()
    if r is None: c.execute("INSERT INTO account VALUES(?,?)", (ck, CFG["START_BALANCE"])); c.commit(); return CFG["START_BALANCE"]
    return r["v"]
def equity(c, ver=None):
    ver = ver or CFG["VERSION"]
    return balance(c, "cash_" + ver) + sum(r["cost"] for r in c.execute("SELECT cost FROM positions WHERE status='open' AND version=?", (ver,)))
def buy(mint, symbol, pair, score, ver=None, mult=1.0, stop_pct=None, conf=None, extra=None):
    ver = ver or CFG["VERSION"]; CK = "cash_" + ver
    c = conn(); cash = balance(c, CK)
    if c.execute("SELECT 1 FROM positions WHERE mint=? AND status='open' AND version=?", (mint, ver)).fetchone(): c.close(); return
    if ver == CFG["VERSION"] and c.execute("SELECT COUNT(*) FROM positions WHERE version=? AND opened>?", (ver, time.time() - 3600)).fetchone()[0] >= CFG["MAX_PER_HOUR"]:
        log("skip", mint, symbol, reason=f"max {CFG['MAX_PER_HOUR']} trades/hour"); c.close(); return
    xr = (extra or {}).get("_res"); extra = {k: v for k, v in (extra or {}).items() if k != "_res"}
    if ver not in ("v1", "v2"):  # b17: stale-data + liquidity-drop breakers, 7-factor scorecard floors (adds rejects only)
        import brain17
        bz = brain17.stale(pair) or brain17.liq_blocked(mint, pair)
        if bz: log("kill", mint, symbol, reason=bz.split(":")[0], detail=bz, final=False, book=ver); c.close(); return
        okz, extra = brain17.gate(mint, symbol, pair, xr, ver, extra)
        if not okz: c.close(); return
    m15, why15 = __import__("brain15").size_mult(ver, mint in __import__("rcfallback").USED)  # down-only: drawdown / expectancy / backup-check brakes
    if why15: log("size_brake", mint, symbol, mult=m15, why=why15, book=ver)
    size = min(cash, equity(c, ver) * CFG["MAX_PCT_PER_TRADE"] * mult * m15); quote = float(pair["priceUsd"])
    sl = __import__('brain6').split_slip(size, pair) if CFG['VERSION'] not in ('v1', 'v2') else CFG['SLIP']  # 186 depth-based slippage
    if sl > 0.03: log('skip', mint, symbol, reason=f'est. slippage {sl*100:.1f}% too high for pool depth'); c.close(); return
    price = quote * (1 + sl) / (1 - CFG["FEE"])  # v3: paper fill incl. slippage + fee
    if CFG["VERSION"] not in ("v1", "v2"):
        day0 = time.mktime(time.localtime()[:3] + (0, 0, 0, 0, 0, -1))
        today = sum(r["pnl"] for r in c.execute("SELECT pnl FROM positions WHERE status='closed' AND version=? AND closed>=?", (ver, day0)))
        if today <= -0.15 * CFG["START_BALANCE"]:
            log("skip", mint, symbol, reason="daily loss limit -15% hit; paused until midnight PT", today=round(today, 2)); c.close(); return
        last = [r["pnl"] for r in c.execute("SELECT pnl FROM positions WHERE status='closed' AND version=? AND reason!='partial_tp' ORDER BY closed DESC LIMIT 3", (ver,))]
        streak = next((i for i, p in enumerate(last) if p > 0), len(last))
        if streak >= 2: size *= 0.5 if streak >= 3 else 0.75  # v3: shrink after losing streak
        if ver == CFG["VERSION"]: RISK.update(day_pnl=round(today, 2), day_limit=-0.15 * CFG["START_BALANCE"], loss_streak=streak, size_mult=round(mult * (0.5 if streak >= 3 else 0.75 if streak >= 2 else 1), 2), ts=time.time())
    if CFG["VERSION"] not in ("v1", "v2") and 1 <= size < 5 and cash >= 5: size = 5.0  # 382 no dust paper fills (min $5)
    if size < 1: log("skip", mint, symbol, reason="insufficient paper cash", cash=cash); c.close(); return
    if CFG["VERSION"] not in ("v1", "v2"):
        cap = MAX_COIN_PCT * equity(c, ver); held = sum(r[0] for r in c.execute("SELECT cost FROM positions WHERE mint=? AND status='open' AND version=?", (mint, ver)))
        if held + size > cap: size = max(0, cap - held)  # per-coin exposure cap (12% of desk equity, adds/re-buys included)
        if size < 1: log("skip", mint, symbol, reason="per-coin exposure cap", held=round(held, 2), cap=round(cap, 2), book=ver); c.close(); return
        mv = mev_cost(size, (pair.get("liquidity") or {}).get("usd")); price *= 1 + mv  # sandwich/MEV cost on the paper fill
    stop = price * (1 - stop_pct) if stop_pct else risk.initial_stop(price)  # stop fixed before entry
    c.execute("INSERT INTO positions(mint,symbol,pair,entry,qty,cost,stop,peak,trailing,opened,status,version) VALUES(?,?,?,?,?,?,?,?,0,?,'open',?)",
              (mint, symbol, pair["pairAddress"], price, size / price, size, stop, price, time.time(), ver))
    c.execute("UPDATE account SET v=v-? WHERE k=?", (size, CK)); c.commit(); c.close()
    try:
        import brain9; brain9.note_entry(mint, price); brain9.milestone("buy"); ver == CFG["VERSION"] and brain9.note_margins(pair, mint)  # 413/414/433
    except Exception: pass
    log("paper_buy", mint, symbol, price=price, quote=quote, usd=round(size, 2), stop=stop, score=score, conf=conf, book=ver, liq=(pair.get("liquidity") or {}).get("usd"), url=pair.get("url"), **(extra or {}))
    try: alerts.on_buy(symbol, size, price, score, stop, (pair.get("liquidity") or {}).get("usd"), pair.get("url"), ver, (str((extra or {}).get("why1") or "") + "\n" + ((extra or {}).get("plan") or {}).get("text", "") + "\n" + str(((extra or {}).get("council") or {}).get("reason") or "") + "\n" + __import__("brain14").votes_text((extra or {}).get("council"))).strip())
    except Exception: pass
    return True
MAX_COIN_PCT = 0.12; LIQ = {}  # LIQ: mint -> latest pool liquidity (positions loop), for exit MEV cost
def mev_cost(usd, liq):
    """Sandwich/MEV model for paper fills (2026-10-31): bots extract roughly another price-impact on memecoin swaps.
    0.15% base + size/liquidity, capped at 2%; unknown liquidity -> 1%. Applied on top of the existing slippage + fee, buys AND sells."""
    try: liq = float(liq or 0)
    except Exception: liq = 0
    return 0.01 if liq <= 0 else min(0.02, 0.0015 + float(usd) / liq)
def _exit_px(pos, quote, qty):
    px = quote * (1 - CFG["SLIP"]) * (1 - CFG["FEE"])
    if pos.get("version") not in ("v1", "v2"): px *= 1 - mev_cost(qty * quote, LIQ.get(pos["mint"]))
    return px
def sell(pos, quote, reason):
    price = _exit_px(pos, quote, pos["qty"])  # v3: paper fill incl. slippage + fee (+ MEV model)
    c = conn(); proceeds = pos["qty"] * price; pnl = proceeds - pos["cost"]
    c.execute("UPDATE positions SET status='closed',closed=?,exit=?,pnl=?,reason=? WHERE id=?", (time.time(), price, pnl, reason, pos["id"]))
    c.execute("UPDATE account SET v=v+? WHERE k=?", (proceeds, "cash" if pos.get("version", "v1") == "v1" else "cash_" + pos["version"])); c.commit(); c.close()
    log("paper_exit", pos["mint"], pos["symbol"], entry=pos["entry"], exit=price, stop=pos["stop"], slip_pct=round((price / pos["stop"] - 1) * 100, 2), pnl=round(pnl, 2), pct=round((price / pos["entry"] - 1) * 100, 2), quote=quote, reason=reason, book=pos.get("version"))
    try: alerts.on_exit(pos["symbol"], (price / pos["entry"] - 1) * 100, pnl, reason, pos.get("version", ""), __import__("brain7").exit_extra(dict(pos, peak=max(pos.get("peak") or 0, quote)), quote))  # 355
    except Exception: pass
    try:  # 210 decision grade (all paper books)
        import brain5; c3 = conn(); tp = c3.execute("SELECT COALESCE(SUM(pnl),0) FROM positions WHERE mint=? AND reason='partial_tp' AND version=?", (pos["mint"], pos.get("version"))).fetchone()[0]; c3.close()
        brain5.on_close(pos, pnl + tp)
        import brain9; brain9.note_exit(pos, price, reason)  # 411
        if reason in ("stop_loss", "early_stop") and pos.get("version") == CFG["VERSION"]: brain9.stop_reentry_watch(pos)  # 429
        import brain7; brain7.review(dict(pos, reason=reason), pnl + tp)  # 277/278/288/320-326/350-352
        if reason in ("lp_pull", "dev_sell", "rug_recheck"): brain7.theme_cooldown(pos["symbol"], reason)  # 328
    except Exception as e: log("error", where="grade", trace=str(e)[:200])
    if pos.get("version") == CFG["VERSION"]:  # 150/160 agents learn from every closed paper trade
        try:
            import json, brain2; c = conn(); r = c.execute("SELECT data FROM events WHERE kind='paper_buy' AND mint=? ORDER BY ts DESC LIMIT 1", (pos["mint"],)).fetchone(); c.close()
            cn = (json.loads(r["data"]).get("council") or {}) if r else {}
            tot = pnl + (c2 := conn()).execute("SELECT COALESCE(SUM(pnl),0) FROM positions WHERE mint=? AND reason='partial_tp' AND version=?", (pos["mint"], pos["version"])).fetchone()[0]; c2.close()
            brain2.learn({a: tuple(x) for a, x in (cn.get("votes") or {}).items()}, tot, cn.get("pattern"), (time.time() - pos["opened"]) / 60)
        except Exception as e: log("error", where="learn", trace=str(e)[:200])
def add(pos, quote, usd, pair):
    """254: paper add-on to a starter position after confirmation (same stop; averaged entry)."""
    sl = __import__('brain6').split_slip(usd, pair); price = quote * (1 + sl) / (1 - CFG["FEE"]); ck = "cash" if pos["version"] == "v1" else "cash_" + pos["version"]
    price *= 1 + mev_cost(usd, (pair.get("liquidity") or {}).get("usd"))
    c = conn(); cash = balance(c, ck); usd = min(usd, cash, max(0, MAX_COIN_PCT * equity(c, pos["version"]) - pos["cost"]))  # per-coin cap
    if usd < 1: c.close(); return False
    q = usd / price; nq = pos["qty"] + q; ne = (pos["cost"] + usd) / nq
    c.execute("UPDATE positions SET qty=?, cost=?, entry=? WHERE id=?", (nq, pos["cost"] + usd, ne, pos["id"])); c.execute("UPDATE account SET v=v-? WHERE k=?", (usd, ck)); c.commit(); c.close()
    log("paper_add", pos["mint"], pos["symbol"], usd=round(usd, 2), price=price, new_entry=ne, book=pos["version"]); return True
def partial(pos, quote, level=1, frac=0.5, reason="partial_tp"):
    """v3: sell half at +30% as its own closed row (reason partial_tp); remaining half keeps trailing. frac/reason: scale-outs and copy sells."""
    frac = max(0.01, min(0.99, frac)); price = _exit_px(pos, quote, pos["qty"] * frac); hq, hc = pos["qty"] * frac, pos["cost"] * frac; pnl = hq * price - hc
    c = conn()
    c.execute("INSERT INTO positions(mint,symbol,pair,entry,qty,cost,stop,peak,trailing,opened,closed,exit,pnl,reason,status,version,tp_done) VALUES(?,?,?,?,?,?,?,?,1,?,?,?,?,'partial_tp','closed',?,1)",
              (pos["mint"], pos["symbol"], pos["pair"], pos["entry"], hq, hc, pos["stop"], pos["peak"], pos["opened"], time.time(), price, pnl, pos["version"]))
    c.execute("UPDATE positions SET qty=?, cost=?, tp_done=?, trailing=1 WHERE id=?", (pos["qty"] - hq, pos["cost"] - hc, level, pos["id"]))
    c.execute("UPDATE account SET v=v+? WHERE k=?", (hq * price, "cash" if pos["version"] == "v1" else "cash_" + pos["version"])); c.commit(); c.close()
    log("paper_exit", pos["mint"], pos["symbol"], entry=pos["entry"], exit=price, pnl=round(pnl, 2), pct=round((price / pos["entry"] - 1) * 100, 2), quote=quote, reason="partial_tp", level=level, why=reason, frac=round(frac, 3), book=pos.get("version"))
    try: alerts.on_exit(pos["symbol"], (price / pos["entry"] - 1) * 100, pnl, "partial_tp", pos.get("version", ""))
    except Exception: pass
