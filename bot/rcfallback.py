"""Backup safety report, used ONLY when rugcheck.xyz cannot produce one (approved by Braydon 2026-10-30 22:51 PT). PAPER ONLY, read-only RPC.
Builds a rugcheck-shaped dict from on-chain reads so filters.check runs every downstream check unchanged, plus strict verdicts:
- lp: pump.fun bonding curve (PDA owned by the pump program, complete=0) = no withdrawable LP (same rule rugcheck path uses);
      PumpSwap pool (owner pAMM, base=mint, quote=SOL): locked = 1 - LP mint supply / pool.lp_supply, pass only >= 95% (CHIPCR/Qcatom-type 402 shortcut NOT used).
      Any other DEX -> unknown -> reject.
- holders: all token accounts via getProgramAccounts (owner+amount slice); pool / bonding-curve vaults tagged AMM.
- Token-2022: only metadataPointer/tokenMetadata extensions allowed; anything else -> reject. Metadata update authority set -> mutable -> reject.
- legacy SPL: Metaplex metadata is_mutable read on-chain; holders via the same RPC call (if blocked -> reject).
- creator from the bonding curve / pool; dev history, bundle and holder-cluster checks are REQUIRED to return pass (unknown -> reject) in filters."""
import time, base64
import fbchain as f
from common import rpc
PUMP = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"; PAMM = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"; SOL = "So11111111111111111111111111111111111111112"
T22 = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"; TOK = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"; MPL = "metaqbxxUerdq28cj1RbAWkYQm3ybzjb6a8bt518x1s"
OK_EXT = {"metadataPointer", "tokenMetadata"}
_C = {}; USED = {}  # mints whose safety report came from this backup (sized 0.5x by brain15)
def _holders(mint, prog):
    r = rpc("getProgramAccounts", [prog, {"encoding": "base64", "dataSlice": {"offset": 32, "length": 40}, "filters": ([{"dataSize": 165}] if prog == TOK else []) + [{"memcmp": {"offset": 0, "bytes": mint}}]}])
    out = {}
    for a in r:
        b = base64.b64decode(a["account"]["data"][0]); ow = f.b58e(b[:32]); amt = int.from_bytes(b[32:40], "little")
        if amt: out[ow] = out.get(ow, 0) + amt
    return out
def _mpl_mutable(mint):
    o_b = f.raw(f.pda([b"metadata", f.b58d(MPL), f.b58d(mint)], MPL))
    if not o_b or o_b[0] != MPL: return None
    b = o_b[1]; o = 1 + 32 + 32
    for _ in range(3): n = int.from_bytes(b[o:o + 4], "little"); o += 4 + n
    o += 2
    if b[o]: n = int.from_bytes(b[o + 1:o + 5], "little"); o += 1 + 4 + 34 * n
    else: o += 1
    o += 1  # primary_sale_happened
    return bool(b[o])
def vaults_bc(mint): return f.pda([b"bonding-curve", f.b58d(mint)], PUMP)
def report(mint, pair):
    """Returns (rc_like_dict, None) or (None, why). Cached 60s."""
    h = _C.get(mint)
    if h and time.time() - h[0] < 60: return h[1]
    out = _report(mint, pair); _C[mint] = (time.time(), out)
    if out[0]: USED[mint] = time.time()
    if len(_C) > 500: [_C.pop(k) for k in list(_C)[:100]]
    return out
def _report(mint, pair):
    mi = rpc("getAccountInfo", [mint, {"encoding": "jsonParsed"}])["value"]
    if not mi: return None, "mint not found"
    prog = mi["owner"]; info = mi["data"]["parsed"]["info"]; ext = {e["extension"]: e.get("state") for e in info.get("extensions") or []}
    rc = dict(_fallback=True, token=dict(supply=int(info["supply"]), mintAuthority=info.get("mintAuthority"), freezeAuthority=info.get("freezeAuthority")),
              token_extensions={k: True for k in ext}, risks=[], knownAccounts={}, markets=[])
    bad = [k for k in ext if k not in OK_EXT]
    if bad: rc["risks"].append(dict(name="Token-2022 extension not allowed: " + ",".join(bad)))
    if prog == T22:
        tm = ext.get("tokenMetadata")
        if tm is None: return None, "Token-2022 without inline metadata (cannot verify mutability)"
        rc["tokenMeta"] = dict(mutable=tm.get("updateAuthority") is not None, name=tm.get("name"), symbol=tm.get("symbol"))
        if (ext.get("metadataPointer") or {}).get("authority"): rc["tokenMeta"]["mutable"] = True
    elif prog == TOK:
        mu = _mpl_mutable(mint)
        if mu is None: return None, "no Metaplex metadata"
        rc["tokenMeta"] = dict(mutable=mu)
    else: return None, "unknown token program"
    if "transferFeeConfig" in ext: rc["transferFee"] = dict(pct=100)  # any fee config -> treated as taxed (strict)
    dex = (pair or {}).get("dexId"); pa = (pair or {}).get("pairAddress"); vaults = set(); creator = None
    if dex == "pumpfun":
        bc = f.pda([b"bonding-curve", f.b58d(mint)], PUMP); o_b = f.raw(bc)
        if not o_b or o_b[0] != PUMP or len(o_b[1]) < 81: return None, "pump.fun bonding curve not verified on-chain"
        b = o_b[1]; creator = f.pk(b, 49); vaults.add(bc)
        rc["_lp"] = ("pass", "pump.fun bonding curve (on-chain, not complete) - no withdrawable LP") if b[48] == 0 else ("unknown", "bonding curve complete; pool must be checked")
    elif dex == "pumpswap" and pa:
        o_b = f.raw(pa)
        if not o_b or o_b[0] != PAMM or len(o_b[1]) < 243: return None, "PumpSwap pool not verified on-chain"
        b = o_b[1]
        if f.pk(b, 43) != mint or f.pk(b, 75) != SOL: return None, "PumpSwap pool mints do not match"
        lp = f.pk(b, 107); orig = f.u64(b, 203); cur = int(rpc("getTokenSupply", [lp])["value"]["amount"])
        if not orig: return None, "pool lp_supply is 0"
        locked = max(0.0, 1 - cur / orig) * 100; creator = f.pk(b, 211); vaults.update([pa, f.pk(b, 139)])
        rc["_lp"] = ("pass" if locked >= 95 else "fail", f"{locked:.1f}% of LP burned (on-chain: supply {cur} of {orig})")
        rc["markets"] = [dict(marketType="pump_amm", lp=dict(lpLockedPct=locked))]
    else:
        rc["_lp"] = ("unknown", f"backup check supports pump.fun curve / PumpSwap only (dex {dex})")
    if rc["_lp"][0] == "pass":  # every OTHER pool holding >=10% of the coin's liquidity must also be verified -> it is not, so reject
        from common import http_json  # (NIO case: PumpSwap LP burned but a bigger unlocked Meteora pool; rugcheck failed it)
        ps = http_json("https://api.dexscreener.com/token-pairs/v1/solana/" + mint, timeout=8) or []
        tot = sum(float((p.get("liquidity") or {}).get("usd") or 0) for p in ps) or 1
        other = [p for p in ps if p.get("pairAddress") != pa and float((p.get("liquidity") or {}).get("usd") or 0) >= max(1000, 0.10 * tot)]
        if other: rc["_lp"] = ("unknown", f"another pool ({other[0].get('dexId')}, ${float((other[0].get('liquidity') or {}).get('usd') or 0):,.0f}) cannot be verified")
    hs = _holders(mint, prog); sup = rc["token"]["supply"]
    if not hs or not sup: return None, "holder list not readable"
    th = sorted(hs.items(), key=lambda x: -x[1])
    rc["topHolders"] = [dict(owner=o, address=o, pct=a / sup * 100) for o, a in th[:50]]
    for v in vaults: rc["knownAccounts"][v] = dict(type="AMM")
    rc["creator"] = creator; rc["_n_holders"] = rc["totalHolders"] = len(hs)
    return rc, None
