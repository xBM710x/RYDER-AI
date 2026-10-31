"""Telegram phone alerts (PAPER ONLY). Token from env RYDER_TELEGRAM_TOKEN only; never logged. chat_id kept in .tg_chat (not in repo)."""
import os, json, time, threading, urllib.request, urllib.parse
D = os.path.dirname(os.path.abspath(__file__)); CF = os.path.join(D, ".tg_chat"); _last_find = [0.0]
def _api(method, **params):
    tok = os.environ.get("RYDER_TELEGRAM_TOKEN")
    if not tok: return None
    data = urllib.parse.urlencode(params).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(f"https://api.telegram.org/bot{tok}/{method}", data=data), timeout=15) as r: return json.loads(r.read())
    except Exception as e: return {"ok": False, "err": type(e).__name__}
def chat_id():
    try: return open(CF).read().strip() or None
    except Exception: pass
    if time.time() - _last_find[0] < 60: return None
    _last_find[0] = time.time(); r = _api("getUpdates") or {}
    for u in reversed(r.get("result") or []):
        ch = ((u.get("message") or {}).get("chat") or {})
        if ch.get("type") == "private" and ch.get("id"):
            open(CF, "w").write(str(ch["id"])); os.chmod(CF, 0o600); return str(ch["id"])
    return None
def send(text):
    cid = chat_id()
    if not cid: return False
    r = _api("sendMessage", chat_id=cid, text=text, disable_web_page_preview="true") or {}
    return bool(r.get("ok"))
def send_async(text): threading.Thread(target=send, args=(text,), daemon=True).start()
fmt = lambda v: f"{v:.3g}" if v < 1 else f"{v:,.2f}"
def on_buy(sym, usd, price, score, stop, liq, url, book, why=None):
    if book.endswith("b") or book.endswith("x"): return
    send_async(("📋 COPY " if book == "vC" else "") + f"🟢 RYDER BUY (paper)\n{sym} · ${usd:.2f} at ${fmt(price)}\nScore {score} · stop −{(1-stop/price)*100:.1f}% · liq ${liq or 0:,.0f}\n" + (f"🧠 {why[:1400]}\n" if why else "") + f"{url or ''}")
def on_exit(sym, pct, pnl, reason, book, extra=""):
    if book.endswith("b") or book.endswith("x"): return
    icon = "🏆" if reason == "partial_tp" else ("✅" if pnl > 0 else "🔴")
    label = "PARTIAL TP" if reason == "partial_tp" else ("WIN" if pnl > 0 else "STOP/SELL")
    send_async(f"{icon} RYDER {label} (paper)\n{sym} · {pct:+.1f}% · ${pnl:+.2f}\nreason: {reason.replace('_', ' ')}" + (f" · {extra}" if extra else "") + "\n" + __import__("brain7").why_exit(reason))  # 298 / 355
_hello = [False]; _recap = [""]
def tick(recap_fn=None):
    """Called every ~60s by runner: find chat_id (sends the connect message once) and send the 7 AM PT recap."""
    if not os.environ.get("RYDER_TELEGRAM_TOKEN"): return
    had = os.path.exists(CF); cid = chat_id()
    if cid and not had and not _hello[0]:
        _hello[0] = send("RYDER alerts connected ⭐ (paper only)")
        open(os.path.join(D, ".tg_hello"), "w").write("delivered" if _hello[0] else "failed")
    lt = time.localtime(); day = time.strftime("%F")
    if cid and recap_fn and lt.tm_hour == 7 and _recap[0] != day:
        _recap[0] = day; send(recap_fn())
