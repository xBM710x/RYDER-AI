"""Stage 2: Filter. FAIL CLOSED: any check that cannot be established -> 'unknown' -> kill.
VERIFIED (on-chain via Solana RPC): mint authority, freeze authority.
SOURCED (RugCheck/DexScreener data, not independently verified): LP locked/burned, top-10 %, 1h volume.
APPROXIMATED (heuristics on RugCheck data): dev past rugs, bundled launch."""
from common import http_json, rpc, CFG
import onchain, detect, extras, more
AMM_TYPES = {"AMM", "LOCKER"}  # RugCheck knownAccounts types excluded from holder concentration
def check(mint, pair):
    res = {}  # name -> (status pass/fail/unknown, detail, provenance)
    vol = ((pair or {}).get("volume") or {}).get("h1")
    res["volume_1h"] = ("unknown", "no DexScreener pair", "dexscreener") if vol is None else \
        (("pass" if vol >= CFG["MIN_VOL_H1"] else "fail"), f"${vol:,.0f}", "dexscreener")
    if CFG["VERSION"] not in ("v1", "v2"):
        liq = ((pair or {}).get("liquidity") or {}).get("usd")
        res["liquidity"] = ("unknown", "no liquidity data", "dexscreener") if liq is None else (("pass" if liq >= CFG["MIN_LIQ"] else "fail"), f"${liq:,.0f}", "dexscreener")
    if CFG["VERSION"] not in ("v1", "v2") and pair:
        tx = pair.get("txns") or {}; m5, h1 = tx.get("m5") or {}, tx.get("h1") or {}
        b5, s5, bh, sh = m5.get("buys", 0), m5.get("sells", 0), h1.get("buys", 0), h1.get("sells", 0)
        res["pressure"] = ("fail" if s5 > b5 or sh > bh * 1.2 else "pass", f"5m {b5}b/{s5}s, 1h {bh}b/{sh}s", "dexscreener")
        info = pair.get("info") or {}; soc = {(s.get("type") or "").lower(): s.get("url", "") for s in info.get("socials") or []}
        links = [u for u in [soc.get("twitter") or soc.get("x"), soc.get("telegram")] + [w.get("url") for w in info.get("websites") or []] if u]
        if not (soc.get("twitter") or soc.get("x") or soc.get("telegram")): res["socials"] = ("fail", "no X/Telegram listed", "dexscreener")
        else:
            dupe = detect.dupe_links(pair["baseToken"]["address"], links)
            res["socials"] = ("fail", "links reused by other token " + dupe[:8], "dexscreener") if dupe else ("pass", f"{len(links)} links, unique", "dexscreener")
    if any(v[0] != "pass" for v in res.values()): return res  # cheap check first; saves RPC/RugCheck rate limit
    try:
        info = rpc("getAccountInfo", [mint, {"encoding": "jsonParsed"}])["value"]["data"]["parsed"]["info"]
        res["mint_authority"] = ("pass" if info.get("mintAuthority") is None else "fail", str(info.get("mintAuthority")), "rpc-verified")
        res["freeze_authority"] = ("pass" if info.get("freezeAuthority") is None else "fail", str(info.get("freezeAuthority")), "rpc-verified")
    except Exception as e:
        res["mint_authority"] = res["freeze_authority"] = ("unknown", f"rpc error {e}", "rpc")
    if "fail" in [res[k][0] for k in ("mint_authority", "freeze_authority")]: return res
    try: rc = http_json(f"https://api.rugcheck.xyz/v1/tokens/{mint}/report", timeout=25)
    except Exception as e: rc = None; err = str(e)
    if not rc:
        for k in ("lp_locked", "top10", "dev_rugs", "bundled"): res[k] = ("unknown", "rugcheck unavailable", "rugcheck")
        return res
    # LP
    mk = rc.get("markets") or []
    if mk:
        best = max(mk, key=lambda m: (m.get("lp") or {}).get("quoteUSD") or 0)
        pct = (best.get("lp") or {}).get("lpLockedPct"); mtype = best.get("marketType", "")
        if "pump" in mtype and "amm" not in mtype or "dbc" in mtype or "launchlab" in mtype:
            res["lp_locked"] = ("pass", f"bonding curve ({mtype}) - no withdrawable LP", "rugcheck-approx")
        elif pct is None: res["lp_locked"] = ("unknown", f"no lpLockedPct ({mtype})", "rugcheck")
        else: res["lp_locked"] = ("pass" if pct >= 95 else "fail", f"{pct:.1f}% locked/burned ({mtype})", "rugcheck")
    else: res["lp_locked"] = ("unknown", "no markets in rugcheck", "rugcheck")
    # top10 excluding pools/lockers
    known = rc.get("knownAccounts") or {}
    th = [h for h in (rc.get("topHolders") or []) if (known.get(h.get("owner")) or known.get(h.get("address")) or {}).get("type") not in AMM_TYPES]
    if th: s = sum(h.get("pct", 0) for h in th[:10]); res["top10"] = ("pass" if s <= CFG["MAX_TOP10"] else "fail", f"{s:.1f}% (ex-AMM)", "rugcheck")
    else: res["top10"] = ("unknown", "no holder data", "rugcheck")
    # dev past rugs (approx): rugged flag, creator's other tokens, risk names
    risks = [r.get("name", "") for r in rc.get("risks") or []]
    bad = [r for r in risks if any(w in r.lower() for w in ("rug", "creator history", "previous"))]
    if rc.get("rugged"): res["dev_rugs"] = ("fail", "token flagged rugged", "rugcheck-approx")
    elif bad: res["dev_rugs"] = ("fail", "; ".join(bad), "rugcheck-approx")
    elif rc.get("creator"): res["dev_rugs"] = ("pass", f"no rug flags for creator ({len(rc.get('creatorTokens') or [])} other tokens)", "rugcheck-approx")
    else: res["dev_rugs"] = ("unknown", "no creator", "rugcheck")
    # bundled (approx): insider networks holding meaningful supply
    supply = ((rc.get("token") or {}).get("supply")) or 0
    nets = rc.get("insiderNetworks") or []
    held = sum(n.get("currentHolding") or 0 for n in nets) / supply * 100 if supply else 0
    bund = [r for r in risks if "bundle" in r.lower() or "insider" in r.lower()]
    if held > 10 or bund: res["bundled"] = ("fail", f"insiders hold {held:.1f}%; {bund}", "rugcheck-approx")
    else: res["bundled"] = ("pass", f"insiders hold {held:.1f}%, {rc.get('graphInsidersDetected') or 0} insider wallets", "rugcheck-approx")
    if CFG["VERSION"] not in ("v1", "v2"):
        mut = [r for r in risks if "mutable" in r.lower()]
        if mut or (rc.get("tokenMeta") or {}).get("mutable"): res["mutable_meta"] = ("fail", "metadata is mutable", "rugcheck"); return res
        fee = ((rc.get("transferFee") or {}).get("pct")) or 0
        if fee > 0: res["honeypot"] = ("fail", f"transfer tax {fee}%", "rugcheck"); return res
        sym = ((pair or {}).get("baseToken") or {}).get("symbol"); dup = extras.copycat(sym, mint, ((pair or {}).get("liquidity") or {}).get("usd"))
        if dup: res["copycat"] = ("fail", f"${sym} already exists with more liquidity ({dup[:8]})", "names-db"); return res
        pk = more.precheck(mint, pair, rc)
        if pk: res[pk[0]] = ("fail", pk[1], "v3-precheck"); return res
        hn, hr = extras.holder_rate(rc, pair); res["_holders"] = ("pass", f"{hn}|{hr}", "meta")
        extras.save_holders(mint, [h.get("owner") for h in th])
    cr = rc.get("creator"); res["_creator"] = ("pass", cr or "", "meta"); detect.remember_creator(mint, cr, pair)
    if CFG["VERSION"] not in ("v1", "v2"):
        bad_w, why = detect.is_rugger(cr)
        if bad_w: res["dev_rugs"] = ("fail", "creator on known-rug list: " + why, "rug-list"); return res
    # v2: on-chain dev history + bundle detection, only for tokens that passed everything else (saves RPC budget)
    if CFG["VERSION"] != "v1" and all(v[0] == "pass" for v in res.values()):
        cr = rc.get("creator")
        try: st, dt = onchain.dev_history(cr, mint) if cr else ("unknown", "no creator")
        except Exception as e: st, dt = "unknown", f"rpc error {e}"
        if st == "unknown": res["dev_rugs"] = (res["dev_rugs"][0], res["dev_rugs"][1] + f" | on-chain unknown: {dt}", "rugcheck-approx-fallback")
        else: res["dev_rugs"] = (st, dt, "rpc-onchain")
        if res["dev_rugs"][0] == "pass":
            try: st, dt = onchain.bundle_check(mint, cr)
            except Exception as e: st, dt = "unknown", f"rpc error {e}"
            if st == "unknown": res["bundled"] = (res["bundled"][0], res["bundled"][1] + f" | on-chain unknown: {dt}", "rugcheck-approx-fallback")
            else: res["bundled"] = (st, dt, "rpc-onchain")
        if res["dev_rugs"][0] == "fail" and res["dev_rugs"][2] == "rpc-onchain": detect.add_rugger(cr, "serial launcher: " + res["dev_rugs"][1][:80])
    # v3: top-holder funding cluster (only for survivors; budget-limited public RPC)
    if CFG["VERSION"] not in ("v1", "v2") and all(v[0] == "pass" for v in res.values()):
        owners = [h.get("owner") for h in th if h.get("owner") and h.get("owner") != cr]
        try: st, dt = detect.holder_cluster(owners)
        except Exception as e: st, dt = "unknown", f"rpc error {e}"
        res["holder_cluster"] = (st, dt, "rpc-onchain") if st != "unknown" else ("pass", dt + " (skipped, not counted)", "unverified")
        if res["holder_cluster"][0] == "pass":
            try: st, dt = extras.sell_sim(mint)
            except Exception as e: st, dt = "unknown", f"jupiter quote error {str(e)[:60]}"
            res["honeypot"] = (st, dt, "jupiter-quote") if st != "unknown" else ("fail", dt + " (no sell route = possible honeypot)", "jupiter-quote")
    if CFG["VERSION"] not in ("v1", "v2") and all(v[0] == "pass" for v in res.values()) and pair:
        try: st, dt = onchain.wash_check(pair["pairAddress"])
        except Exception as e: st, dt = "unknown", f"rpc error {e}"
        res["wash"] = (st, dt, "rpc-onchain") if st != "unknown" else ("pass", dt + " (skipped, not counted)", "unverified")
    return res
def verdict(res):
    for k, (s, d, p) in res.items():
        if k.startswith("_"): continue
        if s != "pass": return False, f"{k}:{s} ({d})"
    return True, "all passed"
