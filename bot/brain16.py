"""Copy-trade PAPER desk 'vC' + wallet grading + scale-outs (2026-10-31, approved by Braydon). READ-ONLY wallet reads, no keys, no signing, no orders.
Wallets: fomo.family 30-day leaderboard traders; addresses from public third-party trackers that match them on-chain to the trader's Fomo trades
(fomoradar.io / fomoapi.io pages, fetched 2026-10-30 23:58 PT). Each was confirmed active on-chain (getSignaturesForAddress) before use.
- Poll: one wallet every ~20s (each ~2 min): token balances via getTokenAccountsByOwner (both token programs). Balance up = buy, down = sell (fraction).
- Copy buy: detected buy -> 30s realistic delay -> skip if price ran +10% from detection (chase guard) -> FULL filters.check (every rug/safety
  check, FOMO-floor volume/liquidity $4K/$6K, NOT main bars) -> paper buy on vC at 5% of desk equity. Only wallets graded 'good'.
- Copy sell: wallet sells fraction f of a coin we hold on vC -> we sell f too (f >= 90% -> full exit).
- Grading: per wallet+coin, count buy increments and sell decrements seen. Bad: any coin with 10+ buys and <= 1 sell. Good: >= 4 coins traded,
  median buys/coin <= 3 and >= half of exited coins scaled out (2+ sells). Bootstrapped from the last 40 transactions per wallet, regraded every 6h."""
import time, json, os, threading, collections, statistics
from common import rpc, dex_market
from logger import conn, log
D = os.path.dirname(os.path.abspath(__file__)); SF = os.path.join(D, "brain16.json"); DESK = "vC"
WALLETS = {"bystevenr": "AH75Bn6QHSt5K2Ad4p1otns3JTwpSJWZTwiwKWNhmnKx", "vvvvvvvvvv": "4Bc4Ue2G37zoQCiksAvwMgXQQJFKcYQThnoHPKizAmWB",
           "G41T3R98": "4t5cayg6FDWkyQwyuYq9DqcRRCQ7e6JXyf9J7f2wfZQW", "awtorkowski7": "7zs3Cda5C8XWadmFKKfuPyXpo78F5AFY6RXQ3Ec5p9k7",
           "SavageCountry": "CdMRJEA33ee3JsLjMNkc9LohTkczSpom63vkyRu988qa", "OinkersRUs": "DPAN2Vig8BokpQCCu4mtV1mTWYLS7ktKe1hHKVBcsayL"}
NOT_FOUND = {"tikitikitrader": "only a shortened address (GDpq…jQrN) is public; full address needs a paid/keyed API -> not guessed"}
PROGS = ("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA", "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb")
SKIP = {"So11111111111111111111111111111111111111112", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"}
DELAY = 30; CHASE = 0.10; SIZE_MULT = 0.5; STATS = collections.Counter(); _L = threading.Lock()
def _load():
    try: return json.load(open(SF))
    except Exception: return {}
S = _load(); [S.setdefault(k, v) for k, v in dict(bal={}, hist={}, grade={}, graded_at=0, boot={}).items()]
PENDING = {}  # mint -> dict(t, px0, sym, who)
def save():
    with _L:
        try: json.dump(S, open(SF + ".tmp", "w")); os.replace(SF + ".tmp", SF)
        except Exception: pass
def balances(addr):
    out = {}
    for pg in PROGS:
        for a in (rpc("getTokenAccountsByOwner", [addr, {"programId": pg}, {"encoding": "jsonParsed"}]) or {}).get("value", []):
            i = a["account"]["data"]["parsed"]["info"]; amt = float(i["tokenAmount"]["uiAmount"] or 0)
            if i["mint"] not in SKIP: out[i["mint"]] = out.get(i["mint"], 0) + amt
    return out
def _h(who, m): return S["hist"].setdefault(who, {}).setdefault(m, [0, 0])  # [buys, sells]
# ---------- grading ----------
def grade(who):
    h = S["hist"].get(who) or {}
    if not h: return "ungraded", "no trades seen yet"
    bad = [m for m, (b, s) in h.items() if b >= 10 and s <= 1]
    if bad: return "bad", f"{len(bad)} coin(s) bought 10+ times with <=1 sell"
    bs = [b for b, s in h.values() if b]; ex = [(b, s) for b, s in h.values() if s]
    if len(bs) < 4: return "ungraded", f"only {len(bs)} coins seen"
    med = statistics.median(bs); scaled = sum(1 for b, s in ex if s >= 2) / max(1, len(ex))
    if med <= 3 and scaled >= 0.5: return "good", f"{len(bs)} coins, median {med:g} buys/coin, {scaled:.0%} of exits scaled out"
    return "ok", f"{len(bs)} coins, median {med:g} buys/coin, {scaled:.0%} scaled out (not copied)"
def bootstrap(who, addr, n=40):
    """Read the wallet's last n transactions once (pre/post token balances owned by the wallet) to seed buy/sell counts."""
    if S["boot"].get(who): return
    sg = rpc("getSignaturesForAddress", [addr, {"limit": n}]) or []; seen = 0
    for x in sg:
        if x.get("err"): continue
        try: t = rpc("getTransaction", [x["signature"], {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}])
        except Exception: continue
        if not t: continue
        pre = {b["mint"]: float(b["uiTokenAmount"]["uiAmount"] or 0) for b in t["meta"].get("preTokenBalances") or [] if b.get("owner") == addr}
        post = {b["mint"]: float(b["uiTokenAmount"]["uiAmount"] or 0) for b in t["meta"].get("postTokenBalances") or [] if b.get("owner") == addr}
        for m in set(pre) | set(post):
            if m in SKIP: continue
            d = post.get(m, 0) - pre.get(m, 0)
            if d > 0: _h(who, m)[0] += 1
            elif d < 0: _h(who, m)[1] += 1
        seen += 1; time.sleep(0.4)
    S["boot"][who] = dict(t=round(time.time()), txs=seen); STATS["boot_txs"] += seen
def regrade():
    for who, addr in WALLETS.items():
        try: bootstrap(who, addr)
        except Exception as e: STATS["boot_err"] += 1
        g, why = grade(who); old = (S["grade"].get(who) or {}).get("g")
        S["grade"][who] = dict(g=g, why=why, at=round(time.time()))
        if g != old: log("copy_grade", who=who, grade=g, why=why)
    S["graded_at"] = time.time(); save()
# ---------- polling ----------
_I = [0]
def poll_one():
    names = list(WALLETS); who = names[_I[0] % len(names)]; _I[0] += 1; addr = WALLETS[who]
    new = balances(addr); old = S["bal"].get(who)
    S["bal"][who] = new
    if old is None: return
    for m in set(new) | set(old):
        a, b = new.get(m, 0), old.get(m, 0)
        if a > b * 1.01 and a > 0:
            _h(who, m)[0] += 1; STATS["seen_buy"] += 1
            if (S["grade"].get(who) or {}).get("g") == "good" and m not in PENDING: on_buy(who, m)
        elif a < b * 0.99:
            _h(who, m)[1] += 1; STATS["seen_sell"] += 1; on_sell(who, m, (b - a) / b if b else 1.0)
def on_buy(who, m):
    p = dex_market([m]).get(m)
    if not p or not p.get("priceUsd"): STATS["copy_no_pair"] += 1; return
    PENDING[m] = dict(t=time.time(), px0=float(p["priceUsd"]), sym=(p.get("baseToken") or {}).get("symbol") or m[:6], who=who)
    log("copy_signal", m, PENDING[m]["sym"], who=who, px=PENDING[m]["px0"], book=DESK)
def on_sell(who, m, frac):
    c = conn(); ps = [dict(r) for r in c.execute("SELECT * FROM positions WHERE status='open' AND version=? AND mint=?", (DESK, m))]; c.close()
    if not ps: return
    p = ps[0]; pr = dex_market([m]).get(m)
    if not pr or not pr.get("priceUsd"): return
    import executor; px = float(pr["priceUsd"])
    if frac >= 0.9: executor.sell(p, px, f"copy_exit:{who}")
    else: executor.partial(p, px, (p.get("tp_done") or 0) + 1, frac=frac, reason=f"copy_sell:{who}")
    STATS["copy_sells"] += 1
def run_pending():
    import filters, executor
    for m, d in list(PENDING.items()):
        if time.time() - d["t"] < DELAY: continue
        PENDING.pop(m, None)
        p = dex_market([m]).get(m)
        if not p or not p.get("priceUsd"): continue
        px = float(p["priceUsd"])
        if px > d["px0"] * (1 + CHASE): log("skip", m, d["sym"], reason="copy_chased", move=round(px / d["px0"] - 1, 3), book=DESK); STATS["copy_chased"] += 1; continue
        res = filters.check(m, p, relax=0.15)  # every safety check; volume/liquidity at the FOMO floors ($4K/$6K)
        ok, why = filters.verdict(res)
        if not ok: log("kill", m, d["sym"], reason="copy_" + why.split(":")[0], detail=why, final=True, book=DESK); STATS["copy_rejected"] += 1; continue
        if executor.buy(m, d["sym"], p, 0, ver=DESK, mult=SIZE_MULT, extra=dict(copy_of=d["who"], copy=True)): STATS["copy_buys"] += 1
# ---------- scale-outs (v3x + vC) ----------
TIERS = {"v3x": [(0.40, 0.25), (0.80, 0.25)], DESK: [(0.20, 0.25), (0.50, 0.25), (1.00, 0.25)]}
def scale_out(p, price):
    """Partial take-profits as price runs: v3x adds +40% / +80% tiers on top of its existing first partial; vC sells 25% at +20/+50/+100%.
    Main desk untouched. Returns True if a piece was sold."""
    t = TIERS.get(p.get("version")); 
    if not t: return False
    done = p.get("tp_done") or 0; g = price / p["entry"] - 1
    base = 1 if p.get("version") == "v3x" else 0  # v3x: tier 0 is its existing +15%/brain9 partial
    i = done - base
    if 0 <= i < len(t) and g >= t[i][0]:
        import executor; executor.partial(p, price, done + 1, frac=t[i][1], reason=f"scale_out_{int(t[i][0]*100)}"); STATS["scale_out"] += 1; return True
    return False
def job_loop():
    k = 0
    while True:
        k += 1
        try:
            if time.time() - S["graded_at"] > 6 * 3600: regrade()
            poll_one(); run_pending()
            if k % 15 == 0: save()
        except Exception as e: STATS["err"] += 1; log("error", where="brain16", trace=str(e)[:200]) if STATS["err"] % 20 == 1 else None
        time.sleep(20)
def start(): threading.Thread(target=job_loop, daemon=True, name="b16-copy").start()
def status():
    return dict(stats=dict(STATS), wallets={w: dict(addr=a[:4] + "…" + a[-4:], grade=(S["grade"].get(w) or {}).get("g"), why=(S["grade"].get(w) or {}).get("why")) for w, a in WALLETS.items()},
                not_found=NOT_FOUND, pending=len(PENDING))
