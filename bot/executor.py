"""Stage 4: Executor. PAPER fills at DexScreener priceUsd. No wallets, no signing, no real orders."""
import time
from common import CFG
from logger import conn, log
import risk
CK = 'cash' if CFG['VERSION'] == 'v1' else 'cash_' + CFG['VERSION']
def balance(c):
    r = c.execute("SELECT v FROM account WHERE k=?", (CK,)).fetchone()
    if r is None: c.execute("INSERT INTO account VALUES(?,?)", (CK, CFG["START_BALANCE"])); c.commit(); return CFG["START_BALANCE"]
    return r["v"]
def equity(c):
    return balance(c) + sum(r["cost"] for r in c.execute("SELECT cost FROM positions WHERE status='open' AND version=?", (CFG["VERSION"],)))
def buy(mint, symbol, pair, score):
    c = conn(); cash = balance(c)
    if c.execute("SELECT 1 FROM positions WHERE mint=? AND status='open'", (mint,)).fetchone(): c.close(); return
    size = min(cash, equity(c) * CFG["MAX_PCT_PER_TRADE"]); quote = float(pair["priceUsd"])
    price = quote * (1 + CFG["SLIP"]) / (1 - CFG["FEE"])  # v3: paper fill incl. slippage + fee
    if CFG["VERSION"] not in ("v1", "v2"):
        day0 = time.mktime(time.localtime()[:3] + (0, 0, 0, 0, 0, -1))
        today = sum(r["pnl"] for r in c.execute("SELECT pnl FROM positions WHERE status='closed' AND version=? AND closed>=?", (CFG["VERSION"], day0)))
        if today <= -0.15 * CFG["START_BALANCE"]:
            log("skip", mint, symbol, reason="daily loss limit -15% hit; paused until midnight PT", today=round(today, 2)); c.close(); return
        last = [r["pnl"] for r in c.execute("SELECT pnl FROM positions WHERE status='closed' AND version=? AND reason!='partial_tp' ORDER BY closed DESC LIMIT 3", (CFG["VERSION"],))]
        streak = next((i for i, p in enumerate(last) if p > 0), len(last))
        if streak >= 2: size *= 0.5 if streak >= 3 else 0.75  # v3: shrink after losing streak
    if size < 1: log("skip", mint, symbol, reason="insufficient paper cash", cash=cash); c.close(); return
    stop = risk.initial_stop(price)  # stop fixed before entry
    c.execute("INSERT INTO positions(mint,symbol,pair,entry,qty,cost,stop,peak,trailing,opened,status,version) VALUES(?,?,?,?,?,?,?,?,0,?,'open',?)",
              (mint, symbol, pair["pairAddress"], price, size / price, size, stop, price, time.time(), CFG["VERSION"]))
    c.execute("UPDATE account SET v=v-? WHERE k=?", (size, CK)); c.commit(); c.close()
    log("paper_buy", mint, symbol, price=price, quote=quote, usd=round(size, 2), stop=stop, score=score, url=pair.get("url"))
def sell(pos, quote, reason):
    price = quote * (1 - CFG["SLIP"]) * (1 - CFG["FEE"])  # v3: paper fill incl. slippage + fee
    c = conn(); proceeds = pos["qty"] * price; pnl = proceeds - pos["cost"]
    c.execute("UPDATE positions SET status='closed',closed=?,exit=?,pnl=?,reason=? WHERE id=?", (time.time(), price, pnl, reason, pos["id"]))
    c.execute("UPDATE account SET v=v+? WHERE k=?", (proceeds, "cash" if pos.get("version", "v1") == "v1" else "cash_" + pos["version"])); c.commit(); c.close()
    log("paper_exit", pos["mint"], pos["symbol"], entry=pos["entry"], exit=price, stop=pos["stop"], slip_pct=round((price / pos["stop"] - 1) * 100, 2), pnl=round(pnl, 2), pct=round((price / pos["entry"] - 1) * 100, 2), quote=quote, reason=reason)
def partial(pos, quote):
    """v3: sell half at +30% as its own closed row (reason partial_tp); remaining half keeps trailing."""
    price = quote * (1 - CFG["SLIP"]) * (1 - CFG["FEE"]); hq, hc = pos["qty"] / 2, pos["cost"] / 2; pnl = hq * price - hc
    c = conn()
    c.execute("INSERT INTO positions(mint,symbol,pair,entry,qty,cost,stop,peak,trailing,opened,closed,exit,pnl,reason,status,version,tp_done) VALUES(?,?,?,?,?,?,?,?,1,?,?,?,?,'partial_tp','closed',?,1)",
              (pos["mint"], pos["symbol"], pos["pair"], pos["entry"], hq, hc, pos["stop"], pos["peak"], pos["opened"], time.time(), price, pnl, pos["version"]))
    c.execute("UPDATE positions SET qty=?, cost=?, tp_done=1, trailing=1 WHERE id=?", (hq, hc, pos["id"]))
    c.execute("UPDATE account SET v=v+? WHERE k=?", (hq * price, "cash" if pos["version"] == "v1" else "cash_" + pos["version"])); c.commit(); c.close()
    log("paper_exit", pos["mint"], pos["symbol"], entry=pos["entry"], exit=price, pnl=round(pnl, 2), pct=round((price / pos["entry"] - 1) * 100, 2), quote=quote, reason="partial_tp")
