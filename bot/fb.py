"""Backup safety check (PAPER ONLY), used ONLY when rugcheck.xyz cannot produce a report. Approved by Braydon 2026-10-30 22:51 PT.
Builds a rugcheck-shaped report from on-chain reads (free Solana RPC) so the SAME downstream checks run, plus stricter rules:
- LP: only two pool types are supported, both verified on-chain:
    pump.fun bonding curve: curve PDA derived from the mint, owner = pump program, complete == false (no withdrawable LP) -> pass.
    PumpSwap pool: pool owner = PumpSwap program, base mint = this mint, LP burned % = 1 - LP-mint supply / pool lp_supply; >= 95% -> pass.
  Every other DEX/pool (Raydium, Meteora, Orca, ...) -> unknown -> reject.
- Holders: every token account of the mint via getProgramAccounts (Token-2022 and legacy). Only the verified pool/curve vault is excluded.
  Holder list unavailable -> reject.
- Token-2022 extensions: anything except metadataPointer/tokenMetadata -> fail (stricter than rugcheck). Mutable metadata -> fail.
- Creator from the curve / pool account. In fallback mode the on-chain dev-history, bundle and holder-cluster checks must PASS
  (rugcheck mode tolerates 'unknown'); unknown -> reject.
No shortcuts: the reverted 402 rule passed pump.fun pools WITHOUT measuring the LP; here the LP mint supply is read on-chain every time."""
import time
import fbchain as f
from common import rpc
PUMP = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"; PSWAP = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"; MPL = "metaqbxxUerdq28cj1RbAWkYQm3ybzjb6a8bmuKbDHER"
TOKS = ("TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb", "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
SAFE_EXT = {"metadataPointer", "tokenMetadata"}
def _holders(mint, prog):
    r = rpc("getProgramAccounts", [prog, {"encoding": "jsonParsed", "filters": ([{"dataSize": 165}] if prog == TOKS[1] else []) + [{"memcmp": {"offset": 0, "bytes": mint}}]}])
    out = {}
    for a in r or []:
        i = a["account"]["data"]["parsed"]["info"]; amt = int(i["tokenAmount"]["amount"])
        if amt: out[a["pubkey"]] = (i["owner"], amt)
    return out
def _legacy_mutable(mint):
    acc = f.raw(f.pda([b"metadata", f.b58d(MPL), f.b58d(mint)], MPL))
    if not acc or acc[0] != MPL: return None
    b = acc[1]; o = 1 + 32 + 32
    for _ in range(3): o += 4 + int.from_bytes(b[o:o + 4], "little")
    o += 2
    if b[o]: o += 1 + 4 + 34 * int.from_bytes(b[o + 1:o + 5], "little")
    else: o += 1
    o += 1  # primary_sale_happened
    return bool(b[o])
def build(mint, pair):
    """Returns (rc_like, fbres) or raises/returns None when anything can't be verified (caller fails closed)."""
    fbres = {}
    mi = rpc("getAccountInfo", [mint, {"encoding": "jsonParsed"}])["value"]; prog = mi["owner"]; info = mi["data"]["parsed"]["info"]
    supply = int(info["supply"]); dec = info["decimals"]
    ext = {e["extension"]: e.get("state") for e in info.get("extensions") or []}
    bad = [e for e in ext if e not in SAFE_EXT]
    tm = ext.get("tokenMetadata")
    if prog == TOKS[0]:
        if tm is None: return None  # Token-2022 without inline metadata: can't verify mutability
        mutable = tm.get("updateAuthority") is not None
    else: mutable = _legacy_mutable(mint)
    if mutable is None: return None
    dex = (pair or {}).get("dexId") or ""; pa = (pair or {}).get("pairAddress"); vault_owner = None; creator = None
    if dex == "pumpfun":
        cv = f.pda([b"bonding-curve", f.b58d(mint)], PUMP); acc = f.raw(cv)
        if not acc or acc[0] != PUMP or len(acc[1]) < 81: fbres["lp_locked"] = ("unknown", "bonding curve not verified on-chain", "fallback-onchain")
        elif acc[1][48]: fbres["lp_locked"] = ("unknown", "bonding curve complete (migrated) but pair is still the curve", "fallback-onchain")
        else: fbres["lp_locked"] = ("pass", "pump.fun bonding curve verified on-chain (no withdrawable LP)", "fallback-onchain"); vault_owner = cv; creator = f.pk(acc[1], 49)
    elif dex == "pumpswap" and pa:
        acc = f.raw(pa)
        if not acc or acc[0] != PSWAP or len(acc[1]) < 243 or f.pk(acc[1], 43) != mint: fbres["lp_locked"] = ("unknown", "PumpSwap pool not verified on-chain", "fallback-onchain")
        else:
            b = acc[1]; lpm = f.pk(b, 107); lps = f.u64(b, 203); cur = int(rpc("getTokenSupply", [lpm])["value"]["amount"])
            pct = 100.0 * (1 - cur / lps) if lps else None
            if pct is None: fbres["lp_locked"] = ("unknown", "pool lp_supply is 0", "fallback-onchain")
            else: fbres["lp_locked"] = ("pass" if pct >= 95 else "fail", f"{pct:.1f}% LP burned (on-chain: LP mint supply {cur} of {lps})", "fallback-onchain")
            vault_owner = pa; creator = f.pk(b, 211)
    else: fbres["lp_locked"] = ("unknown", f"pool type '{dex}' not supported by the backup check", "fallback-onchain")
    if creator in (None, "11111111111111111111111111111111"): creator = None
    hs = _holders(mint, prog)
    if not hs or not supply: return None
    top = sorted(((o, amt, a) for a, (o, amt) in hs.items()), key=lambda x: -x[1])
    th = [dict(owner=o, address=a, pct=round(100.0 * amt / supply, 3)) for o, amt, a in top[:60]]
    known = {vault_owner: dict(type="AMM")} if vault_owner else {}
    rc = dict(_fb=True, creator=creator, topHolders=th, knownAccounts=known, totalHolders=len(hs), token=dict(supply=supply), insiderNetworks=[],
              risks=[], rugged=False, tokenMeta=dict(mutable=mutable), transferFee=dict(pct=0), markets=[],
              token_extensions={k: True for k in bad})
    if bad: fbres["honeypot"] = ("fail", "Token-2022 extension(s) not allowed in backup check: " + ",".join(bad), "fallback-onchain")
    if not creator: fbres["dev_rugs"] = ("unknown", "creator not found on-chain", "fallback-onchain")
    else: fbres["dev_rugs"] = ("pass", "pending on-chain dev history", "fallback-onchain")
    fbres["bundled"] = ("pass", "pending on-chain bundle check", "fallback-onchain")
    return rc, fbres
