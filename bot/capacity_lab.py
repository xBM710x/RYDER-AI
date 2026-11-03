"""Separate paper capacity experiment: same eligible signals, 4 vs 8 entries/hour.
No real orders, no shared-account writes, no automatic promotion. One worker owns its DB.
"""
import collections
import math
import queue
import sqlite3
import threading
import time
from pathlib import Path
DB=Path(__file__).resolve().parent/'capacity-lab.db'
QUEUE=queue.Queue(maxsize=120)
STATS=collections.Counter();_THREAD=None
BOOKS={'control':4,'challenger':8};FEE=.003;SLIP=.01

def positive(x):
    try:v=float(x);return v if math.isfinite(v) and v>0 else None
    except (TypeError,ValueError):return None

def offer(mint,symbol,pair,score,source=None,clock=time.time):
    """Called only after executor hard/risk gates; enqueue never blocks the trader."""
    now=clock();px=positive(pair.get('priceUsd'));liq=positive((pair.get('liquidity') or {}).get('usd'));ts=positive(pair.get('_ts'))
    if not px or not liq or not ts or not 0<=now-ts<=30:return False
    try:QUEUE.put_nowait(dict(mint=mint,symbol=symbol,quote=px,liq=liq,observed=ts,offered=now,score=score,source=source or 'Unknown'));return True
    except queue.Full:STATS['overflow']+=1;return False

def connect():
    c=sqlite3.connect(str(DB),timeout=1);c.row_factory=sqlite3.Row;c.execute('PRAGMA journal_mode=WAL')
    c.executescript('''CREATE TABLE IF NOT EXISTS wallets(book TEXT PRIMARY KEY,cash REAL);
    CREATE TABLE IF NOT EXISTS fills(id INTEGER PRIMARY KEY,book TEXT,mint TEXT,symbol TEXT,source TEXT,opened REAL,entry REAL,qty REAL,cost REAL,peak REAL,mark REAL,mark_ts REAL,closed REAL,exit REAL,pnl REAL,reason TEXT);
    CREATE TABLE IF NOT EXISTS signals(mint TEXT,ts REAL,source TEXT,PRIMARY KEY(mint,ts));''')
    for book in BOOKS:c.execute('INSERT OR IGNORE INTO wallets VALUES(?,300)',(book,))
    c.commit();return c

def slip_cost(size,liq):return min(.02,.0015+size/liq)

def enter(c,signal,clock=time.time):
    now=clock()
    if not 0<=now-signal['observed']<=30 or not positive(signal.get('quote')) or not positive(signal.get('liq')):return
    # One eligibility observation per mint per minute; neither book gets duplicate signals.
    ts=int(signal['offered']//60)*60
    if c.execute('SELECT 1 FROM signals WHERE mint=? AND ts=?',(signal['mint'],ts)).fetchone():return
    c.execute('INSERT INTO signals VALUES(?,?,?)',(signal['mint'],ts,signal['source']))
    day0=int(now//86400)*86400
    for book,limit in BOOKS.items():
        if c.execute('SELECT 1 FROM fills WHERE book=? AND mint=? AND closed IS NULL',(book,signal['mint'])).fetchone():continue
        if c.execute('SELECT COUNT(*) FROM fills WHERE book=? AND opened>?',(book,now-3600)).fetchone()[0]>=limit:continue
        if c.execute('SELECT COALESCE(SUM(pnl),0) FROM fills WHERE book=? AND closed>=?',(book,day0)).fetchone()[0]<=-45:continue
        cash=c.execute('SELECT cash FROM wallets WHERE book=?',(book,)).fetchone()[0]
        cost=c.execute('SELECT COALESCE(SUM(cost),0) FROM fills WHERE book=? AND closed IS NULL',(book,)).fetchone()[0]
        if c.execute('SELECT COUNT(*) FROM fills WHERE book=? AND closed IS NULL',(book,)).fetchone()[0]>=10:continue
        size=min(cash,.10*(cash+cost))
        if size<5:continue
        entry=signal['quote']*(1+SLIP)/(1-FEE)*(1+slip_cost(size,signal['liq']))
        if not math.isfinite(size/entry):continue
        c.execute('INSERT INTO fills(book,mint,symbol,source,opened,entry,qty,cost,peak,mark,mark_ts) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(book,signal['mint'],signal['symbol'],signal['source'],now,entry,size/entry,size,entry,signal['quote'],signal['observed']))
        c.execute('UPDATE wallets SET cash=cash-? WHERE book=?',(size,book))
    c.commit()

def mark(c,market,clock=time.time):
    now=clock()
    for row in c.execute('SELECT * FROM fills WHERE closed IS NULL').fetchall():
        p=dict(row);pr=market.get(p['mint']) or {};quote=positive(pr.get('priceUsd'));ts=positive(pr.get('_ts'));liq=positive((pr.get('liquidity') or {}).get('usd'))
        if not quote or not liq or not ts or not 0<=now-ts<=30:STATS['missing_or_stale_marks']+=1;continue
        peak=max(p['peak'],quote);stop=max(p['entry']*.92,peak*.92 if peak>=p['entry']*1.15 else 0)
        c.execute('UPDATE fills SET peak=?,mark=?,mark_ts=? WHERE id=?',(peak,quote,ts,p['id']))
        reason='stop_or_trail' if quote<=stop else '30m_time_exit' if now-p['opened']>=1800 else None
        if reason:
            exit=quote*(1-SLIP)*(1-FEE)*(1-slip_cost(p['qty']*quote,liq));proceeds=p['qty']*exit;pnl=proceeds-p['cost']
            c.execute('UPDATE fills SET closed=?,exit=?,pnl=?,reason=? WHERE id=? AND closed IS NULL',(now,exit,pnl,reason,p['id']))
            c.execute('UPDATE wallets SET cash=cash+? WHERE book=?',(proceeds,p['book']))
    c.commit()

def run():
    while True:
        c=None
        try:
            c=connect();signals=[]
            for _ in range(30):
                try:signals.append(QUEUE.get_nowait())
                except queue.Empty:break
            for s in signals:enter(c,s)
            mints=[r[0] for r in c.execute('SELECT DISTINCT mint FROM fills WHERE closed IS NULL')]
            if mints:
                from common import dex_market
                mark(c,dex_market(mints))
            STATS['cycles']+=1
        except Exception:STATS['errors']+=1
        finally:
            if c:c.close()
        time.sleep(15)

def start():
    global _THREAD
    if _THREAD and _THREAD.is_alive():return
    _THREAD=threading.Thread(target=run,daemon=True,name='capacity-lab');_THREAD.start()

def summary(clock=time.time):
    if not DB.exists():return dict(status='collecting fully eligible signals',books=[],stats=dict(STATS))
    c=sqlite3.connect(DB.as_uri()+'?mode=ro',uri=True,timeout=1);c.row_factory=sqlite3.Row
    try:
        rows=[]
        for book,limit in BOOKS.items():
            cash=c.execute('SELECT cash FROM wallets WHERE book=?',(book,)).fetchone()[0]
            p=[dict(r) for r in c.execute('SELECT * FROM fills WHERE book=?',(book,))]
            opened=[r for r in p if r['closed'] is None];closed=[r for r in p if r['closed'] is not None]
            stale=sum(clock()-r['mark_ts']>30 for r in opened)
            rows.append(dict(book=book,max_entries_per_hour=limit,cash=round(cash,2),equity=round(cash+sum(r['qty']*r['mark'] for r in opened),2) if not stale else None,open=len(opened),closed=len(closed),realized=round(sum(r['pnl'] for r in closed),2),stale_marks=stale))
        return dict(status='paper-only capacity study',books=rows,stats=dict(STATS),note='Two separate simulated $300 balances; not the main/shared account. Same qualified signals, entry model and simple exits; only hourly capacity differs. Not a replay of the full main exit strategy. UTC day loss cap $45. Missing/stale quotes never trigger fills. No automatic promotion.')
    finally:c.close()
