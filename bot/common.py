"""Shared HTTP helper + config. PAPER ONLY: no wallet, no keys, no signing anywhere."""
import json, time, urllib.request, urllib.error
CFG = dict(VERSION="v3", START_BALANCE=300.0, MAX_PCT_PER_TRADE=0.10, STOP_PCT=0.08, TRAIL_ACTIVATE=0.15, TRAIL_PCT=0.08,
           MIN_VOL_H1=28_000, MAX_TOP10=25.0, MIN_SCORE=0.55, SCAN_SEC=30, POS_SEC=1,
           RECHECK_MIN=10, MAX_CHECKS=3, RPC="https://api.mainnet-beta.solana.com",
           MIN_LIQ=18_000, ENTRY_DELAY=90, MAX_PUMP=0.10, MAX_DUMP=-0.05, SLIP=0.01, FEE=0.003, CLUSTER_MIN=3, MAX_PER_HOUR=4, AB_SCORE=0.7)
UA = {"User-Agent": "night-desk-paper/1.0", "Accept": "application/json", "Content-Type": "application/json"}
HEALTH = {}  # host -> dict(ok, err, ms_avg, last_err)
def _h(url, ok, ms):
    from urllib.parse import urlparse
    h = HEALTH.setdefault(urlparse(url).netloc, dict(ok=0, err=0, ms=0.0, last_ok=0))
    if ok: h["ok"] += 1; h["ms"] = round(h["ms"] * 0.9 + ms * 0.1 if h["ms"] else ms); h["last_ok"] = round(time.time())
    else: h["err"] += 1
import socket; socket.setdefaulttimeout(20)  # 183 hard cap on every socket
# ---------- 491-505 per-host rate limiting, 429 backoff, TTL cache, stale fallback ----------
import threading as _th
_RL = {"api.geckoterminal.com": 2.2, "api.dexscreener.com": 0.25, "api.rugcheck.xyz": 0.5}  # 491 min seconds between calls per host (GT free tier ~30/min)
_TTL = (("/new_pools", 45), ("/trending_pools", 150), ("sort=h24_volume", 150), ("/info", 900), ("/token_price/", 20), ("token-boosts", 60), ("token-profiles", 60))  # 494/495
_RLK = _th.Lock(); _NEXT = {}; _COOL = {}; _CACHE = {}; NET = dict(cache_hit=0, stale_served=0, cooled_skip=0, r429=0, throttled_ms=0)
def _host(url): return url.split("/")[2] if "://" in url else url
def _ttl(url):
    for k, t in _TTL:
        if k in url: return t
    return 0
class Cooling(Exception): pass
def http_json(url, body=None, timeout=12, retries=1):
    """492/493/496/497: cache GET hits, honour a per-host cooldown after 429 (10s doubling to 300s, reset on success),
    space calls per host, and serve the last good response (<=15 min old) instead of failing while cooling."""
    h = _host(url); ttl = _ttl(url) if body is None else 0; now = time.time()
    if ttl:
        hit = _CACHE.get(url)
        if hit and now - hit[0] < ttl: NET["cache_hit"] += 1; return hit[1]
    cool = _COOL.get(h)
    if cool and now < cool[0]:
        hit = _CACHE.get(url)
        if hit and now - hit[0] < 900: NET["stale_served"] += 1; return hit[1]
        NET["cooled_skip"] += 1; raise Cooling(f"{h} cooling {cool[0]-now:.0f}s after 429")
    gap = _RL.get(h)
    if gap and "pos_loop" in _th.current_thread().name and "dexscreener" in h: gap = 0  # 537 open-position prices skip the queue (exits never wait behind scans)
    if gap:
        with _RLK: wait = max(0.0, _NEXT.get(h, 0) - now); _NEXT[h] = max(now, _NEXT.get(h, 0)) + gap
        if wait > 20: NET["cooled_skip"] += 1; _NEXT[h] -= gap; raise Cooling(f"{h} queue {wait:.0f}s")  # 498 never block a thread >20s
        if wait: NET["throttled_ms"] += int(wait * 1000); time.sleep(wait)
    try: r = _http_json_t(url, body, timeout, 0 if gap else retries)
    except urllib.error.HTTPError as e:
        if e.code == 429:
            NET["r429"] += 1; prev = (_COOL.get(h) or (0, 5))[1]; d = min(20 if 'dexscreener' in h else 300, prev * 2); _COOL[h] = (time.time() + d, d)  # 499 DexScreener cooldown capped at 20s (exits need prices)
            hit = _CACHE.get(url)
            if hit and time.time() - hit[0] < 900: NET["stale_served"] += 1; return hit[1]
        raise
    _COOL.pop(h, None)
    if ttl:
        _CACHE[url] = (time.time(), r)
        if len(_CACHE) > 3000: [_CACHE.pop(k, None) for k in list(_CACHE)[:800]]
    return r
def net_status(): return dict(NET, cooling={k: round(v[0] - time.time()) for k, v in _COOL.items() if v[0] > time.time()})  # 505
def _http_json_t(url, body=None, timeout=12, retries=1):
    timeout = min(timeout, 15); t0 = time.time()
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
RPCS = [CFG["RPC"], "https://solana-rpc.publicnode.com"]  # 123 backup free RPC failover
RPC_COOL = {}  # (endpoint, method) -> (until, strikes). 2026-10-30: publicnode answers 403 "Request blocked" to getTokenAccountsByOwner
def rpc(method, params):
    """Failover across free RPCs. 403/429 on an endpoint+method -> that pair cools off (2, 4, 8 .. 30 min) instead of being retried every minute."""
    err = None; now = time.time()
    for u in list(RPCS):
        until, k = RPC_COOL.get((u, method), (0, 0))
        if now < until: continue
        try:
            r = http_json(u, {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout=20 if u == RPCS[0] else 15)
            if "error" in r and ("blocked" in str(r["error"]).lower() or (r["error"] or {}).get("code") == -32052):
                RPC_COOL[(u, method)] = (now + min(1800, 120 * 2 ** k), k + 1); err = RuntimeError(r["error"]); continue
            if "error" in r and (r["error"] or {}).get("code") in (429, -32005, -32429): RPC_COOL[(u, method)] = (now + min(1800, 120 * 2 ** k), k + 1); err = RuntimeError(r["error"]); continue
            if "error" in r: raise RuntimeError(r["error"])
            RPC_COOL.pop((u, method), None)
            if u != RPCS[0]: RPCS.remove(u); RPCS.insert(0, u)  # promote the healthy endpoint
            return r["result"]
        except RuntimeError: raise
        except Exception as e:
            if getattr(e, "code", None) in (403, 429): RPC_COOL[(u, method)] = (now + min(1800, 120 * 2 ** k), k + 1)
            err = e
    raise err or RuntimeError(f"all RPCs cooling off for {method}")
_DC = {}
def dex_market(mints):
    """DexScreener batch (<=30 mints) -> {mint: best-liquidity solana pair}"""
    out = {}
    for i in range(0, len(mints), 30):
        chunk = mints[i:i+30]
        key = ",".join(sorted(chunk)); hit = _DC.get(key)
        if hit and time.time() - hit[0] < 0.8: pairs = hit[1]  # 140 de-dupe identical calls across threads
        else:
            try: pairs = http_json("https://api.dexscreener.com/tokens/v1/solana/" + ",".join(chunk)) or []; _DC[key] = (time.time(), pairs)
            except Exception: continue
            if len(_DC) > 500: _DC.clear()
        _t = _DC.get(key, (time.time(),))[0]  # b17 stale-data breaker: when this price data was fetched
        for p in pairs:
            if isinstance(p, dict): p["_ts"] = _t
        for p in pairs:
            m = p.get("baseToken", {}).get("address")
            if m not in chunk: continue
            if m not in out or (p.get("liquidity") or {}).get("usd", 0) > (out[m].get("liquidity") or {}).get("usd", 0):
                out[m] = p
    return out
