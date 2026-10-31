"""Skeptic + trade diary + locked lanes + 2-loss half size (2026-10-31, approved by Braydon). PAPER ONLY. Only ADDS rejects / lowers size.
1 Skeptic: final veto before every v3+ paper buy (after the scorecard). Looks for a trap; reject 'skeptic_<why>'. Never approves anything.
2 Diary: on every full close, two plain lines (what went right / what went wrong) from trade data; stored in brain18.json, exported in
  data.json 'diary', and read back by the Skeptic as a nudge (repeated 'no lift' entries -> stricter spike check; never looser).
3 Locked lanes: every council step after the agents vote is a writer with its own lane(s). A writer may raise only its own agent's vote;
  raising another agent's vote is reverted (lowering = more caution is allowed, never loosens), and a vote under the veto line can't be
  raised by anyone, including the debate step. Violations logged 'lane_block'.
4 Two-loss brake: 2+ losing full exits in a row on a desk -> 0.5x size, on top of the existing executor streak brake."""
import json, os, time, threading, collections
from logger import conn, log
D = os.path.dirname(os.path.abspath(__file__)); SF = os.path.join(D, "brain18.json"); _L = threading.Lock(); STATS = collections.Counter()
try: S = json.load(open(SF))
except Exception: S = {}
S.setdefault("diary", [])
def save():
    with _L:
        try: json.dump(S, open(SF + ".tmp", "w")); os.replace(SF + ".tmp", SF)
        except Exception: pass
# ---------- 1 skeptic ----------
SK = dict(factor=0.40, spike_m5=40.0, spike_m5_nudged=25.0, spike_h1=500.0, min_liq=5000.0, liq_vs_size=40.0, top10=30.0, liq_drop=0.15)
def _f(x):
    try: return float(x)
    except Exception: return None
def skeptic(mint, pair, res, sc, size_usd=0.0, ver=None, now=None):
    """Return 'skeptic_<why>: detail' or None. Pure veto."""
    import re, brain17
    pair = pair or {}; res = res or {}; sc = sc or {}; pc = pair.get("priceChange") or {}
    w = [k for k, v in sc.items() if v < SK["factor"]]
    if w: k = min(w, key=lambda k: sc[k]); return f"skeptic_weak_{k}: {k} {sc[k]:.2f} barely above floor"
    lim = SK["spike_m5_nudged"] if nudged(ver) else SK["spike_m5"]
    m5, h1 = _f(pc.get("m5")), _f(pc.get("h1"))
    if m5 is not None and m5 > lim: return f"skeptic_spike: +{m5:.0f}% in 5 min (limit {lim:.0f}%{', tightened by diary' if lim < SK['spike_m5'] else ''})"
    if h1 is not None and h1 > SK["spike_h1"]: return f"skeptic_spike: +{h1:.0f}% in 1h"
    liq = _f((pair.get("liquidity") or {}).get("usd")) or None  # 0/missing (bonding-curve coins) = unknown; filters.check already gated liquidity
    if liq is not None and (liq < SK["min_liq"] or (size_usd and liq < size_usd * SK["liq_vs_size"])): return f"skeptic_thin_pool: ${liq:,.0f} pool"
    for k in ("dev_rugs", "_creator", "bundled", "holder_cluster", "wash"):
        if k in res and res[k][0] != "pass": return f"skeptic_{'dev' if k in ('dev_rugs', '_creator') else 'holders'}: {k} {res[k][0]}"
    mt = re.search(r"([\d.]+)%", str((res.get("top10") or ("", ""))[1]))
    if mt and float(mt.group(1)) > SK["top10"]: return f"skeptic_holders: top10 {mt.group(1)}%"
    h = [x for x in brain17.LIQH.get(mint, []) if (now or time.time()) - x[0] <= 600]
    if liq and h and liq < max(x[1] for x in h) * (1 - SK["liq_drop"]): return f"skeptic_liq_drop: pool down {1 - liq / max(x[1] for x in h):.0%} in 10 min"
    return None
# ---------- 2 diary ----------
def diary_lines(sym, entry, exit_, peak, pnl, reason, held_min, sc=None):
    g = (exit_ / entry - 1) * 100 if entry else 0; pk = ((peak or entry) / entry - 1) * 100 if entry else 0; tags = []
    if pnl > 0: right = f"{sym}: closed {g:+.1f}% (${pnl:+.2f}) via {reason.replace('_', ' ')}" + (f" after peaking +{pk:.0f}%" if pk > g + 1 else "") + "."
    elif reason in ("lp_pull", "liq_drop", "dev_sell", "rug_recheck"): right = f"{sym}: got out on {reason.replace('_', ' ')} at {g:+.1f}% instead of riding a rug."
    elif g > -9: right = f"{sym}: the stop held the loss to {g:.1f}% (${pnl:.2f})."
    else: right = f"{sym}: position size kept the hit to ${pnl:.2f}."
    if pk < 2: wrong = f"never lifted (peak +{pk:.1f}%): entry was late or the move was already over."; tags.append("no_lift")
    elif pk - g > 10: wrong = f"gave back {pk - g:.0f} pts from the +{pk:.0f}% peak before exiting."; tags.append("gave_back")
    elif pnl <= 0: wrong = f"it reversed after +{pk:.0f}% and stopped out in {held_min:.0f} min."; tags.append("reversal")
    else: wrong = "nothing major" + (f"; weakest factor was {min(sc, key=sc.get)} {min(sc.values()):.2f}" if sc else "") + "."
    if reason in ("lp_pull", "liq_drop", "dev_sell", "rug_recheck"): tags.append("rug_exit")
    return "What went right: " + right, "What went wrong: " + wrong, tags
def on_close(pos, price, pnl, reason):
    try:
        sc = None; c = conn(); r = c.execute("SELECT data FROM events WHERE kind='paper_buy' AND mint=? ORDER BY ts DESC LIMIT 1", (pos["mint"],)).fetchone(); c.close()
        if r: sc = json.loads(r["data"]).get("scorecard")
        a, b, tags = diary_lines(pos["symbol"], pos["entry"], price, max(pos.get("peak") or 0, price), pnl, reason, (time.time() - pos["opened"]) / 60, sc)
        e = dict(t=round(time.time()), sym=(pos["symbol"] or "")[:14], desk=pos.get("version"), pnl=round(pnl, 2), right=a, wrong=b, tags=tags)
        with _L: S["diary"].append(e); S["diary"] = S["diary"][-200:]
        save(); log("diary", pos["mint"], pos["symbol"], right=a, wrong=b, tags=tags, book=pos.get("version")); STATS["diary"] += 1
    except Exception as ex: log("error", where="b18_diary", trace=str(ex)[:160])
def recent(n=5, desk=None): return [e for e in S["diary"] if desk in (None, e.get("desk"))][-n:]
def nudged(desk): return sum("no_lift" in e.get("tags", []) for e in recent(5, desk)) >= 2
# ---------- 3 locked lanes ----------
def lanes(prev, new, writer, own, veto=None, lower_ok=True):
    """Merge a council step: only `own` agents may change; vetoed votes (< veto line) can't be raised. Returns merged dict."""
    veto = veto if veto is not None else __import__("brain2").BRAIN["thresholds"]["veto"]
    out = {}; blocked = []
    for a, x in prev.items():
        y = new.get(a, x)
        if a not in own and (y[0] > x[0] or (y[0] < x[0] and not lower_ok)): blocked.append(f"{a} {x[0]:.2f}->{y[0]:.2f}"); y = x
        elif x[0] < veto and y[0] > x[0]: blocked.append(f"{a} veto {x[0]:.2f}->{y[0]:.2f}"); y = (x[0], y[1])
        out[a] = y
    if blocked and writer == "_test": return out
    if blocked: STATS["lane_block"] += 1; STATS["lane_block_" + writer] += 1
    if blocked and STATS["lane_block"] % 25 == 1: log("lane_block", writer=writer, blocked=blocked[:4])
    return out
# ---------- 4 two-loss half size ----------
def two_loss_mult(ver, pnls=None):
    if pnls is None:
        c = conn(); pnls = [r[0] for r in c.execute("SELECT pnl FROM positions WHERE status='closed' AND version=? AND reason!='partial_tp' ORDER BY closed DESC LIMIT 2", (ver,))]; c.close()
    return 0.5 if len(pnls) >= 2 and all(p <= 0 for p in pnls[:2]) else 1.0
def status(): return dict(stats=dict(STATS), diary_n=len(S["diary"]), last=S["diary"][-1:] )
