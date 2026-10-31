"""READ-ONLY watch of Braydon's PUBLIC Fomo wallet (public RPC). No keys, no signing, no transactions - ever.
New buys -> Telegram note with RYDER's paper read + coin handed to Scout as a signal (all safety checks still apply)."""
import json, os, time
from common import rpc
WALLET = "19rLqxcgPCcbVEVhVEUB5d8G5WD13kUnirywGq3FCVc"
PROGS = ("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA", "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb")
SKIP = {"Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", "So11111111111111111111111111111111111111112"}
P = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wallet_watch_state.json"); QUEUE = []
def balances():
    out = {}
    for pg in PROGS:
        r = rpc("getTokenAccountsByOwner", [WALLET, {"programId": pg}, {"encoding": "jsonParsed"}]) or {}
        for a in r.get("value", []):
            i = a["account"]["data"]["parsed"]["info"]; amt = float(i["tokenAmount"]["uiAmount"] or 0)
            if i["mint"] not in SKIP: out[i["mint"]] = out.get(i["mint"], 0) + amt
    return out
def tick():
    import alerts, brain3
    from common import dex_market
    try: st = json.load(open(P))
    except Exception: st = {}
    old = st.get("bal"); new = balances()
    try:
        sg = rpc("getSignaturesForAddress", [WALLET, {"limit": 5}]) or []; st["last_sig_time"] = max([s.get("blockTime") or 0 for s in sg] or [0])
    except Exception: pass
    held = [m for m, a in new.items() if a > 0]
    mk = dex_market(held) if held else {}
    val = sorted(((new[m] * float((mk.get(m) or {}).get("priceUsd") or 0), m) for m in held), reverse=True)
    for usd, m in [x for x in val if x[0] >= 5][:15]:  # feed existing holdings watch: top 15 positions worth >= $5
        sym = ((mk.get(m) or {}).get("baseToken") or {}).get("symbol")
        if sym and m not in brain3.HOLD.values(): brain3.HOLD[sym] = m
    st["top"] = [dict(sym=((mk.get(m) or {}).get("baseToken") or {}).get("symbol"), usd=round(u, 2)) for u, m in val[:15]]
    if old is not None:
        for m, a in new.items():
            b = old.get(m, 0)
            if a > b * 1.01 and a > 0:
                sym = ((mk.get(m) or {}).get("baseToken") or {}).get("symbol") or m[:6]
                QUEUE.append(dict(mint=m, name=sym, source="fomo-wallet", dex="unknown"))
                try: __import__("brain14").note_fomo_buy(m, sym)  # hint: 45-min re-check watch (no trading from it)
                except Exception: pass
                try: read = brain3.lookup(m)
                except Exception as e: read = f"(RYDER read unavailable: {str(e)[:60]})"
                alerts.send_async(f"👛 Your Fomo wallet {'bought' if b == 0 else 'added to'} {sym}\nRYDER is checking it as a paper signal (all safety checks still apply).\n\n{read}")
            elif a < b * 0.99:
                sym = ((mk.get(m) or {}).get("baseToken") or {}).get("symbol") or m[:6]
                alerts.send_async(f"👛 Your Fomo wallet {'sold all' if a == 0 else 'trimmed'} {sym} ({b:,.0f} → {a:,.0f} tokens) · read-only watch")
    total = sum(u for u, m in val)
    try:
        sol = (rpc("getBalance", [WALLET]) or {}).get("value", 0) / 1e9; sp = float((dex_market(["So11111111111111111111111111111111111111112"]).get("So11111111111111111111111111111111111111112") or {}).get("priceUsd") or 0)
        if sol and sp: st["sol_usd"] = round(sol * sp, 2); total += sol * sp
    except Exception: pass
    st["total_usd"] = round(total, 2)
    st.update(bal=new, t=time.time()); json.dump(st, open(P, "w"))
