"""Publish PAPER stats to github.com/xBM710x/RYDER-AI data.json (only that file).
Token is read from env RYDER_GITHUB_TOKEN at runtime; it is never printed, logged or written."""
import os, sys, json, time, base64, subprocess, urllib.request, urllib.error, datetime
D = os.path.dirname(os.path.abspath(__file__))
INTERVAL = 180
API = "https://api.github.com/repos/xBM710x/RYDER-AI/contents/data.json"
def build():
    subprocess.run([sys.executable, os.path.join(D, "export_dashboard.py")], cwd=D, check=True, stdout=subprocess.DEVNULL)
    line = open(os.path.join(D, "page_data_line.txt")).read().strip()
    d = json.loads(line[line.index("{"):line.rindex("}") + 1])
    d["paper"] = True
    now = datetime.datetime.now(datetime.timezone.utc); d["updated_at"] = now.isoformat(timespec="seconds")
    hb = {}
    try: hb = json.load(open(os.path.join(D, "heartbeat.json")))
    except Exception: pass
    age = round(time.time() - hb["ts"]) if hb.get("ts") else None
    d["heartbeat"] = dict(at=d["updated_at"], runner_alive=age is not None and age < 120, runner_last_beat_s=age,
                          pending_entries=hb.get("pending"), live_feed=bool((hb.get("ws") or {}).get("connected")),
                          live_feed_events=(hb.get("ws") or {}).get("events"), publish_every_s=INTERVAL)
    try: d["ryder_events"] = ryder_events()
    except Exception: d["ryder_events"] = []
    try: d["trade_quality"] = __import__("brain15").quality()  # data only (no panel): expectancy, profit factor, drawdown per desk
    except Exception: d["trade_quality"] = None
    try: d["skip_tally"] = skip_tally()
    except Exception: d["skip_tally"] = None
    try: d["copy_desk"] = copy_desk()
    except Exception: d["copy_desk"] = None
    try: d["diary"] = (json.load(open(os.path.join(D, "brain18.json"))).get("diary") or [])[-20:][::-1]  # b18 trade diary (newest first; data only)
    except Exception: d["diary"] = []
    try:  # b19 minimal status (data only, no panel)
        b19 = json.load(open(os.path.join(D, "brain19.json"))); sc = b19.get("scored") or []; dd = [x["would_pct"] - x["real_pct"] for x in sc]; mo = b19.get("mood") or {}
        try: co = json.load(open(os.path.join(D, "reports", "coach_latest.json"))).get("suggestion") or {}
        except Exception: co = {}
        d["agents5"] = dict(exit_mgr=dict(mode="shadow", n=len(dd), better=sum(x > 0 for x in dd), worse=sum(x < 0 for x in dd)), mood=dict(mult=mo.get("mult"), why=mo.get("why")),
                            sentinel_watching=len(b19.get("sent") or {}), coach=dict(tweak=co.get("tweak"), ok=co.get("ok"), applied=False))
    except Exception: d["agents5"] = None
    try: d["calendar"] = calendar_export(d)
    except Exception: d["calendar"] = None
    return d
SKIP_BUCKETS = [("Volume too low", ("volume_1h",)), ("Liquidity too low", ("liquidity", "thin_pool")), ("No socials", ("socials",)),
    ("Copycat / scam name", ("copycat", "scam_name")), ("LP not locked", ("lp_locked",)),
    ("Bundled / top holders", ("top10", "sniper_wallets", "bundle_sizes", "bundled", "holder_cluster")),
    ("Dev / contract risk", ("mint_authority", "dev_rugs", "honeypot_shape", "honeypot", "fresh_dev")),
    ("Wallet sold early", ("copy_wallet_sold_early",))]
def skip_tally(hours=24):
    """Logger card: last-24h skip reasons (one per coin check) in plain-English buckets; best/worst closed paper trade same window."""
    import sqlite3
    since = time.time() - hours * 3600
    c = sqlite3.connect("file:" + os.path.join(D, "desk.db") + "?mode=ro", uri=True, timeout=10)
    raw = {}
    for (dat,) in c.execute("SELECT data FROM events WHERE kind='kill' AND ts>?", (since,)):
        try: r = str(json.loads(dat or "{}").get("reason", ""))
        except Exception: r = ""
        k = r.split(":")[0].split("(")[0].strip(); raw[k] = raw.get(k, 0) + 1
    pn = [r[0] for r in c.execute("SELECT pnl FROM positions WHERE status='closed' AND closed>? AND pnl IS NOT NULL", (since,))]
    c.close()
    out, used = [], set()
    for name, keys in SKIP_BUCKETS:
        out.append([name, sum(raw.get(k, 0) for k in keys)]); used.update(keys)
    out.append(["Other checks", sum(v for k, v in raw.items() if k not in used)])
    return dict(hours=hours, total=sum(raw.values()), buckets=out, best=round(max(pn), 2) if pn else None, worst=round(min(pn), 2) if pn else None)
DESK_LABEL = {"v1": "v1", "v2": "v2", "v3": "Main", "v3b": "Strict", "v3x": "FOMO"}
def calendar_export(d):
    """Calendar view: REAL paper trades from positions table, all desks. Days in America/Los_Angeles. No addresses/secrets."""
    import sqlite3
    from zoneinfo import ZoneInfo
    tz = ZoneInfo("America/Los_Angeles")
    c = sqlite3.connect("file:" + os.path.join(D, "desk.db") + "?mode=ro", uri=True, timeout=10)
    rows = c.execute("SELECT symbol, version, cost, opened, closed, pnl, status, reason, mint FROM positions ORDER BY opened").fetchall()
    why = {}  # b17: scorecard + plain-English 'why I bought it' from the paper_buy event (data only)
    for m_, ts_, dat_ in c.execute("SELECT mint, ts, data FROM events WHERE kind='paper_buy' AND data LIKE '%why_bought%'"):
        try: j_ = json.loads(dat_); why.setdefault(m_, []).append((ts_, j_.get("book"), j_.get("scorecard"), j_.get("why_bought")))
        except Exception: pass
    c.close()
    vers = d.get("versions") or []
    start = round(sum(300.0 for _ in vers) or 300.0, 2)
    open_cost = sum(r[2] or 0 for r in rows if r[6] != "closed")
    equity = round(sum(v.get("cash") or 0 for v in vers) + open_cost, 2) if vers else d.get("equity")
    trades, days, curve, eq = [], {}, [], start
    for sym, ver, cost, op, cl, pnl, st, why_, mint in rows:
        closed = st == "closed" and cl
        t = dict(sym=(sym or "")[:14], desk=DESK_LABEL.get(ver or "v1", ver), ver=ver, usd=round(cost or 0, 2),
                 opened=round(op), closed=round(cl) if closed else None, open=not closed, reason=why_ if closed else None,
                 pnl=round(pnl, 2) if closed and pnl is not None else None,
                 pct=round(pnl / cost * 100, 2) if closed and pnl is not None and cost else None)
        wb = next((x for x in why.get(mint, []) if abs(x[0] - op) < 120 and x[1] in (ver, None)), None)
        if wb: t.update(scorecard=wb[2], why_bought=wb[3])
        trades.append(t)
    for t in sorted([t for t in trades if not t["open"]], key=lambda t: t["closed"]):
        day = datetime.datetime.fromtimestamp(t["closed"], tz).strftime("%Y-%m-%d")
        x = days.setdefault(day, dict(pnl=0.0, n=0, w=0)); x["pnl"] = round(x["pnl"] + t["pnl"], 2); x["n"] += 1; x["w"] += t["pnl"] > 0
        eq += t["pnl"]; curve.append(dict(t=t["closed"], v=round(eq, 2)))
    nc = [t for t in trades if not t["open"]]
    return dict(tz="America/Los_Angeles", start=start, equity=equity, realized=round(sum(t["pnl"] for t in nc), 2),
                trades=len(nc), wins=sum(t["pnl"] > 0 for t in nc), open=len(trades) - len(nc),
                today=datetime.datetime.now(tz).strftime("%Y-%m-%d"), days=days, curve=curve, list=trades[::-1][:100])
RUG = ("rug", "dev_", "lp_", "bundle", "honeypot", "wash", "sniper", "linked_launch", "fresh_", "clone", "team_supply", "listing_scam", "wallet_", "mutable", "copycat")
def copy_desk():
    """Read-only copy desk (vC) summary: paper equity, today, grades by public trader name. No wallet addresses/keys."""
    import sqlite3, ast, re
    c = sqlite3.connect("file:" + os.path.join(D, "desk.db") + "?mode=ro", uri=True)
    cash = c.execute("SELECT v FROM account WHERE k='cash_vC'").fetchone(); start = 300.0
    rows = c.execute("SELECT mint, symbol, cost, qty, pnl, status, opened, closed, reason FROM positions WHERE version='vC'").fetchall()
    t0 = time.mktime(datetime.date.today().timetuple())
    closed = [r for r in rows if r[5] == "closed"]; today = [r for r in closed if (r[7] or 0) >= t0]
    realized = sum(r[4] or 0 for r in closed); openc = sum(r[2] or 0 for r in rows if r[5] == "open")
    equity = (float(cash[0]) + openc) if cash else start + realized
    wins = sum(1 for r in today if (r[4] or 0) > 0)
    names = list(ast.literal_eval(re.search(r"WALLETS\s*=\s*(\{.*?\})", open(os.path.join(D, "brain16.py")).read(), re.S).group(1)).keys())
    try: G = json.load(open(os.path.join(D, "brain16.json"))).get("grade", {})
    except Exception: G = {}
    try: dem = __import__("brain17").demoted
    except Exception: dem = lambda w: False
    wl = []
    for n in names:
        g = G.get(n) or {}; gr = g.get("g") or "grading"; why = g.get("why") or "first grade pending"
        try:
            if dem(n): gr, why = "demoted", "lost 3 copies in a row"
        except Exception: pass
        wl.append(dict(name=n, grade=gr, why=why))
    last = None
    for k, sym, ts, data in c.execute("SELECT kind, symbol, ts, data FROM events WHERE kind IN ('copy_signal','paper_buy','paper_exit','paper_partial') AND (kind='copy_signal' OR data LIKE '%\"book\": \"vC\"%' OR data LIKE '%copy_of%') ORDER BY id DESC LIMIT 1"):
        x = json.loads(data or "{}"); last = dict(kind={"copy_signal": "signal", "paper_buy": "buy", "paper_exit": "exit", "paper_partial": "partial"}.get(k, k), sym=(sym or "")[:14], who=x.get("who") or x.get("copy_of"), t=round(ts), pnl=x.get("pnl"))
    c.close()
    return dict(equity=round(equity, 2), start=start, today_pnl=round(sum(r[4] or 0 for r in today), 2), trades_today=len(today), trades=len(closed),
                open=sum(1 for r in rows if r[5] == "open"), win_rate=round(100 * wins / len(today)) if today else None, wallets=wl, last=last)
def ryder_events(n=25):
    """App voice/emote cues: recent MAIN-book (v3) paper events only. No addresses beyond symbols, no secrets."""
    import sqlite3
    c = sqlite3.connect(os.path.join(D, "desk.db")); c.row_factory = sqlite3.Row; out = []
    for r in c.execute("SELECT id, ts, kind, symbol, data FROM events WHERE kind IN ('paper_buy','paper_exit','kill','strong_agreement') AND ts>? ORDER BY id DESC LIMIT 400", (time.time() - 3 * 3600,)):
        x = json.loads(r["data"] or "{}"); book = x.get("book") or "v3"
        if r["kind"] in ("paper_buy", "paper_exit") and book != "v3": continue
        if r["kind"] == "kill" and not any(k in str(x.get("reason", "")) for k in RUG): continue
        e = dict(id=r["id"], t=round(r["ts"]), kind={"paper_buy": "buy", "paper_exit": "exit", "kill": "rug_dodged"}.get(r["kind"], r["kind"]), sym=(r["symbol"] or "")[:14])
        if r["kind"] == "paper_exit": e.update(pct=x.get("pct"), pnl=x.get("pnl"), reason=x.get("reason"))
        if r["kind"] == "kill": e["reason"] = x.get("reason")
        out.append(e)
        if len(out) >= n: break
    c.close(); return out[::-1]
def validate(d):  # mirrors app.js validate()
    for k in ['start','equity','cash','seen','passed','trades','wins','losses','nkills','realized']: assert isinstance(d[k], (int, float)), k
    assert d["start"] > 0 and isinstance(d["asof"], str)
    for k in ['opens','closed','agents','tail','curve','kills','by_dex']: assert isinstance(d[k], list), k
    for p in d["curve"]: assert isinstance(p["v"], (int, float))
    for p in d["opens"] + d["closed"]: assert isinstance(p["sym"], str) and isinstance(p["pnl"], (int, float)) and p["entry"] > 0
    for p in d["opens"]: assert all(isinstance(p[k], (int, float)) for k in ("now", "usd", "stop"))
    for p in d["closed"]: assert isinstance(p["pct"], (int, float)) and isinstance(p["exit"], (int, float))
    for p in d["by_dex"] + d["kills"]: assert isinstance(p[0], str) and isinstance(p[1], (int, float))
    for p in d["agents"]: assert isinstance(p["name"], str)
    for p in d["tail"]: assert isinstance(p["ag"], str)
def core(d):
    d = json.loads(json.dumps(d)); d.pop("asof", None); d.pop("updated_at", None)
    if d.get("curve"): d["curve"][-1].pop("t", None)
    return json.dumps(d, sort_keys=True)
def gh(method, body=None):
    tok = os.environ.get("RYDER_GITHUB_TOKEN")
    if not tok: raise RuntimeError("RYDER_GITHUB_TOKEN not set in environment")
    req = urllib.request.Request(API + ("?ref=main" if method == "GET" else ""), method=method,
        data=json.dumps(body).encode() if body else None,
        headers={"Authorization": "Bearer " + tok, "Accept": "application/vnd.github+json", "User-Agent": "ryder-night-desk", "X-GitHub-Api-Version": "2022-11-28"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r: return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"GitHub {method} failed: HTTP {e.code}") from None
def publish_once():
    d = build(); validate(d)
    cur = gh("GET"); old = base64.b64decode(cur.get("content", "")).decode() if cur.get("content") else "{}"
    try: same = core(json.loads(old)) == core(d)
    except Exception: same = False
    if same and "--skip-unchanged" in sys.argv: return "unchanged (skipped commit)"
    body = {"message": "stats update" if not same else "heartbeat", "content": base64.b64encode((json.dumps(d, indent=1) + "\n").encode()).decode(), "sha": cur["sha"], "branch": "main"}
    r = gh("PUT", body); return "pushed commit " + r["commit"]["sha"][:7]
if __name__ == "__main__":
    loop = "--loop" in sys.argv; interval = INTERVAL
    while True:
        try: msg = publish_once()
        except Exception as e: msg = f"error: {type(e).__name__}: {str(e)[:200]}"
        print(time.strftime("[%Y-%m-%d %H:%M:%S]"), msg, flush=True)
        if not loop: break
        time.sleep(interval)
