"""Coach (nightly, PAPER ONLY, no LLM). Reads the trade diary, skip stats and kill counterfactuals, backtests at most ONE rule tweak on stored
data, and writes a suggestion to reports/coach_<date>.md + reports/coach_latest.json. It NEVER changes config or code; Braydon approves changes.
Safety checks (rug/LP/authority/holders/dev/bundle) are never proposed for loosening."""
import json, os, sqlite3, statistics, time, datetime
D = os.path.dirname(os.path.abspath(__file__)); R = os.path.join(D, "reports"); os.makedirs(R, exist_ok=True)
SAFE_ONLY = {"volume_1h", "liquidity", "recheck", "no_dip", "budget", "portfolio"}  # non-safety rules the coach may look at
def run(now=None):
    now = now or time.time(); c = sqlite3.connect("file:" + os.path.join(D, "desk.db") + "?mode=ro", uri=True, timeout=10)
    try: diary = json.load(open(os.path.join(D, "brain18.json"))).get("diary") or []
    except Exception: diary = []
    try: em = json.load(open(os.path.join(D, "brain19.json"))).get("scored") or []
    except Exception: em = []
    last = diary[-10:]; tags = [t for e in last for t in e.get("tags", [])]
    kills = {}
    for (d,) in c.execute("SELECT data FROM events WHERE kind='kill' AND ts>?", (now - 86400,)):
        try: k = str(json.loads(d).get("reason", "")).split(":")[0]; kills[k] = kills.get(k, 0) + 1
        except Exception: pass
    cf = {}
    for rule, pct in c.execute("SELECT rule, pct FROM counterfactual WHERE ts>? AND pct IS NOT NULL", (now - 7 * 86400,)): cf.setdefault(rule, []).append(pct)
    c.close(); sug = None
    if tags.count("gave_back") >= 2 and em:  # tweak A: exit manager live
        d = [x["would_pct"] - x["real_pct"] for x in em]
        sug = dict(tweak="Turn the exit manager live (protect-stop 6% under peak after a +15% run fades)", backtest=f"{len(d)} shadow-scored exits: avg {statistics.mean(d):+.2f} pts vs the real exit, better {sum(x > 0 for x in d)} / worse {sum(x < 0 for x in d)}",
                   apply_if="avg > 0 and worse <= better", ok=bool(d) and statistics.mean(d) > 0 and sum(x < 0 for x in d) <= sum(x > 0 for x in d))
    else:  # tweak B: the non-safety skip rule that most often skipped coins that later ran
        best = None
        for rule, xs in cf.items():
            if rule not in SAFE_ONLY or len(xs) < 10: continue
            won = sum(x > 50 for x in xs) / len(xs); dead = sum(x < -50 for x in xs) / len(xs)
            if best is None or won - dead > best[1]: best = (rule, won - dead, len(xs), won, dead, statistics.median(xs))
        if best:
            sug = dict(tweak=f"Review the '{best[0]}' skip (not a safety check)", backtest=f"{best[2]} skipped coins (7d): {best[3]:.0%} later ran +50%, {best[4]:.0%} later died -50%, median {best[5]:+.0f}%",
                       apply_if="ran% clearly above died% over 50+ coins", ok=best[2] >= 50 and best[3] > best[4] + 0.1)
    out = dict(at=datetime.datetime.fromtimestamp(now).strftime("%Y-%m-%d %H:%M PT"), diary_n=len(diary), last10_tags=tags, kills24h_top=sorted(kills.items(), key=lambda x: -x[1])[:6],
               suggestion=sug or dict(tweak="No change suggested", backtest="not enough data", ok=False), applied=False, note="Suggestion only. Nothing is applied without Braydon's OK.")
    json.dump(out, open(os.path.join(R, "coach_latest.json"), "w"), indent=1)
    s = out["suggestion"]
    open(os.path.join(R, f"coach_{out['at'][:10]}.md"), "w").write(f"# RYDER coach — {out['at']}\n\nSuggestion: {s['tweak']}\n\nBacktest: {s['backtest']}\n\nPasses its own bar: {'yes' if s['ok'] else 'no'}\n\nNOT applied. Braydon approves any change.\n")
    return out
if __name__ == "__main__": print(json.dumps(run()["suggestion"]))
