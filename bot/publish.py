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
    return d
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
