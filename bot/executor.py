"""Stage 4: Executor. PAPER fills at DexScreener priceUsd. No wallets, no signing, no real orders."""
import time
from common import CFG
from logger import conn, log
import risk
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
    size = min(cash, equity(c, ver) * CFG["MAX_PCT_PER_TRADE"] * mult); quote = float(pair["priceUsd"])
    price = quote * (1 + CFG["SLIP"]) / (1 - CFG["FEE"])  # v3: paper fill incl. slippage + fee
    if CFG["VERSION"] not in ("v1", "v2"):
        day0 = time.mktime(time.localtime()[:3] + (0, 0, 0, 0, 0, -1))
        today = sum(r["pnl"] for r in c.execute("SELECT pnl FROM positions WHERE status='closed' AND version=? AND closed>=?", (ver, day0)))
        if today <= -0.15 * CFG["START_BALANCE"]:
            log("skip", mint, symbol, reason="daily loss limit -15% hit; paused until midnight PT", today=round(today, 2)); c.close(); return
        last = [r["pnl"] for r in c.execute("SELECT pnl FROM positions WHERE status='closed' AND version=? AND reason!='partial_tp' ORDER BY closed DESC LIMIT 3", (ver,))]
        streak = next((i for i, p in enumerate(last) if p > 0), len(last))
        if streak >= 2: size *= 0.5 if streak >= 3 else 0.75  # v3: shrink after losing streak
        if ver == CFG["VERSION"]: RISK.update(day_pnl=round(today, 2), day_limit=-0.15 * CFG["START_BALANCE"], loss_streak=streak, size_mult=round(mult * (0.5 if streak >= 3 else 0.75 if streak >= 2 else 1), 2), ts=time.time())
    if size < 1: log("skip", mint, symbol, reason="insufficient paper cash", cash=cash); c.close(); return
    stop = price * (1 - stop_pct) if stop_pct else risk.initial_stop(price)  # stop fixed before entry
    c.execute("INSERT INTO positions(mint,symbol,pair,entry,qty,cost,stop,peak,trailing,opened,status,version) VALUES(?,?,?,?,?,?,?,?,0,?,'open',?)",
              (mint, symbol, pair["pairAddress"], price, size / price, size, stop, price, time.time(), ver))
    c.execute("UPDATE account SET v=v-? WHERE k=?", (size, CK)); c.commit(); c.close()
    log("paper_buy", mint, symbol, price=price, quote=quote, usd=round(size, 2), stop=stop, score=score, conf=conf, book=ver, liq=(pair.get("liquidity") or {}).get("usd"), url=pair.get("url"), **(extra or {}))
    return True
def sell(pos, quote, reason):
    price = quote * (1 - CFG["SLIP"]) * (1 - CFG["FEE"])  # v3: paper fill incl. slippage + fee
    c = conn(); proceeds = pos["qty"] * price; pnl = proceeds - pos["cost"]
    c.execute("UPDATE positions SET status='closed',closed=?,exit=?,pnl=?,reason=? WHERE id=?", (time.time(), price, pnl, reason, pos["id"]))
    c.execute("UPDATE account SET v=v+? WHERE k=?", (proceeds, "cash" if pos.get("version", "v1") == "v1" else "cash_" + pos["version"])); c.commit(); c.close()
    log("paper_exit", pos["mint"], pos["symbol"], entry=pos["entry"], exit=price, stop=pos["stop"], slip_pct=round((price / pos["stop"] - 1) * 100, 2), pnl=round(pnl, 2), pct=round((price / pos["entry"] - 1) * 100, 2), quote=quote, reason=reason)
def partial(pos, quote, level=1):
    """v3: sell half at +30% as its own closed row (reason partial_tp); remaining half keeps trailing."""
    price = quote * (1 - CFG["SLIP"]) * (1 - CFG["FEE"]); hq, hc = pos["qty"] / 2, pos["cost"] / 2; pnl = hq * price - hc
    c = conn()
    c.execute("INSERT INTO positions(mint,symbol,pair,entry,qty,cost,stop,peak,trailing,opened,closed,exit,pnl,reason,status,version,tp_done) VALUES(?,?,?,?,?,?,?,?,1,?,?,?,?,'partial_tp','closed',?,1)",
              (pos["mint"], pos["symbol"], pos["pair"], pos["entry"], hq, hc, pos["stop"], pos["peak"], pos["opened"], time.time(), price, pnl, pos["version"]))
    c.execute("UPDATE positions SET qty=?, cost=?, tp_done=?, trailing=1 WHERE id=?", (hq, hc, level, pos["id"]))
    c.execute("UPDATE account SET v=v+? WHERE k=?", (hq * price, "cash" if pos["version"] == "v1" else "cash_" + pos["version"])); c.commit(); c.close()
    log("paper_exit", pos["mint"], pos["symbol"], entry=pos["entry"], exit=price, pnl=round(pnl, 2), pct=round((price / pos["entry"] - 1) * 100, 2), quote=quote, reason="partial_tp", level=level)
