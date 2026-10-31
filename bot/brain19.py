"""Five agents (2026-10-31, approved by Braydon). PAPER ONLY, read-only chain data, no LLM calls. Only exits sooner / lowers size / pauses.
1 Exit manager: adaptive protect-stop on momentum fade after a run, faster cut on volume collapse. SHADOW MODE: it logs what it would do and
  scores itself against the real exit on every close ('exit_mgr' in data.json). It never touches stops until Braydon approves going live.
2 Rug sentinel: every ~60s per held v3+ coin (on the existing per-minute recheck thread): dev wallet selling, LP shrinking (<60% of first seen),
  top-holder concentration jump (+15 pts, pool account excluded), mint/freeze authority appearing -> exit 'rug_sentinel_<why>'.
3 Wallet scout: copy-P&L grade on top of the behaviour grade. 3+ closed copies with positive total and >=50% wins -> copyable even if
  behaviour graded bad/ok; 3+ copies with negative total -> not copyable even if 'good'. (Demotion after 3 straight losses still applies.)
4 Market mood: SOL trend + new-coin launch rate + survival -> size multiplier 0.5..1.0, or pause new buys. Never above 1.0.
Coach lives in coach.py (nightly, suggestion file only, never applies anything)."""
import json, os, time, threading, collections
from logger import conn, log
D = os.path.dirname(os.path.abspath(__file__)); SF = os.path.join(D, "brain19.json"); _L = threading.Lock(); STATS = collections.Counter()
try: S = json.load(open(SF))
except Exception: S = {}
for k, v in dict(shadow={}, scored=[], sent={}, mood={}).items(): S.setdefault(k, v)
def save():
    with _L:
        try: json.dump(S, open(SF + ".tmp", "w")); os.replace(SF + ".tmp", SF)
        except Exception: pass
def _f(x):
    try: return float(x)
    except Exception: return None
# ---------- 1 exit manager (shadow) ----------
EM = dict(min_run=0.15, protect=0.06, min_age=180, vc_age=300, vc_ratio=0.10, vc_max_gain=0.03)
def exit_signal(p, price, pr, now=None):
    """Return (reason, protect_stop) — reason when it would exit now; protect_stop is only ever >= the current stop."""
    now = now or time.time(); age = now - p["opened"]; peak = max(p.get("peak") or 0, price); e = p["entry"]
    pc = pr.get("priceChange") or {}; tx5 = (pr.get("txns") or {}).get("m5") or {}; vol = pr.get("volume") or {}
    stop = p.get("stop") or 0
    if age >= EM["min_age"] and peak >= e * (1 + EM["min_run"]) and (_f(pc.get("m5")) or 0) < 0 and (tx5.get("sells") or 0) > (tx5.get("buys") or 0):
        ps = max(stop, peak * (1 - EM["protect"]))
        if price <= ps: return "exit_mgr_fade", ps
        return None, ps
    v5, v1 = _f(vol.get("m5")) or 0, _f(vol.get("h1")) or 0
    if age >= EM["vc_age"] and v1 and v5 < EM["vc_ratio"] * v1 / 12 and price < e * (1 + EM["vc_max_gain"]): return "exit_mgr_vol_collapse", stop
    return None, stop
def shadow(p, price, pr):
    try:
        k = str(p["id"]); r, _ = exit_signal(p, price, pr)
        if r and k not in S["shadow"]:
            S["shadow"][k] = dict(reason=r, px=price, entry=p["entry"], t=round(time.time()), sym=p["symbol"]); STATS["would_exit"] += 1
            log("exit_mgr_shadow", p["mint"], p["symbol"], would=r, px=price, pct=round((price / p["entry"] - 1) * 100, 2), book=p.get("version")); save()
    except Exception: STATS["err"] += 1
def on_close(pos, price, reason):
    k = str(pos["id"]); s = S["shadow"].pop(k, None)
    if not s: return
    S["scored"].append(dict(sym=pos["symbol"], would=s["reason"], would_pct=round((s["px"] / pos["entry"] - 1) * 100, 2), real_pct=round((price / pos["entry"] - 1) * 100, 2), real=reason, t=round(time.time())))
    S["scored"] = S["scored"][-200:]; save()
def em_summary():
    sc = S["scored"]; d = [x["would_pct"] - x["real_pct"] for x in sc]
    return dict(mode="shadow", n=len(sc), better=sum(x > 0 for x in d), worse=sum(x < 0 for x in d), avg_diff_pct=round(sum(d) / len(d), 2) if d else None, open_flags=len(S["shadow"]))
# ---------- 2 rug sentinel ----------
FLAG = {}
def _top_share(mint):
    from common import rpc
    la = (rpc("getTokenLargestAccounts", [mint]) or {}).get("value") or []; sup = _f(((rpc("getTokenSupply", [mint]) or {}).get("value") or {}).get("uiAmount"))
    if not la or not sup: return None
    amts = sorted((_f(a.get("uiAmount")) or 0 for a in la), reverse=True)[1:11]  # drop the largest (pool / bonding curve)
    return round(sum(amts) / sup * 100, 2)
def _auth(mint):
    from common import rpc
    i = rpc("getAccountInfo", [mint, {"encoding": "jsonParsed"}])["value"]["data"]["parsed"]["info"]; return i.get("mintAuthority"), i.get("freezeAuthority")
def sentinel_eval(base, now_):
    """Pure decision: base/now dicts with dev, top, liq, auth -> reason or None."""
    import detect
    if now_.get("auth") and any(now_["auth"]) and not (base.get("auth") and any(base["auth"])): return "rug_sentinel_authority"
    if detect.dev_sold(base.get("dev"), now_.get("dev")): return "rug_sentinel_dev_sell"
    if base.get("liq") and now_.get("liq") is not None and now_["liq"] < base["liq"] * 0.6: return "rug_sentinel_lp_shrink"
    if base.get("top") is not None and now_.get("top") is not None and now_["top"] > base["top"] + 15: return "rug_sentinel_top_holders"
    return None
def sentinel(m, liq=None):
    try:
        import detect
        c = conn(); r = c.execute("SELECT creator FROM creators WHERE mint=?", (m,)).fetchone(); c.close(); cr = r[0] if r else None
        def _try(fn):
            try: return fn()
            except Exception: STATS["sentinel_rpc_miss"] += 1; return None
        cur = dict(auth=_try(lambda: list(_auth(m))), top=_try(lambda: _top_share(m)), liq=_f(liq), dev=_try(lambda: detect.dev_balance(cr, m)) if cr else None)
        b = S["sent"].get(m)
        if b is None: S["sent"][m] = cur; save(); return None
        for k in ("top", "dev", "liq"):
            if b.get(k) is None and cur.get(k) is not None: b[k] = cur[k]
        why = sentinel_eval(b, cur); STATS["sentinel_checks"] += 1
        if why: FLAG[m] = why; STATS[why] += 1; log("rug_sentinel", m, why=why, base=b, now=cur)
        return why
    except Exception as e: STATS["sentinel_err"] += 1; return None
# ---------- 3 wallet scout ----------
def copy_grade(who, results=None):
    import brain17
    r = (results if results is not None else brain17.copy_results()).get(who, [])
    if len(r) < 3: return None, f"{len(r)} closed copies"
    tot = sum(r); wr = sum(p > 0 for p in r) / len(r)
    if tot > 0 and wr >= 0.5: return "good", f"{len(r)} copies, ${tot:+.2f}, {wr:.0%} wins"
    if tot < 0: return "bad", f"{len(r)} copies, ${tot:+.2f}"
    return None, f"{len(r)} copies, ${tot:+.2f}"
def copyable(who, behaviour, results=None):
    g, _ = copy_grade(who, results)
    return g == "good" if g else behaviour == "good"
# ---------- 4 market mood ----------
def mood_eval(sol_h1, sol_h24, launch_ratio, survival, n_surv):
    m, why = 1.0, []
    if (sol_h24 is not None and sol_h24 < -5) or (sol_h1 is not None and sol_h1 < -2): m *= 0.6; why.append("SOL falling")
    elif sol_h24 is not None and sol_h24 < -2: m *= 0.85; why.append("SOL soft")
    if launch_ratio is not None and launch_ratio < 0.5: m *= 0.85; why.append(f"launches {launch_ratio:.0%} of normal")
    if survival is not None and n_surv >= 10:
        if survival < 0.05: return 0.0, why + [f"survival {survival:.0%}: pause new buys"]
        if survival < 0.20: m *= 0.7; why.append(f"survival {survival:.0%}")
    return round(max(0.5, min(1.0, m)), 3), why
def mood_refresh():
    import extras
    from common import dex_market
    rg = extras.regime(); now = time.time(); c = conn()
    def scans(a, b):
        n = 0
        for (d,) in c.execute("SELECT data FROM events WHERE kind='scan' AND ts BETWEEN ? AND ?", (now - a, now - b)):
            try: n += json.loads(d).get("n_raw") or 0
            except Exception: pass
        return n
    h1, h24 = scans(3600, 0), scans(86400, 0); lr = (h1 / (h24 / 24)) if h24 > 0 else None
    rows = c.execute("SELECT mint, first_liq FROM creators WHERE ts BETWEEN ? AND ? AND first_liq>0 ORDER BY ts DESC LIMIT 30", (now - 6 * 3600, now - 3600)).fetchall(); c.close()
    surv = None
    if rows:
        mk = dex_market([r[0] for r in rows]); surv = sum(1 for m, l in rows if ((mk.get(m) or {}).get("liquidity") or {}).get("usd", 0) >= 0.5 * l) / len(rows)
    mult, why = mood_eval(rg.get("sol_h1"), rg.get("sol_h24"), lr, surv, len(rows))
    S["mood"] = dict(mult=mult, why=why, sol_h1=rg.get("sol_h1"), sol_h24=rg.get("sol_h24"), launch_ratio=round(lr, 2) if lr is not None else None, survival=round(surv, 2) if surv is not None else None, n=len(rows), at=round(now))
    save(); return S["mood"]
def mood_mult():
    m = S.get("mood") or {}
    if not m or time.time() - m.get("at", 0) > 3600: return 1.0, None
    return m["mult"], ", ".join(m.get("why") or []) or None
def coach_nightly():
    d = time.strftime("%Y-%m-%d")
    if time.localtime().tm_hour == 3 and S.get("coach_day") != d:
        S["coach_day"] = d; save()
        try: import coach; out = coach.run(); log("coach", suggestion=out["suggestion"]["tweak"], ok=out["suggestion"]["ok"], applied=False)
        except Exception as e: log("error", where="coach", trace=str(e)[:160])
def jobs(k):
    if k % 600 == 300: threading.Thread(target=coach_nightly, daemon=True, name="b19-coach").start()
    if k % 900 == 45: threading.Thread(target=lambda: (mood_refresh() if True else None), daemon=True, name="b19-mood").start()
def status(): return dict(stats=dict(STATS), exit_mgr=em_summary(), mood=S.get("mood"), sentinel_watching=len(S["sent"]))
