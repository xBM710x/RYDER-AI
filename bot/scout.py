"""Stage 1: Scout. New Solana pairs from GeckoTerminal new_pools + DexScreener latest token profiles/boosts."""
import time
from common import http_json, CFG
from logger import conn
import feed
DEX_TAG = {"pump-fun": "pumpfun", "pumpswap": "pumpswap", "pumpfun": "pumpfun", "raydium": "raydium", "raydium-clmm": "raydium",
           "raydium-launchlab": "letsbonk/launchlab", "meteora": "meteora", "meteora-dbc": "meteora", "meteora-damm-v2": "meteora", "orca": "orca"}
def tag(dex, mint=""):
    t = DEX_TAG.get(dex, dex or "unknown")
    if mint.endswith("bonk"): t += "(bonk)"
    if mint.endswith("pump") and "pump" not in t: t += "(pump-origin)"
    return t
_LP = [0.0]
BOOSTED = {}
def boost_bump(m): return 0.03 if time.time() - BOOSTED.get(m, 0) < 3600 else 0.0
def scout():
    cands = {}
    poll = time.time() - _LP[0] >= CFG["SCAN_SEC"]  # REST polling at most every SCAN_SEC; websocket coins handled instantly
    if poll: _LP[0] = time.time()
    for page in ((1, 2) if poll else ()):
        try:
            for p in http_json(f"https://api.geckoterminal.com/api/v2/networks/solana/new_pools?page={page}").get("data", []):
                m = p["relationships"]["base_token"]["data"]["id"].replace("solana_", "")
                if m == "So11111111111111111111111111111111111111112": continue
                cands.setdefault(m, dict(mint=m, name=p["attributes"]["name"], source="geckoterminal",
                                         dex=tag(p["relationships"]["dex"]["data"]["id"], m)))
        except Exception as e: print("scout gecko err", e)
    for url in (("https://api.dexscreener.com/token-profiles/latest/v1", "https://api.dexscreener.com/token-boosts/latest/v1", "https://api.dexscreener.com/token-boosts/top/v1") if poll else ()):
        try:
            for t in http_json(url) or []:
                if t.get("chainId") == "solana":
                    if "boosts" in url: BOOSTED[t["tokenAddress"]] = time.time()  # boosted/trending -> small score bump later (safety checks unchanged)
                    cands.setdefault(t["tokenAddress"], dict(mint=t["tokenAddress"], name="", source="dexscreener-boost" if "boosts" in url else "dexscreener", dex=tag("", t["tokenAddress"])))
        except Exception as e: print("scout dexs err", e)
    import wallet_watch
    while wallet_watch.QUEUE: t = wallet_watch.QUEUE.pop(0); t["dex"] = tag("", t["mint"]); cands[t["mint"]] = t  # Fomo-wallet buy signals
    for t in feed.drain():
        cands.setdefault(t["mint"], t)  # v3 live websocket launches
        if t.get("source") == "pumpportal-migration": __import__("brain8").migration_recheck(t["mint"])  # 377
    if poll:
        for t in __import__("brain8").discover(): cands.setdefault(t["mint"], t)  # 374/375
    for m in __import__("brain8").due_migrations(): cands.setdefault(m, dict(mint=m, name="", source="pumpportal-migration-recheck", dex="pumpswap", grad=True, recheck=True))
    for m, v in __import__("brain8").due_second(): cands.setdefault(m, dict(mint=m, name="", source="second-chance", dex="unknown", recheck=True, v0=v))
    # handoff: only tokens never finalized and due for (re)check
    c = conn(); now = time.time(); out = []
    for m, d in cands.items():
        r = c.execute("SELECT * FROM seen WHERE mint=?", (m,)).fetchone()
        if r is None:
            c.execute("INSERT INTO seen VALUES(?,?,?,0,0)", (m, now, 0)); out.append(d)
        elif d.get("source") == "fomo-wallet" and not r["done"]:
            c.execute("UPDATE seen SET checks=0 WHERE mint=?", (m,)); out.append(d)
        elif d.get("source") == "pumpportal-migration" and r["checks"] <= CFG["MAX_CHECKS"] and __import__("brain2").graduated(m):  # 121 re-check graduates of watched launches
            c.execute("UPDATE seen SET done=0 WHERE mint=?", (m,)); d["grad"] = True; out.append(d)
        elif d.get("recheck") and r["checks"] < 6:  # 372/377
            c.execute("UPDATE seen SET done=0 WHERE mint=?", (m,)); out.append(d)
        elif not r["done"] and r["checks"] < 5 and now - r["last_ts"] > CFG["RECHECK_MIN"] * 60:
            out.append(d)
    c.commit(); c.close()
    out.sort(key=lambda d: -__import__('brain2').source_score(d))  # 122 freshest/best source first
    out = __import__('brain8').order(out) if any(d.get("vol") for d in out) else out  # 376
    return out, len(cands)
