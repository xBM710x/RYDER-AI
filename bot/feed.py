"""v3 live launch feed: PumpPortal public websocket (subscribeNewToken), read-only, no key. Falls back silently to polling."""
import json, threading, time, collections
NEW = collections.deque(maxlen=500); STATS = dict(connected=False, events=0, last=0, err="")
def _run():
    import websocket
    while True:
        try:
            w = websocket.create_connection("wss://pumpportal.fun/api/data", timeout=60)
            w.send(json.dumps({"method": "subscribeNewToken"})); w.send(json.dumps({"method": "subscribeMigration"})); STATS["connected"] = True  # 101: graduations too
            while True:
                try: m = json.loads(w.recv())
                except websocket.WebSocketTimeoutException:
                    if time.time() - (STATS.get('last') or time.time()) > 300: STATS['reconnects'] = STATS.get('reconnects', 0) + 1; STATS['last'] = time.time(); w.close(); break  # 184
                    continue
                if m.get("mint") and m.get("txType") == "migrate":
                    NEW.append(dict(mint=m["mint"], name="", source="pumpportal-migration", dex="pumpswap", creator=None, t=time.time())); STATS["migrations"] = STATS.get("migrations", 0) + 1
                elif m.get("mint"):
                    NEW.append(dict(mint=m["mint"], name=m.get("symbol") or m.get("name") or "", source="pumpportal-ws",
                                    dex="pumpfun", creator=m.get("traderPublicKey"), t=time.time()))
                    __import__('brain2').watch_launch(m['mint']); STATS["events"] += 1; STATS["last"] = time.time()
        except Exception as e:
            STATS["connected"] = False; STATS["err"] = str(e)[:120]; time.sleep(15)
def start():
    try: import websocket  # noqa
    except ImportError: STATS["err"] = "websocket-client not installed"; return
    threading.Thread(target=_run, daemon=True).start()
def drain():
    out = []
    while NEW: out.append(NEW.popleft())
    return out
