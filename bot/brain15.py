"""Reliability / profitability upgrades (PAPER ONLY), 2026-10-30 night. Only sizing DOWN and stats; no bar, safety check or exit loosened.
Q  trade-quality stats per desk (win rate, expectancy, profit factor, payoff, max drawdown, avg hold) -> heartbeat + data.json 'trade_quality'.
DD equity drawdown brake: desk equity >10% under its peak closed-equity -> 0.5x size (until back within 5%).
EX expectancy brake: once a desk has 20+ closed trades, rolling-20 expectancy < 0 -> 0.5x size.
FB backup-check trades: coins approved through the on-chain rugcheck backup trade at 0.5x size."""
import sqlite3, os, time
DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "desk.db")
def _trades(c, ver):
    return [dict(pnl=r[0] or 0, cost=r[1] or 0, opened=r[2], closed=r[3], reason=r[4]) for r in c.execute(
        "SELECT pnl, cost, opened, closed, reason FROM positions WHERE status='closed' AND version=? ORDER BY closed", (ver,))]
def stats(ts, start=300.0):
    full = [t for t in ts if t["reason"] != "partial_tp"]; n = len(full)
    if not ts: return dict(n=0)
    w = [t["pnl"] for t in ts if t["pnl"] > 0]; l = [t["pnl"] for t in ts if t["pnl"] <= 0]
    eq, pk, dd = start, start, 0.0
    for t in ts: eq += t["pnl"]; pk = max(pk, eq); dd = max(dd, (pk - eq) / pk)
    return dict(n=n, fills=len(ts), win_rate=round(len(w) / len(ts), 3), expectancy=round(sum(t["pnl"] for t in ts) / len(ts), 3),
                profit_factor=round(sum(w) / -sum(l), 2) if l and sum(l) < 0 else None, avg_win=round(sum(w) / len(w), 2) if w else None,
                avg_loss=round(sum(l) / len(l), 2) if l else None, payoff=round((sum(w) / len(w)) / (-sum(l) / len(l)), 2) if w and l and sum(l) < 0 else None,
                total_pnl=round(sum(t["pnl"] for t in ts), 2), max_drawdown_pct=round(dd * 100, 2), equity_closed=round(eq, 2), peak_equity=round(pk, 2),
                avg_hold_min=round(sum((t["closed"] - t["opened"]) / 60 for t in ts) / len(ts), 1))
def quality():
    c = sqlite3.connect(DB, timeout=30)
    try:
        sb = {k: v for k, v in c.execute("SELECT k, v FROM account")}
        out = {v: stats(_trades(c, v)) for (v,) in c.execute("SELECT DISTINCT version FROM positions")}
    finally: c.close()
    return out
_M = {}
def size_mult(ver, fallback=False):
    """Combined down-only multiplier with reasons. Cached 30s per desk."""
    h = _M.get(ver)
    if h and time.time() - h[0] < 30: m, why = h[1]
    else:
        c = sqlite3.connect(DB, timeout=30); ts = _trades(c, ver); c.close(); m, why = 1.0, []
        s = stats(ts)
        if s.get("n"):
            cur_dd = (s["peak_equity"] - s["equity_closed"]) / s["peak_equity"]
            if cur_dd > 0.10 or (cur_dd > 0.05 and DDON.get(ver)): DDON[ver] = True; m *= 0.5; why.append(f"drawdown brake ({cur_dd:.0%} under peak)")
            else: DDON[ver] = False
        full = [t for t in ts if t["reason"] != "partial_tp"]
        if len(full) >= 20:
            e20 = sum(t["pnl"] for t in full[-20:]) / 20
            if e20 < 0: m *= 0.5; why.append(f"expectancy brake (last 20 avg ${e20:+.2f})")
        _M[ver] = (time.time(), (m, why))
    if fallback: m *= 0.5; why = why + ["backup safety check (rugcheck down)"]
    return round(m, 3), why
DDON = {}
