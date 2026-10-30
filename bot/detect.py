"""v3 detection (PAPER ONLY, public data, no keys): known-rug wallet list, top-holder funding clusters, dev sell tracking."""
import time, json
from common import CFG, dex_market
from logger import conn, log
import onchain
def _init(c):
    c.executescript("""CREATE TABLE IF NOT EXISTS rug_wallets(wallet TEXT PRIMARY KEY, reason TEXT, ts REAL);
    CREATE TABLE IF NOT EXISTS creators(mint TEXT PRIMARY KEY, creator TEXT, first_price REAL, first_liq REAL, ts REAL, checked INT DEFAULT 0);""")
def is_rugger(w):
    if not w: return False, ""
    c = conn(); _init(c); r = c.execute("SELECT reason FROM rug_wallets WHERE wallet=?", (w,)).fetchone(); c.close()
    return (True, r["reason"]) if r else (False, "")
def add_rugger(w, reason):
    if not w: return
    c = conn(); _init(c); new = c.execute("INSERT OR IGNORE INTO rug_wallets VALUES(?,?,?)", (w, reason, time.time())).rowcount; c.commit(); c.close()
    if new: log("rug_list_add", wallet=w, reason=reason)
def remember_creator(mint, creator, pair):
    if not creator: return
    c = conn(); _init(c)
    c.execute("INSERT OR IGNORE INTO creators(mint,creator,first_price,first_liq,ts) VALUES(?,?,?,?,?)",
              (mint, creator, float((pair or {}).get("priceUsd") or 0), ((pair or {}).get("liquidity") or {}).get("usd") or 0, time.time()))
    c.commit(); c.close()
def sweep_dead(min_age=1800, n=30):
    """Auto-add creators whose tokens died (price -90% or liquidity < $1k) after >=30 min."""
    c = conn(); _init(c)
    rows = [dict(r) for r in c.execute("SELECT * FROM creators WHERE checked=0 AND ts<? LIMIT ?", (time.time() - min_age, n))]; c.close()
    if not rows: return 0
    mk = dex_market([r["mint"] for r in rows]); added = 0
    for r in rows:
        p = mk.get(r["mint"]); px = float((p or {}).get("priceUsd") or 0); liq = ((p or {}).get("liquidity") or {}).get("usd") or 0
        dead = (r["first_price"] and px < r["first_price"] * 0.1) or liq < 1000
        if dead: add_rugger(r["creator"], f"token {r['mint'][:8]} died (px {px:.3g} vs {r['first_price']:.3g}, liq ${liq:,.0f})"); added += 1
        c = conn(); c.execute("UPDATE creators SET checked=1 WHERE mint=?", (r["mint"],)); c.commit(); c.close()
    return added
def funder(w):
    """Who sent the first SOL to wallet w (None if wallet too old/busy for free RPC)."""
    sg = onchain.r("getSignaturesForAddress", [w, {"limit": 1000}]) or []
    if not sg or len(sg) == 1000: return None
    t = onchain.tx(sg[-1]["signature"])
    for i in t["transaction"]["message"]["instructions"]:
        p = i.get("parsed")
        if isinstance(p, dict) and p.get("type") == "transfer" and p["info"].get("destination") == w: return p["info"]["source"]
    return None
def holder_cluster(owners, budget=25):
    """Top holders (ex-AMM) funded by the same wallet -> fail. Budget-limited; returns (status, detail)."""
    t0, f, checked, fresh = time.time(), {}, 0, 0
    for w in owners[:6]:
        if time.time() - t0 > budget: break
        try:
            sg = onchain.r("getSignaturesForAddress", [w, {"limit": 1000}]) or []; checked += 1
            if len(sg) < 20: fresh += 1  # v3 #23: brand-new wallet
            src = funder(w) if 0 < len(sg) < 1000 else None
        except Exception: continue
        if src: f.setdefault(src, []).append(w)
    if fresh >= 4: return "fail", f"{fresh}/{checked} top holders are fresh wallets (<20 txs)"
    if checked == 0: return "unknown", "no holder funding readable on free RPC"
    top = max(f.items(), key=lambda kv: len(kv[1]), default=(None, []))
    d = f"checked {checked}/{min(len(owners),6)} top holders, max {len(top[1])} share funder {str(top[0])[:8]}"
    return ("fail" if len(top[1]) >= CFG["CLUSTER_MIN"] else "pass"), d
def dev_balance(creator, mint):
    """Creator's current token balance (raw float) via public RPC; None if unknown."""
    try:
        res = onchain.r("getTokenAccountsByOwner", [creator, {"mint": mint}, {"encoding": "jsonParsed"}])["value"]
        return sum(float(a["account"]["data"]["parsed"]["info"]["tokenAmount"]["uiAmount"] or 0) for a in res)
    except Exception: return None
def dev_sold(before, now, tol=0.02):
    return before is not None and now is not None and before > 0 and now < before * (1 - tol)

def dupe_links(mint, links):
    """v3: same X/Telegram/site link already used by a different token -> return that mint."""
    c = conn(); c.execute("CREATE TABLE IF NOT EXISTS links(url TEXT, mint TEXT, PRIMARY KEY(url, mint))"); hit = ""
    for u in links:
        u2 = u.lower().rstrip("/").replace("https://", "").replace("http://", "").replace("www.", "").replace("twitter.com", "x.com")
        if u2 in ("x.com", "t.me", "") or "/status/" in u2 or "/search" in u2: continue  # skip generic links
        r = c.execute("SELECT mint FROM links WHERE url=? AND mint!=?", (u2, mint)).fetchone()
        if r: hit = r["mint"]
        c.execute("INSERT OR IGNORE INTO links VALUES(?,?)", (u2, mint))
    c.commit(); c.close(); return hit
