"""Shared HTTP helper + config. PAPER ONLY: no wallet, no keys, no signing anywhere."""
import json, time, urllib.request, urllib.error
CFG = dict(VERSION="v3", START_BALANCE=300.0, MAX_PCT_PER_TRADE=0.10, STOP_PCT=0.08, TRAIL_ACTIVATE=0.15, TRAIL_PCT=0.08,
           MIN_VOL_H1=40_000, MAX_TOP10=25.0, MIN_SCORE=0.6, SCAN_SEC=30, POS_SEC=1,
           RECHECK_MIN=10, MAX_CHECKS=3, RPC="https://api.mainnet-beta.solana.com",
           MIN_LIQ=25_000, ENTRY_DELAY=90, MAX_PUMP=0.10, MAX_DUMP=-0.05, SLIP=0.01, FEE=0.003, CLUSTER_MIN=3, MAX_PER_HOUR=4, AB_SCORE=0.7)
UA = {"User-Agent": "night-desk-paper/1.0", "Accept": "application/json", "Content-Type": "application/json"}
HEALTH = {}  # host -> dict(ok, err, ms_avg, last_err)
def _h(url, ok, ms):
    from urllib.parse import urlparse
    h = HEALTH.setdefault(urlparse(url).netloc, dict(ok=0, err=0, ms=0.0, last_ok=0))
    if ok: h["ok"] += 1; h["ms"] = round(h["ms"] * 0.9 + ms * 0.1 if h["ms"] else ms); h["last_ok"] = round(time.time())
    else: h["err"] += 1
def http_json(url, body=None, timeout=12, retries=1):
    t0 = time.time()
    try: r = _http_json(url, body, timeout, retries); _h(url, True, (time.time() - t0) * 1000); return r
    except Exception: _h(url, False, 0); raise
def _http_json(url, body=None, timeout=12, retries=1):
    for i in range(retries + 1):
        try:
            data = json.dumps(body).encode() if body is not None else None
            req = urllib.request.Request(url, data=data, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 429 and i < retries: time.sleep(3 * (i + 1)); continue
            if i == retries: raise
        except Exception:
            if i == retries: raise
            time.sleep(1.5)
def rpc(method, params):
    r = http_json(CFG["RPC"], {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout=30)
    if "error" in r: raise RuntimeError(r["error"])
    return r["result"]
def dex_market(mints):
    """DexScreener batch (<=30 mints) -> {mint: best-liquidity solana pair}"""
    out = {}
    for i in range(0, len(mints), 30):
        chunk = mints[i:i+30]
        try: pairs = http_json("https://api.dexscreener.com/tokens/v1/solana/" + ",".join(chunk)) or []
        except Exception: continue
        for p in pairs:
            m = p.get("baseToken", {}).get("address")
            if m not in chunk: continue
            if m not in out or (p.get("liquidity") or {}).get("usd", 0) > (out[m].get("liquidity") or {}).get("usd", 0):
                out[m] = p
    return out
