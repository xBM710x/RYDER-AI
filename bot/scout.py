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
def scout():
    cands = {}
    for page in (1, 2):
        try:
            for p in http_json(f"https://api.geckoterminal.com/api/v2/networks/solana/new_pools?page={page}").get("data", []):
                m = p["relationships"]["base_token"]["data"]["id"].replace("solana_", "")
                if m == "So11111111111111111111111111111111111111112": continue
                cands.setdefault(m, dict(mint=m, name=p["attributes"]["name"], source="geckoterminal",
                                         dex=tag(p["relationships"]["dex"]["data"]["id"], m)))
        except Exception as e: print("scout gecko err", e)
    for url in ("https://api.dexscreener.com/token-profiles/latest/v1", "https://api.dexscreener.com/token-boosts/latest/v1"):
        try:
            for t in http_json(url) or []:
                if t.get("chainId") == "solana":
                    cands.setdefault(t["tokenAddress"], dict(mint=t["tokenAddress"], name="", source="dexscreener", dex=tag("", t["tokenAddress"])))
        except Exception as e: print("scout dexs err", e)
    for t in feed.drain(): cands.setdefault(t["mint"], t)  # v3 live websocket launches
    # handoff: only tokens never finalized and due for (re)check
    c = conn(); now = time.time(); out = []
    for m, d in cands.items():
        r = c.execute("SELECT * FROM seen WHERE mint=?", (m,)).fetchone()
        if r is None:
            c.execute("INSERT INTO seen VALUES(?,?,?,0,0)", (m, now, 0)); out.append(d)
        elif not r["done"] and r["checks"] < CFG["MAX_CHECKS"] and now - r["last_ts"] > CFG["RECHECK_MIN"] * 60:
            out.append(d)
    c.commit(); c.close()
    return out, len(cands)
