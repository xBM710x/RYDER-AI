"""v3 upgrades 21-40 (PAPER ONLY, public read-only data, no keys)."""
import time, re, json, collections
from common import http_json, CFG, dex_market
from logger import conn, log
SOL = "So11111111111111111111111111111111111111112"
STATE = dict(regime={}, tod={}, last_regime=0)
def _t(c):
    c.executescript("""CREATE TABLE IF NOT EXISTS smart_wallets(wallet TEXT PRIMARY KEY, wins INT, ts REAL);
    CREATE TABLE IF NOT EXISTS holders(mint TEXT, wallet TEXT, PRIMARY KEY(mint, wallet));
    CREATE TABLE IF NOT EXISTS names(sym TEXT, mint TEXT, liq REAL, ts REAL, PRIMARY KEY(sym, mint));""")
# 31 narrative tagging
NARR = dict(ai=r"\b(ai|gpt|agent|bot|neural|grok)", dog=r"(dog|doge|shib|inu|pup|wif)", cat=r"(cat|kitty|meow|popcat)", frog=r"(frog|pepe|toad)",
            politics=r"(trump|maga|biden|elon|vote|usa)", anime=r"(anime|waifu|chan|kun)", food=r"(pizza|burger|taco|banana)", animal=r"(ape|monkey|bear|bull|fish|bird|hamster)")
def narrative(name):
    n = (name or "").lower()
    return next((k for k, p in NARR.items() if re.search(p, n)), "other")
# 32 copycat filter
def copycat(sym, mint, liq):
    s = (sym or "").strip().lower()
    if not s: return None
    c = conn(); _t(c); c.execute("INSERT OR REPLACE INTO names VALUES(?,?,?,?)", (s, mint, liq or 0, time.time()))
    r = c.execute("SELECT mint, liq FROM names WHERE sym=? AND mint!=? AND ts>? ORDER BY liq DESC LIMIT 1", (s, mint, time.time() - 86400)).fetchone()
    c.commit(); c.close()
    return r["mint"] if r and (r["liq"] or 0) >= (liq or 0) else None
# 28 sell simulation (Jupiter quotes only; never executes)
def sell_sim(mint, sol_in=200_000_000):
    q = lambda a, b, amt: http_json(f"https://lite-api.jup.ag/swap/v1/quote?inputMint={a}&outputMint={b}&amount={amt}&slippageBps=500", timeout=10)
    buy = q(SOL, mint, sol_in); back = q(mint, SOL, buy["outAmount"])
    loss = 1 - int(back["outAmount"]) / sol_in
    return ("fail" if loss > 0.15 else "pass"), f"round-trip 0.2 SOL quote loses {loss*100:.1f}% (tax/impact)"
# 30 market regime
def regime():
    """Market mood from SOL 1h/24h change. Fix 2026-10-30: one DexScreener 429 left mood 'unknown' for 10+ min (no retry, no fallback).
    Now: refresh every 5 min, retry after 60s on failure, CoinGecko fallback (24h only; 1h kept from last good read), last good value kept up to 1h."""
    now = time.time()
    if now - STATE["last_regime"] > 300 and now - STATE.get("last_try", 0) > 60:
        STATE["last_try"] = now; h1 = h24 = None
        try:
            p = max(http_json("https://api.dexscreener.com/tokens/v1/solana/" + SOL) or [], key=lambda p: (p.get("liquidity") or {}).get("usd", 0))
            ch = p.get("priceChange") or {}; h1, h24 = ch.get("h1"), ch.get("h24"); src = "dexscreener"
        except Exception: pass
        if h24 is None:
            try:
                g = http_json("https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd&include_24hr_change=true", timeout=8)
                h24 = round(float(g["solana"]["usd_24h_change"]), 2); h1 = (STATE["regime"] or {}).get("sol_h1"); src = "coingecko"
            except Exception: pass
        if h24 is not None:
            h1f = h1 or 0
            mood = "risk-off" if h24 < -5 or h1f < -2 else "hot" if h24 > 5 else "neutral"
            STATE["regime"] = dict(sol_h1=h1, sol_h24=h24, mood=mood, size_mult=0.5 if mood == "risk-off" else 1.0, src=src, at=round(now)); STATE["last_regime"] = now
    if STATE["regime"] and now - STATE["last_regime"] > 3600: STATE["regime"] = {}
    return STATE["regime"] or dict(mood="unknown", size_mult=1.0)
# 29 time-of-day learning
def tod_mult():
    h = time.localtime().tm_hour; c = conn()
    rows = [r["pnl"] for r in c.execute("SELECT pnl,closed FROM positions WHERE status='closed' AND version=?", (CFG["VERSION"],)) if time.localtime(r["closed"]).tm_hour == h]; c.close()
    return (0.5 if len(rows) >= 3 and sum(rows) < 0 else 1.0), len(rows)
# 21 smart wallets: holders of past winners
def save_holders(mint, owners):
    c = conn(); _t(c); c.executemany("INSERT OR IGNORE INTO holders VALUES(?,?)", [(mint, w) for w in owners[:10] if w]); c.commit(); c.close()
def smart_hits(owners, mint=None):
    c = conn(); _t(c)
    if not owners and mint: owners = [r["wallet"] for r in c.execute("SELECT wallet FROM holders WHERE mint=?", (mint,))]; n = sum(1 for w in owners if c.execute("SELECT 1 FROM smart_wallets WHERE wallet=?", (w,)).fetchone()); c.close(); return n
def learn_winner(mint):
    c = conn(); _t(c)
    for r in c.execute("SELECT wallet FROM holders WHERE mint=?", (mint,)).fetchall():
        c.execute("INSERT INTO smart_wallets VALUES(?,1,?) ON CONFLICT(wallet) DO UPDATE SET wins=wins+1", (r["wallet"], time.time()))
    c.commit(); c.close()
# 33 volatility stop (6%..10%)
def vol_stop(pair):
    pc = (pair or {}).get("priceChange") or {}; v = abs(pc.get("m5") or 0)
    return round(min(0.10, max(0.06, 0.06 + v / 250)), 3)
# 24/25 bonding progress + migration tag
def launch_stage(pair):
    dex = (pair or {}).get("dexId", ""); mc = (pair or {}).get("marketCap") or (pair or {}).get("fdv") or 0
    age = (time.time() * 1000 - ((pair or {}).get("pairCreatedAt") or 0)) / 60000
    if dex in ("pumpfun", "pump-fun"): return dict(stage="bonding", progress=round(min(100, mc / 69000 * 100)), age_min=round(age))
    if dex == "pumpswap" and age < 45: return dict(stage="just_migrated", progress=100, age_min=round(age))
    return dict(stage="dex", progress=100, age_min=round(age))
# 22 holder growth (holders per minute of pair age)
def holder_rate(rc, pair):
    n = rc.get("totalHolders") or 0; age = max(1, (time.time() * 1000 - ((pair or {}).get("pairCreatedAt") or 0)) / 60000)
    return n, round(n / age, 2)
# 40 confidence
def confidence(score, res, smart, rate, reg):
    unverified = sum(1 for v in res.values() if isinstance(v, tuple) and v[2] in ("unverified", "rugcheck-approx-fallback"))
    c = score + 0.05 * min(smart, 2) + (0.05 if rate >= 5 else 0) - 0.05 * unverified - (0.1 if reg.get("mood") == "risk-off" else 0)
    return round(max(0, min(1, c)), 3)
# 36 post-mortem
def postmortem(pos, exit_price, reason):
    c = conn(); e = c.execute("SELECT data FROM events WHERE kind='paper_buy' AND mint=? ORDER BY ts DESC LIMIT 1", (pos["mint"],)).fetchone(); c.close()
    b = json.loads(e["data"]) if e else {}
    pk = (pos.get("peak") or pos["entry"]) / pos["entry"] - 1; pct = exit_price / pos["entry"] - 1; held = (time.time() - pos["opened"]) / 60
    lesson = ("gave back a big run: trail could be tighter" if pk > 0.25 and pct < 0.05 else "stopped quickly: possibly bought a spike" if reason == "stop_loss" and held < 3
              else "dev/LP event: detection worked" if reason in ("dev_sell", "lp_pull") else "flat: time stop freed capital" if reason == "time_stop" else "clean")
    log("postmortem", pos["mint"], pos["symbol"], held_min=round(held, 1), peak_pct=round(pk * 100, 1), exit_pct=round(pct * 100, 1), reason=reason,
        score=b.get("score"), conf=b.get("conf"), narrative=b.get("narrative"), stage=b.get("stage"), lesson=lesson)
    if pct > 0.3 and pos.get("version") == CFG["VERSION"]: learn_winner(pos["mint"])
