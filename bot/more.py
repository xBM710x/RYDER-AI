"""v3 upgrades 101-120 (PAPER ONLY, public read-only data)."""
import time, json, re, collections
from common import CFG, http_json, dex_market
from logger import conn, log
import extras
SCAM = re.compile(r"(listing soon|binance listing|presale|airdrop|giveaway|100x guaranteed|stealth launch)", re.I)
def _closed(ver=None):
    c = conn(); r = [dict(x) for x in c.execute("SELECT * FROM positions WHERE status='closed' AND version=? AND reason!='partial_tp'", (ver or CFG["VERSION"],))]; c.close(); return r
def _t(c): c.execute("CREATE TABLE IF NOT EXISTS rug_assets(kind TEXT, val TEXT, mint TEXT, PRIMARY KEY(kind,val))")
# 106 / 112 / 113 / 111: pre-trade kills
def precheck(mint, pair, rc):
    info = (pair or {}).get("info") or {}; bt = (pair or {}).get("baseToken") or {}
    txt = " ".join([bt.get("name") or "", bt.get("symbol") or ""] + [w.get("label") or "" for w in info.get("websites") or []])
    if SCAM.search(txt): return "listing_scam", f"scam wording: {SCAM.search(txt).group(0)}"
    c = conn(); _t(c)
    for kind, val in (("img", info.get("imageUrl")), ("name", (bt.get("name") or "").strip().lower())):
        if val:
            r = c.execute("SELECT mint FROM rug_assets WHERE kind=? AND val=? AND mint!=?", (kind, val, mint)).fetchone()
            if r: c.close(); return "reused_rug_asset", f"{kind} matches past rug {r['mint'][:8]}"
    c.close()
    ext = ((rc or {}).get("token_extensions") or {}) or {}
    bad = [k for k in ("transferHook", "permanentDelegate", "defaultAccountState") if ext.get(k)] + (["nonTransferable"] if ext.get("nonTransferable") is True else [])
    if bad:
        return "clone_contract", "Token-2022 risky extension: " + ",".join(bad)
    cr = (rc or {}).get("creator"); tot = sum(h.get("pct", 0) for h in (rc or {}).get("topHolders") or [] if h.get("owner") == cr)
    if cr and tot > 5: return "team_supply", f"dev holds {tot:.1f}% unlocked"
    return None
def remember_rug(mint, pair):
    info = (pair or {}).get("info") or {}; bt = (pair or {}).get("baseToken") or {}
    c = conn(); _t(c)
    for kind, val in (("img", info.get("imageUrl")), ("name", (bt.get("name") or "").strip().lower())):
        if val: c.execute("INSERT OR IGNORE INTO rug_assets VALUES(?,?,?)", (kind, val, mint))
    c.commit(); c.close()
# 102 good-dev whitelist
def good_dev(creator):
    if not creator: return False
    c = conn()
    try: ms = [r[0] for r in c.execute("SELECT mint FROM creators WHERE creator=?", (creator,))]
    except Exception: ms = []
    c.close()
    return any(p["mint"] in ms and p["pnl"] > 0 for p in _closed())
# 109 / 110: orderflow + liquidity change across the entry wait
def flow(p_old, pair):
    a = (p_old.get("tx5") or {}); b = ((pair.get("txns") or {}).get("m5") or {})
    db, ds = (b.get("buys") or 0) - (a.get("buys") or 0), (b.get("sells") or 0) - (a.get("sells") or 0)
    liq0, liq1 = p_old.get("liq0") or 0, (pair.get("liquidity") or {}).get("usd") or 0
    return dict(d_buys=db, d_sells=ds, imbalance="sell" if ds > db * 1.3 and ds >= 5 else "buy" if db > ds * 1.3 else "flat", liq_add=bool(liq0 and liq1 > liq0 * 1.1))
# 114/115/116/117/118: portfolio guards
def guards(narr):
    c = conn(); V = CFG["VERSION"]
    op = [dict(r) for r in c.execute("SELECT mint FROM positions WHERE status='open' AND version=?", (V,))]
    buys = {r["mint"]: json.loads(r["data"]) for r in c.execute("SELECT mint,data FROM events WHERE kind='paper_buy' AND version=?", (V,))}; c.close()
    if len(op) >= 3: return "max 3 concurrent holdings", 1
    if narr != "other" and any((buys.get(p["mint"]) or {}).get("narrative") == narr for p in op): return f"already holding a '{narr}' coin (correlation guard)", 1
    cl = sorted(_closed(), key=lambda p: p["closed"])
    last3 = cl[-3:]
    if len(last3) == 3 and all(p["pnl"] < 0 for p in last3) and last3[-1]["closed"] - last3[0]["closed"] < 1800 and time.time() - last3[-1]["closed"] < 3600:
        return "1h pause after 3 fast losses", 1
    ns = collections.defaultdict(lambda: [0, 0])
    for p in cl:
        n = (buys.get(p["mint"]) or {}).get("narrative") or "other"; ns[n][0] += 1; ns[n][1] += p["pnl"] > 0
    if narr in ns and ns[narr][0] >= 5 and ns[narr][1] <= 1: return f"narrative '{narr}' auto-blacklisted ({ns[narr][1]}/{ns[narr][0]} wins)", 1
    d0 = time.mktime(time.localtime()[:3] + (0, 0, 0, 0, 0, -1)); day = sum(p["pnl"] for p in cl if p["closed"] >= d0)
    return None, (0.5 if day > 0.10 * CFG["START_BALANCE"] else 1.0)  # 117 profit-protect
# 119 two-source price check
def price_ok(mint, dex_px):
    try:
        g = http_json(f"https://api.geckoterminal.com/api/v2/simple/networks/solana/token_price/{mint}", timeout=8)
        gp = float(((g.get("data") or {}).get("attributes") or {}).get("token_prices", {}).get(mint) or 0)
    except Exception: return True, "gecko unavailable (not counted)"
    if not gp: return True, "no gecko price (not counted)"
    dv = abs(gp / dex_px - 1)
    return dv <= 0.05, f"dexscreener vs gecko differ {dv*100:.1f}%"
# 107 rug-timing stats
def rug_timing():
    rs = [(p["closed"] - p["opened"]) / 60 for v in (CFG["VERSION"], CFG["VERSION"] + "b") for p in _closed(v) if p["reason"] in ("dev_sell", "lp_pull", "holder_concentration")]
    if not rs: return dict(n=0)
    rs.sort(); return dict(n=len(rs), median_min=round(rs[len(rs) // 2], 1), p90_min=round(rs[int(len(rs) * 0.9)], 1))
# 120 startup self-test
def selftest():
    out = {}
    for name, fn in (("dexscreener", lambda: dex_market(["So11111111111111111111111111111111111111112"])),
                     ("geckoterminal", lambda: http_json("https://api.geckoterminal.com/api/v2/networks/solana/new_pools?page=1")),
                     ("rugcheck", lambda: http_json("https://api.rugcheck.xyz/v1/stats/new_tokens", timeout=15)),
                     ("solana_rpc", lambda: __import__("common").rpc("getSlot", [])),
                     ("jupiter", lambda: http_json("https://lite-api.jup.ag/swap/v1/quote?inputMint=So11111111111111111111111111111111111111112&outputMint=J3ReuwckNtcJP1Zhn7wVbfXhTDNTkHxozQWWAwxWpump&amount=1000000", timeout=8))):
        t0 = time.time()
        try: fn(); out[name] = dict(ok=True, ms=round((time.time() - t0) * 1000))
        except Exception as e: out[name] = dict(ok=False, err=str(e)[:60])
    try: c = conn(); c.execute("SELECT 1"); c.close(); out["db"] = dict(ok=True)
    except Exception as e: out["db"] = dict(ok=False, err=str(e)[:60])
    log("selftest", **out); return out
