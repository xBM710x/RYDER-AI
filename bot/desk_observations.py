"""Best-effort display telemetry in a separate database; never used to approve trades."""
import json
from contextlib import closing
import math
import sqlite3
import time
from pathlib import Path
DB = Path(__file__).resolve().parent/'desk-observations.db'

def finite(v):
    try:
        n=float(v)
        return n if math.isfinite(n) else None
    except (TypeError, ValueError): return None

def connect():
    c=sqlite3.connect(str(DB),timeout=.2);c.row_factory=sqlite3.Row
    c.execute('PRAGMA journal_mode=WAL')
    c.executescript('''CREATE TABLE IF NOT EXISTS tokens(mint TEXT PRIMARY KEY,symbol TEXT,source TEXT,dex TEXT,first_ts REAL,last_ts REAL,created REAL,price REAL,liquidity REAL,regime TEXT);
    CREATE TABLE IF NOT EXISTS equity(ts INTEGER PRIMARY KEY,value REAL,scope TEXT);
    CREATE INDEX IF NOT EXISTS tokens_last ON tokens(last_ts);''')
    return c

def observe(candidates,market,regime=None,clock=time.time):
    now=clock()
    with closing(connect()) as c:
        for cd in candidates[:120]:
            pair=market.get(cd['mint']) or {}
            created=finite(pair.get('pairCreatedAt'))
            c.execute('''INSERT INTO tokens VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(mint) DO UPDATE SET
              symbol=excluded.symbol,dex=excluded.dex,last_ts=excluded.last_ts,created=COALESCE(excluded.created,tokens.created),price=excluded.price,liquidity=excluded.liquidity,regime=excluded.regime''',
              (cd['mint'],(pair.get('baseToken') or {}).get('symbol') or cd.get('name') or cd['mint'][:8],cd.get('source') or 'Unknown',pair.get('dexId') or cd.get('dex') or 'Unknown',now,now,created/1000 if created else None,finite(pair.get('priceUsd')),finite((pair.get('liquidity') or {}).get('usd')),regime or 'Unknown'))
        c.commit()

def equity(value,scope,clock=time.time):
    if finite(value) is None:return
    with closing(connect()) as c:c.execute('INSERT OR REPLACE INTO equity VALUES(?,?,?)',(int(clock()//180)*180,value,scope));c.commit()

def snapshot(clock=time.time,scope='shared'):
    if not DB.exists():return [],[]
    c=sqlite3.connect(DB.as_uri()+'?mode=ro',uri=True,timeout=.2);c.row_factory=sqlite3.Row
    try:
        tokens=[dict(r) for r in c.execute('SELECT * FROM tokens ORDER BY last_ts DESC LIMIT 120')]
        curve=[dict(r) for r in c.execute('SELECT * FROM equity WHERE ts>=? AND scope=? ORDER BY ts',(clock()-7*86400,scope))]
        return tokens,curve
    finally:c.close()
