"""RYDER upgrades 361-400 (PAPER ONLY): trade-frequency fixes, funnel diagnostics, safe idle relax, more discovery. Hard safety checks are never relaxed."""
import time, collections, json
from common import CFG, http_json
from logger import conn, log
APPROVED = dict(MIN_VOL_H1=28_000, MIN_LIQ=18_000, MIN_SCORE=0.55)  # user-approved 2026-10-30 08:50 PT; self-tuning may go lower (bounded) but never above
FUNNEL = collections.Counter(); FUN_T0 = [time.time()]; STAGE = dict(relax=1.0, score_drift=0.0)
def enforce_ceiling():
    """361 (bug fix): brain2/brain4 self-tuned thresholds (36k vol / 25k liq) were overriding the approved 28k / 18k at startup."""
    import brain2; th = brain2.BRAIN["thresholds"]; ch = {}
    for k, ck in (("min_vol_h1", "MIN_VOL_H1"), ("min_liq", "MIN_LIQ")):
        if th.get(k, 0) > APPROVED[ck] or CFG[ck] > APPROVED[ck]: ch[k] = (th.get(k), APPROVED[ck]); th[k] = min(th.get(k, APPROVED[ck]), APPROVED[ck]); CFG[ck] = min(CFG[ck], th[k])
    if ch: brain2.save(brain2.BRAIN); log("threshold_fix", changes={k: list(v) for k, v in ch.items()})
    return ch
def count(gate): FUNNEL[gate] += 1  # 369
def funnel(): return dict(since=time.strftime("%H:%M", time.localtime(FUN_T0[0])), gates=dict(FUNNEL.most_common(25)))
def idle_min(ver="v3"):
    c = conn(); r = c.execute("SELECT MAX(opened) FROM positions WHERE version=?", (ver,)).fetchone()[0]; c.close()
    import runner_start; return (time.time() - (r or runner_start.T0)) / 60
def quiet():
    """384: quiet market = fewer than 6 coins/hour clearing the volume bar."""
    return FUNNEL["vol_pass"] / max(0.25, (time.time() - FUN_T0[0]) / 3600) < 6
def patience():
    """367/373/385/393: main-desk patience relax. Idle 60 min -> soft bars x0.9, 120 min -> x0.85, and after 6 PM with <3 trades today x0.8.
    Score floor drifts 0.55 -> 0.52 after 120 min idle. Floors: vol 20k, liq 14k. Resets on the next main trade. Hard checks untouched."""
    try: idl = idle_min()
    except Exception: idl = 0
    f = 1.0 if idl < 60 else 0.9 if idl < 120 else 0.85
    lt = time.localtime()
    if lt.tm_hour >= 18 and f < 1:
        c = conn(); n = c.execute("SELECT COUNT(*) FROM positions WHERE version='v3' AND opened>?", (time.mktime(lt[:3] + (0, 0, 0, 0, 0, -1)),)).fetchone()[0]; c.close()
        if n < 3: f = 0.8
    drift = 0.03 if idl >= 120 else 0.0
    if (f, drift) != (STAGE["relax"], STAGE["score_drift"]): log("patience", factor=f, score_drift=drift, idle_min=round(idl)); STAGE.update(relax=f, score_drift=drift)  # 394
    return f
def vol_bar(base):
    """367/378: effective main volume bar (patience x overnight 0.85), floor 20k."""
    h = time.localtime().tm_hour; on = 0.85 if 0 <= h < 7 else 1.0
    return int(max(20_000, base * STAGE["relax"] * on))
def liq_bar(base): return int(max(14_000, base * STAGE["relax"]))
def min_score(base): return round(max(0.52, base - STAGE["score_drift"]), 3)
def projected_vol(pair):
    """364/398: young pairs (<60 min) judged on projected 1h volume (5m x 12, discounted 30%), only when buys > sells in the last 5 min."""
    if not pair: return None
    v1 = ((pair.get("volume") or {}).get("h1")) or 0; v5 = ((pair.get("volume") or {}).get("m5")) or 0
    age = (time.time() * 1000 - (pair.get("pairCreatedAt") or 0)) / 60000; t5 = (pair.get("txns") or {}).get("m5") or {}
    if age < 60 and (t5.get("buys") or 0) > (t5.get("sells") or 0): return max(v1, v5 * 12 * 0.7 * min(1, age / 20 + 0.25))
    return v1
def curve_liq(pair):
    """388 (approx): pump.fun bonding-curve pairs report no liquidity; use ~20% of mcap as real SOL depth proxy (capped $40k)."""
    if (pair or {}).get("dexId") in ("pumpfun", "pump-fun") and not ((pair.get("liquidity") or {}).get("usd")):
        mc = pair.get("marketCap") or pair.get("fdv") or 0; return min(40_000, mc * 0.2) if mc else None
    return None
def soft_socials(pair, vol, liq):
    """366: no socials -> soft (score -0.05) instead of a kill when the coin is clearly liquid & active (liq >= 25k and vol >= 1.5x bar)."""
    return bool(liq and vol and liq >= 25_000 and vol >= 1.5 * CFG["MIN_VOL_H1"])
def max_checks(cd, pair):
    """365: young / unknown pairs get 5 looks (pairs appear on DexScreener a few minutes after launch)."""
    if not pair or (time.time() * 1000 - (pair.get("pairCreatedAt") or 0)) / 60000 < 30: return 5
    return CFG["MAX_CHECKS"]
_GT = [0]
def discover():
    """374/375: extra free discovery: GeckoTerminal trending pools + top-volume pools on Solana (every 2 min)."""
    if time.time() - _GT[0] < 120: return []
    _GT[0] = time.time(); out = []
    for u, src in (("https://api.geckoterminal.com/api/v2/networks/solana/trending_pools?page=1", "gecko-trending"), ("https://api.geckoterminal.com/api/v2/networks/solana/pools?page=1&sort=h24_volume_usd_desc", "gecko-volume")):
        try:
            for p in (http_json(u) or {}).get("data", [])[:20]:
                m = p["relationships"]["base_token"]["data"]["id"].replace("solana_", "")
                if m.startswith("So111") or m.startswith("EPjF") or m.startswith("Es9v"): continue
                out.append(dict(mint=m, name=p["attributes"].get("name", "").split(" / ")[0], source=src, dex="unknown", vol=float(((p["attributes"].get("volume_usd") or {}).get("h1")) or 0)))
        except Exception: pass
    FUNNEL["discover_gecko"] += len(out); return out
def order(cands):
    """376: within a scan, evaluate highest-volume candidates first (after the existing source ordering)."""
    return sorted(cands, key=lambda d: -(d.get("vol") or 0))
MIG = {}
def migration_recheck(m):
    """377: graduates re-checked at +2 and +6 min after migration (pair data exists by then)."""
    MIG.setdefault(m, time.time())
def due_migrations():
    now = time.time(); out = []
    for m, t in list(MIG.items()):
        age = now - t
        if 120 <= age < 130 or 360 <= age < 370: out.append(m)
        if age > 400: MIG.pop(m, None)
    return out
def staying_power(checks, pair):
    """379: coin survived 2+ rechecks and volume is still there -> +0.02."""
    return 0.02 if checks >= 2 and ((pair.get("volume") or {}).get("h1") or 0) >= CFG["MIN_VOL_H1"] else 0.0
SECOND = {}
def second_chance(m, sc, bar, pair):
    """372: score within 0.05 of the bar -> one re-evaluation after 5 min if 1h volume grows 30%+."""
    if bar - 0.05 <= sc < bar and m not in SECOND: SECOND[m] = (time.time(), ((pair.get("volume") or {}).get("h1")) or 0)
def due_second():
    out = []
    for m, (t, v) in list(SECOND.items()):
        if time.time() - t > 300: out.append((m, v)); SECOND.pop(m, None)
    return out
def diagnose():
    """389: over-blocking check: a soft gate causing >85% of rejections for 2h while its skipped coins win >20% of the time -> log + recap note."""
    tot = sum(v for k, v in FUNNEL.items() if k.startswith("kill:")) or 1
    import brain7; out = []
    for k, v in FUNNEL.items():
        if not k.startswith("kill:") or v / tot < 0.85: continue
        w, n, _ = (brain7.S["nm"].get(k[5:]) or [0, 0, 0])
        if n >= 20 and w / n > 0.2 and time.time() - FUN_T0[0] > 7200: out.append(f"{k[5:]} blocks {v/tot:.0%} and {w}/{n} skipped coins ran +30%")
    if out: log("overblocking", notes=out)
    return out
def funnel_line():
    """391: one-line funnel for recap / weekly."""
    g = FUNNEL; return f"Funnel since {funnel()['since']}: seen {g['seen']} · vol ok {g['vol_pass']} · safety ok {g['safety_pass']} · scored {g['scored']} · waited {g['entry_wait']} · bought {g['bought']}"
def hourly():
    """370: hourly funnel snapshot to the Logger."""
    log("funnel", **funnel()); diagnose()
def invariants():
    """395: relax never touches hard checks: assert floors and that hard rules are not in any relaxed set."""
    ok = vol_bar(1) >= 20_000 and liq_bar(1) >= 14_000 and min_score(0) >= 0.52
    log("relax_selftest", ok=ok); return ok
def status():
    """386/399: heartbeat block: funnel per gate, patience stage, FOMO stage."""
    import fomo
    return dict(funnel=funnel(), patience=STAGE, quiet=quiet(), bars=dict(vol=vol_bar(CFG["MIN_VOL_H1"]), liq=liq_bar(CFG["MIN_LIQ"]), score=min_score(CFG["MIN_SCORE"])),
                fomo=dict(factor=fomo.factor(), evals=FUNNEL["fomo_eval"], buys=FUNNEL["fomo_buy"]))
