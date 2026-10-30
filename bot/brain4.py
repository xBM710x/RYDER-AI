"""Upgrades 181-200 (PAPER ONLY; public read-only data; never touches wallets or keys)."""
import time, json, os, glob, shutil, hashlib, statistics, collections
from common import CFG, http_json, dex_market, rpc
from logger import conn, log
import brain2
D = os.path.dirname(os.path.abspath(__file__)); B = brain2.BRAIN
SAFETY = {"mint_authority", "freeze_authority", "lp_locked", "top10", "dev_rugs", "bundled", "honeypot", "mutable_meta", "copycat", "holder_cluster",
          "wash", "dev_sell", "linked_launch", "fresh_dev", "same_dev_today", "clone_contract", "team_supply", "listing_scam", "reused_rug_asset",
          "bundle_sizes", "rug_wallet_holders", "wallet_cluster", "price_impact", "liq_mcap", "exit_liquidity", "whale_volume"}
# 181 learn from missed winners: loosen only soft volume/score bars, bounded, never safety checks
def loosen():
    th = B["thresholds"]; th.setdefault("min_vol_h1", CFG["MIN_VOL_H1"]); ch = []
    for rule, s in B["rule_stats"].items():
        if rule in SAFETY or s.get("n", 0) < 20: continue
        rate = s.get("missed_winners", 0) / s["n"]
        if rule == "volume_1h" and rate > 0.05 and th["min_vol_h1"] > 25_000: th["min_vol_h1"] = int(max(25_000, th["min_vol_h1"] * 0.9)); ch.append(f"vol bar -> ${th['min_vol_h1']:,}")
        if rule.startswith("score") and rate > 0.10 and th["min_consensus"] > 0.5: th["min_consensus"] = round(max(0.5, th["min_consensus"] - 0.01), 3); ch.append(f"council bar -> {th['min_consensus']}")
    th["min_vol_h1"] = min(th["min_vol_h1"], __import__("brain8").APPROVED["MIN_VOL_H1"]); CFG["MIN_VOL_H1"] = th["min_vol_h1"]  # 361 never above approved bar
    if ch: B["lessons"] = (["missed winners: " + ", ".join(ch)] + B["lessons"])[:10]; brain2.save(B); log("loosen", changes=ch)
    return ch
# 182 fallback holder data from RPC when RugCheck is slow/down (other RugCheck-only checks stay fail-closed)
def rpc_top10(mint):
    try:  # GeckoTerminal holder distribution first (free public RPCs block getTokenLargestAccounts)
        a = http_json(f"https://api.geckoterminal.com/api/v2/networks/solana/tokens/{mint}/info", timeout=8)["data"]["attributes"]
        t = ((a.get("holders") or {}).get("distribution_percentage") or {}).get("top_10")
        if t: return round(float(t), 1)
    except Exception: pass
    la = rpc("getTokenLargestAccounts", [mint])["value"]; sup = float(rpc("getTokenSupply", [mint])["value"]["uiAmount"] or 0)
    if not sup: return None
    amts = sorted([float(a.get("uiAmount") or 0) for a in la], reverse=True)
    return round(sum(amts[1:11]) / sup * 100, 1)  # skip #1 (usually the pool / bonding curve)
# 187 lower volume bar for very new, fast-climbing coins
def vol_bar(pair):
    base = CFG["MIN_VOL_H1"]
    if not pair: return base
    age = (time.time() * 1000 - (pair.get("pairCreatedAt") or 0)) / 60000; pc = pair.get("priceChange") or {}; t5 = (pair.get("txns") or {}).get("m5") or {}
    if age < 30 and (pc.get("m5") or 0) > 10 and (t5.get("buys") or 0) > 1.5 * max(1, t5.get("sells") or 0): return int(base * 0.6)
    return base
# 188 re-check recent low-volume rejects once volume rises
def requeue_volume():
    c = conn(); rows = [r["mint"] for r in c.execute("SELECT DISTINCT mint FROM events WHERE kind='kill' AND ts>? AND data LIKE '%\"reason\": \"volume_1h\"%' AND data LIKE '%\"final\": true%'", (time.time() - 7200,))][-90:]
    mk = dex_market(rows); n = 0
    for m in rows:
        v = ((mk.get(m) or {}).get("volume") or {}).get("h1") or 0
        if v >= vol_bar(mk.get(m)) and m not in brain2.REJ: n += c.execute("UPDATE seen SET done=0, checks=?, last_ts=0 WHERE mint=? AND done=1", (CFG["MAX_CHECKS"] - 1, m)).rowcount
    c.commit(); c.close(); brain2.STATS["vol_requeue"] += n; return n
# 189 relative strength vs SOL
def rel_strength(pair, reg):
    return round(((pair.get("priceChange") or {}).get("h1") or 0) - ((reg or {}).get("sol_h1") or 0), 1)
# 185 early exit before a stop gaps / 191 hold longer while buyers arrive
def near_stop_exit(p, price, sp):
    return p["stop"] and price <= p["stop"] * 1.012 and sp["px"] < -1 and sp["sells"] > sp["buys"]
def buyers_arriving(sp, pair):
    return sp["buys"] >= 4 and sp["buys"] > 2 * sp["sells"] and brain2.pressure(pair) > 0.65
# 186 depth-based slippage model (constant-product estimate from pool liquidity)
def slip(usd, pair):
    liq = (pair.get("liquidity") or {}).get("usd") or 0
    if not liq: return 0.03
    return round(min(0.05, max(0.004, usd / (liq / 2) + 0.003)), 4)
# 192 top holders vs known rug wallets / 193 wallets showing up across many fresh coins
def holder_risk(owners):
    owners = [o for o in owners if o][:15]
    if not owners: return None
    c = conn(); q = ",".join("?" * len(owners))
    bad = c.execute(f"SELECT COUNT(*) FROM rug_wallets WHERE wallet IN ({q})", owners).fetchone()[0]
    try: multi = c.execute(f"SELECT COUNT(*) FROM (SELECT wallet FROM holders WHERE wallet IN ({q}) GROUP BY wallet HAVING COUNT(DISTINCT mint)>=3)", owners).fetchone()[0]
    except Exception: multi = 0
    c.close()
    if bad: return "rug_wallet_holders", f"{bad} top holder(s) on the rug-wallet list"
    if multi >= 3: return "wallet_cluster", f"{multi} top holders also sit in 3+ other fresh coins (farm cluster)"
# 195 trading steadiness (lower = choppier) from 1s ticks
def steadiness(mint):
    q = [x[1] for x in brain2.TK.get(mint, []) if x[1]]
    if len(q) < 6: return 0.5
    r = [q[i] / q[i - 1] - 1 for i in range(1, len(q)) if q[i - 1]]
    return round(max(0, 1 - statistics.pstdev(r) * 40), 3)
# 190/196 priority queue for waiting coins (keep best N, swap out weakest)
def admit(pending, new_score, cap=8):  # 380: 5 -> 8
    if len(pending) < cap: return True, None
    worst = min(pending, key=lambda m: pending[m]["score"])
    if new_score > pending[worst]["score"] + 0.03: return True, worst
    return False, None
# 197 per-agent time-of-day trust
def tod_bucket(): return str(time.localtime().tm_hour // 6)
def tod_trust(agent):
    g = B.setdefault("tod_grades", {}).get(agent, {}).get(tod_bucket())
    return 1.0 if not g or g[0] < 5 else round(0.7 + 0.6 * g[1] / g[0], 3)
def tod_learn(votes, win):
    for a, (c, _) in (votes or {}).items():
        g = B.setdefault("tod_grades", {}).setdefault(a, {}).setdefault(tod_bucket(), [0, 0]); g[0] += 1; g[1] += ((c >= 0.5) == win)
# 198 adaptive scan speed
def scan_sec(feed_stats, last_cands, base):
    silent = not feed_stats.get("last") or time.time() - feed_stats["last"] > 300
    return 15 if silent or last_cands >= 10 else (45 if last_cands == 0 and base >= 30 else base)
# 199 best missed coin
def note_missed(m, rule, px, q, sym=None):
    g = q / px - 1; bm = B.get("best_missed") or {}
    if g > bm.get("gain", 0) or time.time() - bm.get("t", 0) > 86400: B["best_missed"] = dict(mint=m, rule=rule, gain=round(g, 2), sym=sym, t=time.time())
def missed_line():
    bm = B.get("best_missed")
    if not bm or time.time() - bm.get("t", 0) > 86400: return "Best missed coin: none in last 24h"
    return f"Best missed coin: {bm.get('sym') or bm['mint'][:6]} +{bm['gain']*100:.0f}% after I skipped it ({bm['rule']})"
# 200 auto-rollback to last good build if the new build underperforms
BF = os.path.join(D, "builds.json"); CODE = sorted(glob.glob(os.path.join(D, "*.py")))
def build_id(): return hashlib.sha1(b"".join(open(f, "rb").read() for f in CODE)).hexdigest()[:10]
def register_build(last_good):
    try: bs = json.load(open(BF))
    except Exception: bs = {}
    bid = build_id()
    if bs.get("current", {}).get("id") != bid: bs["current"] = dict(id=bid, since=time.time(), last_good=last_good); json.dump(bs, open(BF, "w"), indent=1)
    return bs["current"]
def check_rollback():
    bs = json.load(open(BF)); cur = bs["current"]; lg = cur.get("last_good")
    c = conn(); cl = [r["pnl"] for r in c.execute("SELECT pnl FROM positions WHERE status='closed' AND version=? AND closed>? AND reason!='partial_tp'", (CFG["VERSION"], cur["since"]))]; c.close()
    if len(cl) < 8 or not lg or not os.path.isdir(lg): return None
    pnl, wr = sum(cl), sum(p > 0 for p in cl) / len(cl)
    if pnl < -0.08 * CFG["START_BALANCE"] and wr < 0.3:
        for f in glob.glob(os.path.join(lg, "*.py")): shutil.copy2(f, D)
        bs.setdefault("rolled_back", []).append(dict(bad=cur["id"], to=lg, pnl=round(pnl, 2), trades=len(cl), t=time.time())); json.dump(bs, open(BF, "w"), indent=1)
        log("rollback", bad=cur["id"], to=lg, pnl=round(pnl, 2), win_rate=round(wr, 2))
        __import__("alerts").send(f"⏪ RYDER auto-rollback (paper): build {cur['id']} lost ${pnl:.2f} over {len(cl)} trades ({wr:.0%} wins). Restored last good build; restarting.")
        os._exit(3)  # supervisor restarts the runner on the restored code
