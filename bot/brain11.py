"""RYDER upgrades 491-540 (PAPER ONLY): network resilience (GeckoTerminal 429s), hang diagnostics, health reporting.
No trading bars or safety checks are changed here."""
import time, os, sys, threading, traceback, collections, json
from common import CFG, net_status, HEALTH
from logger import log
D = os.path.dirname(os.path.abspath(__file__)); HB = os.path.join(D, "heartbeat.json"); HANG = os.path.join(D, "hang.log")
STATS = collections.Counter(); _LAST_DUMP = [0]; LOOP_T = {}
SLOW = collections.deque(maxlen=30); SLOWAGG = collections.Counter()
CUR = {}
def timed(name, fn, *a):
    """532/533: time each positions-loop step; >3s -> 'slow_step' log + heartbeat list. CUR shows the step in progress for hang dumps."""
    t0 = time.time(); CUR["pos"] = (name, t0)
    try: return fn(*a)
    finally:
        dt = time.time() - t0; CUR.pop("pos", None)
        if dt > 3: SLOW.append((time.strftime("%H:%M:%S"), name, round(dt, 1))); SLOWAGG[name] += 1; log("slow_step", step=name, sec=round(dt, 1))
def tick(name): LOOP_T[name] = time.time()  # 506 per-loop liveness stamps
def _dump(why):
    """507/508: when a loop stalls, write every thread's stack to hang.log (max once per 10 min) so the root cause of
    stale-heartbeat restarts (13:26 and 13:40 PT today) can be found. No secrets: stack frames only."""
    if time.time() - _LAST_DUMP[0] < 600: return
    _LAST_DUMP[0] = time.time(); STATS["hang_dumps"] += 1
    fr = sys._current_frames(); names = {t.ident: t.name for t in threading.enumerate()}
    with open(HANG, "a") as f:
        f.write(f"\n===== {time.strftime('%F %T')} {why} | step in progress: {CUR.get('pos')}\n")
        for tid, st in fr.items(): f.write(f"--- thread {names.get(tid, tid)}\n" + "".join(traceback.format_stack(st)[-12:]))
    log("hang_dump", why=why, file="hang.log")
def watchdog():
    """509/510: independent thread. Positions loop silent 60s or scan loop silent 150s -> stack dump (before the supervisor's 180s kill)."""
    last = time.time()
    while True:
        time.sleep(10)
        try:
            now = time.time(); gap = now - last; last = now
            if gap > 40: continue  # whole-process pause (brain14 logs it); a stack dump now would only show the recovery
            for n, lim in (("pos", 30), ("scan", 100)):  # 536 dump at 30s so the stuck stack is captured before recovery
                t = LOOP_T.get(n)
                if t and now - t > lim: STATS["stall_" + n] += 1; _dump(f"{n} loop silent {now - t:.0f}s")
        except Exception: pass
def start(): threading.Thread(target=watchdog, daemon=True, name="b11-watchdog").start()
def status():
    """511-515: health block: per-host ok/err/latency, 429 cooldowns, cache hits/stale serves, loop ages, hang dumps."""
    now = time.time()
    return dict(net=net_status(), hosts={k: dict(ok=v.get("ok"), err=v.get("err"), ms=v.get("ms")) for k, v in HEALTH.items()},
                loop_age={k: round(now - v) for k, v in LOOP_T.items()}, stats=dict(STATS), slow=list(SLOW)[-8:], slow_by_step=dict(SLOWAGG), in_progress=CUR.get("pos"))
