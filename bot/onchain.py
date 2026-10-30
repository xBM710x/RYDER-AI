"""v2 on-chain checks via public Solana RPC (no keys). Rate-limited, fail-closed with explicit 'unknown'."""
import time
from common import rpc, dex_market
_last = [0.0]
def r(method, params):
    dt = time.time() - _last[0]
    if dt < 0.25: time.sleep(0.25 - dt)  # <=4 req/s to public RPC
    _last[0] = time.time()
    for i in range(2):
        try: return rpc(method, params)
        except Exception:
            if i == 1: raise
            time.sleep(1.5)
def tx(sig):
    return r("getTransaction", [sig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}])
def mints_created_in(t):
    out = []
    if not t: return out
    ins = list(t["transaction"]["message"]["instructions"])
    for g in (t.get("meta") or {}).get("innerInstructions") or []: ins += g["instructions"]
    for i in ins:
        p = i.get("parsed")
        if isinstance(p, dict) and p.get("type") in ("initializeMint", "initializeMint2"): out.append(p["info"]["mint"])
    return out
def dev_history(creator, current_mint, max_tx=12, budget=30):
    """Returns (status, detail). Scans creator's recent txs for mints it created, then checks each on DexScreener."""
    sigs = r("getSignaturesForAddress", [creator, {"limit": 300}]) or []
    created, scanned, t0 = [], 0, time.time()
    for s in sigs:
        if scanned >= max_tx: break
        if time.time() - t0 > budget: return "unknown", f"RPC too slow (scanned {scanned} of {len(sigs)} creator txs in {budget}s)"
        if s.get("err"): continue
        scanned += 1
        try: created += [m for m in mints_created_in(tx(s["signature"])) if m != current_mint]
        except Exception: continue
    created = list(dict.fromkeys(created))
    note = f"{len(sigs)} creator txs, scanned {scanned}, prior mints {len(created)}"
    if not created: return "pass", note + " (no prior launches seen in scanned txs)"
    mk = dex_market(created[:30]); dead = []
    for m in created[:30]:
        p = mk.get(m)
        liq = ((p or {}).get("liquidity") or {}).get("usd") or 0; fdv = (p or {}).get("fdv") or 0
        if liq < 2000 and fdv < 15000: dead.append(m)
    note += f", collapsed {len(dead)}/{min(len(created),30)}"
    if len(created) >= 2 and len(dead) / min(len(created), 30) >= 0.75: return "fail", note + " (serial launcher, most prior tokens dead)"
    return "pass", note
def bundle_check(mint, creator=None, max_pages=3):
    """On-chain: walk signatures back to the launch, then inspect txs in the launch slot (+1).
    >=3 distinct non-creator signers landing in the same slot as the create = bundled (Jito-style).
    Also flags when >=2 of those wallets were funded by the same address in their first tx (sampled)."""
    before, page, n = None, [], 0
    for _ in range(max_pages):
        opts = {"limit": 1000}
        if before: opts["before"] = before
        pg = r("getSignaturesForAddress", [mint, opts]) or []
        if not pg: break
        page = pg; n += len(pg); before = pg[-1]["signature"]
        if len(pg) < 1000: break
    else:
        return "unknown", f">{max_pages*1000} txs since launch; launch window not reachable on free RPC"
    if not page: return "unknown", "no signatures"
    launch_slot = page[-1]["slot"]
    window = [s for s in page if s["slot"] <= launch_slot + 1 and not s.get("err")][-25:]
    signers = {}
    for s in window:
        try:
            t = tx(s["signature"])
            keys = t["transaction"]["message"]["accountKeys"]
            payer = keys[0]["pubkey"] if isinstance(keys[0], dict) else keys[0]
            signers.setdefault(payer, s["slot"])
        except Exception: continue
    others = [w for w in signers if w != creator]
    same = [w for w in others if signers[w] == launch_slot]
    # common funder sample: first-ever tx of up to 5 same-slot wallets, look at who sent them SOL
    funders = {}
    for w in same[:5]:
        try:
            sg = r("getSignaturesForAddress", [w, {"limit": 1000}]) or []
            if not sg or len(sg) == 1000: continue
            t = tx(sg[-1]["signature"])
            for i in t["transaction"]["message"]["instructions"]:
                p = i.get("parsed")
                if isinstance(p, dict) and p.get("type") == "transfer" and p["info"].get("destination") == w:
                    funders.setdefault(p["info"]["source"], []).append(w)
        except Exception: continue
    common = max((len(v) for v in funders.values()), default=0)
    detail = f"launch slot {launch_slot}: {len(same)} other wallets bought in launch slot, {len(others)} in slot+1 window, max wallets per common funder {common}"
    if len(same) >= 3 or common >= 2: return "fail", detail
    if len(others) >= 8: return "fail", detail + " (v3 sniper check: >=8 bot buys in first 2 slots)"
    return "pass", detail

def wash_check(pair_addr, n=100):
    """v3: sample last n txs on the pool; few distinct signers doing many txs = wash trading."""
    sg = [s for s in (r("getSignaturesForAddress", [pair_addr, {"limit": n}]) or []) if not s.get("err")][:40]
    if len(sg) < 15: return "unknown", f"only {len(sg)} recent pool txs"
    signers = {}
    for s in sg[:20]:
        try:
            t = tx(s["signature"]); k = t["transaction"]["message"]["accountKeys"][0]
            k = k["pubkey"] if isinstance(k, dict) else k; signers[k] = signers.get(k, 0) + 1
        except Exception: continue
    tot = sum(signers.values())
    if tot < 10: return "unknown", f"read {tot} txs"
    top = max(signers.values()); d = f"{len(signers)} distinct signers in {tot} recent txs, busiest wallet {top}"
    return ("fail" if len(signers) / tot < 0.35 or top / tot > 0.4 else "pass"), d
