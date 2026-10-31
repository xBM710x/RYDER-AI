"""Agent council upgrades (PAPER ONLY), 2026-10-30. Six agents: scout, filter, analyst, executor, risk, logger (brain2.votes/decide).
Everything here can only LOWER votes or ADD a reject reason; no bar or hard safety check is loosened.
- Shared rug-pattern memory: fingerprints of scored coins + whether they died 30+ min later (detect.sweep_dead), read by risk/filter/scout.
- Wash flag: identical 5m and 1h trade counts on a pair older than 10 min.
- Disagreement check before buys: a trusted agent < 0.40 needs consensus +0.05.
- Shadow self-grading: every council decision is re-priced 60 min later; agents graded at 0.25 weight into trust.
- Per-agent vote explanation log ('council_votes')."""
import time, json, os, collections, threading
from logger import log
D = os.path.dirname(os.path.abspath(__file__)); SF = os.path.join(D, "brain13.json"); _L = threading.Lock()
def _load():
    try: return json.load(open(SF))
    except Exception: return {}
S = _load(); [S.setdefault(k, v) for k, v in dict(fp={}, cand={}, src={}, shadow=[], sgrades={}).items()]
STATS = collections.Counter()
def _seed_src():
    """backtest14 (2026-10-30): seed per-source death rates from the counterfactual table (1h after first sight, dead = -80% or worse)
    so the Scout rule works before live memory fills. Only adds sources not yet in memory."""
    if S["src"]: return
    try:
        from logger import conn
        c = conn(); src = {}
        for m, d in c.execute("SELECT mint, data FROM events WHERE kind='kill'"): src.setdefault(m, json.loads(d).get("source") or "?")
        for m, p in c.execute("SELECT mint, pct FROM counterfactual"):
            r = S["src"].setdefault(src.get(m, "?"), [0, 0]); r[0] += 1; r[1] += p <= -80
        c.close()
    except Exception: pass
def save():
    with _L:
        try: json.dump(S, open(SF + ".tmp", "w"), default=str); os.replace(SF + ".tmp", SF)
        except Exception: pass
def _f(x):
    try: return float(x or 0)
    except Exception: return 0.0
def age_min(pair): return (time.time() * 1000 - (pair.get("pairCreatedAt") or 0)) / 60000 if pair.get("pairCreatedAt") else 9999
def identical_windows(pair):
    tx = pair.get("txns") or {}; a, b = tx.get("m5") or {}, tx.get("h1") or {}
    return bool(a) and (a.get("buys"), a.get("sells")) == (b.get("buys"), b.get("sells")) and (a.get("buys") or 0) + (a.get("sells") or 0) > 0
def wash_flag(pair):
    """Identical 5m/1h counts are normal for a pair <10 min old; on an older pair it means the hour had no trades outside one 5-min burst."""
    return identical_windows(pair) and age_min(pair) > 10
def fingerprint(pair, cd):
    """Coarse shape of a coin at score time (dex, pair age, liquidity, mcap/liq, one-burst trading, source)."""
    liq = _f((pair.get("liquidity") or {}).get("usd")); mc = _f(pair.get("marketCap") or pair.get("fdv")); a = age_min(pair)
    return "|".join([pair.get("dexId") or "?", "<15m" if a < 15 else "<60m" if a < 60 else "old",
                     "liq<30k" if liq < 30e3 else "liq<100k" if liq < 100e3 else "liq100k+", "mc/l<3" if mc < 3 * liq else "mc/l<10" if mc < 10 * liq else "mc/l10+",
                     "burst" if identical_windows(pair) else "spread", (cd or {}).get("source") or "?"])
def note_candidate(m, pair, cd):
    if not pair or m in S["cand"]: return
    S["cand"][m] = dict(fp=fingerprint(pair, cd), src=(cd or {}).get("source") or "?", t=round(time.time()))
    if len(S["cand"]) > 5000: [S["cand"].pop(k) for k in list(S["cand"])[:1000]]
def outcome(m, dead):
    """Called by detect.sweep_dead (30+ min after first sight). Updates fingerprint + source rug rates (shared by all agents)."""
    c = S["cand"].pop(m, None)
    if not c: return
    for tab, key in (("fp", c["fp"]), ("src", c["src"])):
        r = S[tab].setdefault(key, [0, 0]); r[0] += 1; r[1] += bool(dead)
    STATS["outcomes"] += 1; STATS["rugs"] += bool(dead)
def rug_rate(tab, key, min_n=4):
    r = S[tab].get(key)
    return (r[1] / r[0], r[0]) if r and r[0] >= min_n else (None, r[0] if r else 0)
def adjust(v, pair, cd, m):
    """Per-agent upgrades applied to brain2 votes before the debate/decide. Only lowers votes."""
    fp = fingerprint(pair, cd); rr, n = rug_rate("fp", fp); sr, sn = rug_rate("src", (cd or {}).get("source") or "?", 8)
    def dn(a, d, why):
        if d > 0: v[a] = (round(max(0, v[a][0] - d), 3), v[a][1] + f"; {why}")
    if rr is not None and rr >= 0.5: dn("risk", 0.35 if rr >= 0.7 else 0.2, f"rug memory: {rr:.0%} of {n} look-alikes died")   # risk: shared rug memory (can trigger RISK VETO)
    if wash_flag(pair): dn("filter", 0.25, "wash flag: all 1h trades inside the last 5 min on a >10-min-old pair")             # filter: wash pattern
    if sr is not None and sr >= 0.30: dn("scout", 0.15, f"source {(cd or {}).get('source')} rug rate {sr:.0%} of {sn}")           # scout: source quality
    liq = _f((pair.get("liquidity") or {}).get("usd")); mc = _f(pair.get("marketCap") or pair.get("fdv"))
    if liq and mc > 20 * liq: dn("executor", 0.15, f"mcap {mc/liq:.0f}x liquidity (hard to exit)")                              # executor: exit-ability
    m5 = _f((pair.get("priceChange") or {}).get("m5"))
    if m5 > 25: dn("analyst", 0.08, f"already +{m5:.0f}% in 5m (late)")                                                          # analyst: late-entry discount
    g = S["sgrades"]
    if sum(x[0] for x in g.values()) >= 20:                                                                                         # logger: self-grading report
        acc = {a: round(x[1] / x[0], 2) for a, x in g.items() if x[0]}
        v["logger"] = (v["logger"][0], v["logger"][1] + f"; shadow accuracy {acc}")
    return v
def disagreement(v, cons, min_cons, trust):
    """Before a buy: any agent with trust >= 1.0 voting < 0.40 -> consensus must clear the bar by +0.05. Returns reject reason or None."""
    low = [a for a in v if v[a][0] < 0.40 and trust.get(a, 1) >= 1.0]
    if low and cons < min_cons + 0.05: STATS["disagree_block"] += 1; return f"disagreement: {', '.join(low)} below 0.40 and consensus {cons:.2f} < {min_cons + 0.05:.2f}"
    return None
def explain(m, sym, v, cons, go, reason, trust):
    tot = sum(trust.get(a, 1) for a in v) or 1
    log("council_votes", m, sym, go=go, consensus=cons, reason=reason[:200], votes={a: dict(vote=v[a][0], trust=trust.get(a, 1), weight=round(trust.get(a, 1) / tot, 3), why=v[a][1][:160]) for a in v})
    S["shadow"].append(dict(m=m, t=round(time.time()), votes={a: v[a][0] for a in v}, go=bool(go)))
    S["shadow"] = S["shadow"][-1000:]
def shadow_job():
    """Re-price council decisions after 60 min. Agent is 'right' if (vote >= 0.5) == (coin +10% or better and liquidity still >= $5k).
    Shadow grades feed brain2 trust at 0.25 weight alongside real-trade grades."""
    import brain2
    from common import dex_market
    due = [s for s in S["shadow"] if time.time() - s["t"] > 3600 and "done" not in s][:30]
    if not due: return
    mk = dex_market([s["m"] for s in due])
    for s in due:
        p = mk.get(s["m"]) or {}; liq = _f((p.get("liquidity") or {}).get("usd")); px = _f(p.get("priceUsd"))
        p0 = s.get("px0") or px; good = bool(px and liq >= 5000 and p0 and px >= p0 * 1.10)
        s["done"] = 1
        for a, c in s["votes"].items():
            g = S["sgrades"].setdefault(a, [0, 0]); g[0] += 1; g[1] += (c >= 0.5) == good
    for a, g in S["sgrades"].items():
        r = brain2.BRAIN["grades"].get(a, [0, 0]); n = r[0] + 0.25 * g[0]; w = r[1] + 0.25 * g[1]
        if a in brain2.BRAIN["trust"]: brain2.BRAIN["trust"][a] = round(max(0.5, min(1.5, 0.5 + (w + 1) / (n + 2))), 3)
    S["shadow"] = [s for s in S["shadow"] if "done" not in s or time.time() - s["t"] < 86400]
    brain2.save(brain2.BRAIN); save()
def jobs(k):
    if k % 600 == 321: __import__("brain10")._bg("b13_shadow", shadow_job)
    if k % 120 == 55: __import__("brain10")._bg("b13_save", save)
_seed_src()
def status():
    top = sorted(((r[1] / r[0], r[0], k) for k, r in S["fp"].items() if r[0] >= 4), reverse=True)[:5]
    return dict(stats=dict(STATS), fingerprints=len(S["fp"]), riskiest=[dict(fp=k, rug_rate=round(x, 2), n=n) for x, n, k in top],
                shadow_pending=sum(1 for s in S["shadow"] if "done" not in s), shadow_grades=S["sgrades"])
