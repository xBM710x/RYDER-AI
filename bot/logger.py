"""Stage 6: Logger. SQLite (desk.db) + JSONL (events.jsonl)."""
import sqlite3, json, time, os
from common import CFG
D = os.path.dirname(os.path.abspath(__file__))
DB, JL = os.path.join(D, "desk.db"), os.path.join(D, "events.jsonl")
def conn():
    c = sqlite3.connect(DB, timeout=30); c.row_factory = sqlite3.Row
    c.executescript("""
    CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, ts REAL, kind TEXT, mint TEXT, symbol TEXT, data TEXT);
    CREATE TABLE IF NOT EXISTS seen(mint TEXT PRIMARY KEY, first_ts REAL, last_ts REAL, checks INT, done INT);
    CREATE TABLE IF NOT EXISTS positions(id INTEGER PRIMARY KEY, mint TEXT, symbol TEXT, pair TEXT, entry REAL, qty REAL,
      cost REAL, stop REAL, peak REAL, trailing INT, opened REAL, closed REAL, exit REAL, pnl REAL, reason TEXT, status TEXT);
    CREATE TABLE IF NOT EXISTS account(k TEXT PRIMARY KEY, v REAL);""")
    for t in ("events", "positions"):
        if "version" not in [r[1] for r in c.execute(f"PRAGMA table_info({t})")]:
            c.execute(f"ALTER TABLE {t} ADD COLUMN version TEXT DEFAULT 'v1'")
    if "tp_done" not in [r[1] for r in c.execute("PRAGMA table_info(positions)")]: c.execute("ALTER TABLE positions ADD COLUMN tp_done INT DEFAULT 0")
    return c
def log(kind, mint=None, symbol=None, **data):
    ts = time.time(); rec = dict(ts=ts, time=time.strftime("%Y-%m-%d %H:%M:%S"), kind=kind, version=CFG["VERSION"], mint=mint, symbol=symbol, **data)
    with open(JL, "a") as f: f.write(json.dumps(rec, default=str) + "\n")
    c = conn(); c.execute("INSERT INTO events(ts,kind,mint,symbol,data,version) VALUES(?,?,?,?,?,?)", (ts, kind, mint, symbol, json.dumps(data, default=str), CFG["VERSION"])); c.commit(); c.close()
    print(f"[{rec['time']}] {kind:<10} {symbol or ''} {mint or ''} {json.dumps(data, default=str)[:300]}", flush=True)
