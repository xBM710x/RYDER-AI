"""RYDER supervisor (PAPER ONLY), cross-platform: Mac, Linux, Windows.
Loads .env (secrets stay in your environment, never printed), runs self-tests, then keeps
runner.py and publish.py alive. Restarts the runner if heartbeat.json goes stale (>180s).
Publisher only runs when RYDER_GITHUB_TOKEN is set (only ONE computer should publish)."""
import os, sys, time, subprocess, datetime, signal

# One supervisor per state directory, including manual starts after installation.
if os.name != "nt":
    import fcntl
    _lock = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "supervisor.lock"), "a")
    try: fcntl.flock(_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("RYDER is already running for this directory.", flush=True); sys.exit(0)

def _stop(signum, frame): raise KeyboardInterrupt
signal.signal(signal.SIGTERM, _stop)
D = os.path.dirname(os.path.abspath(__file__)); os.chdir(D)
def log(m):
    line = datetime.datetime.now().strftime("%F %T") + " " + m
    print(line, flush=True); open("supervisor.log", "a").write(line + "\n")
if os.path.exists(".env"):
    for l in open(".env", encoding="utf-8"):
        l = l.strip()
        if l and not l.startswith("#") and "=" in l:
            k, v = l.split("=", 1); v = v.strip().strip('"').strip("'")
            if v: os.environ.setdefault(k.strip(), v)
PY = sys.executable
log("self-tests starting")
t = subprocess.run([PY, "test_breakers.py"], capture_output=True, text=True)
fails = [l for l in t.stdout.splitlines() if l.startswith("FAIL")]
log(f"self-tests: {t.stdout.count('PASS')} pass, {len(fails)} fail" + (" -> " + "; ".join(fails) if fails else ""))
if t.returncode != 0 or fails: log("WARNING: self-tests failed; runner still starts but check runner.log")
def spawn(args, logf): return subprocess.Popen([PY, "-u"] + args, stdout=open(logf, "a"), stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
runner = pub = None; warned = False
try:
    while True:
        if runner is None or runner.poll() is not None:
            runner = spawn(["runner.py"], "runner.log"); log(f"runner (re)started PID {runner.pid}")
        if os.environ.get("RYDER_GITHUB_TOKEN"):
            if pub is None or pub.poll() is not None:
                pub = spawn(["publish.py", "--loop"], "publisher.log"); log(f"publisher (re)started PID {pub.pid}")
        elif not warned: log("publisher off: RYDER_GITHUB_TOKEN not set (app won't update)"); warned = True
        hb = "heartbeat.json"
        if os.path.exists(hb) and time.time() - os.path.getmtime(hb) > 180 and runner.poll() is None:
            log("runner heartbeat stale; restarting"); runner.kill(); runner.wait(); os.utime(hb, None)
        time.sleep(20)
except KeyboardInterrupt:
    log("stopping")
finally:
    for p in (runner, pub):
        if p and p.poll() is None: p.terminate()

    for p in (runner, pub):
        if p:
            try: p.wait(timeout=15)
            except subprocess.TimeoutExpired: p.kill(); p.wait()
