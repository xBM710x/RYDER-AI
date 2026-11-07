"""Decision operations: bounded evidence and isolated timing experiments. Paper only."""
import collections
import json
import math
import queue
import sqlite3
import threading
import time
from pathlib import Path
from decision_review import openings, obj
RELEASE='decision-ops-1'
DB=Path(__file__).resolve().parent/'decision-timing.db'
OFFERS=queue.Queue(maxsize=64)
THREAD=None
STATS=collections.Counter()


def number(v):
    if isinstance(v,bool): return None
    try: v=float(v)
    except (ValueError,TypeError): return None
    return v if math.isfinite(v) else None


def quote(p,now):
    p=p or {};px=number(p.get('priceUsd'));liq=number((p.get('liquidity') or {}).get('usd'));ts=number(p.get('_ts'))
    if px is None or liq is None or ts is None or px<=0 or liq<=0 or not 0<=now-ts<=30 or not p.get('pairAddress'): return None
    return dict(price=px,liquidity=liq,ts=ts,pool=p['pairAddress'])


def rank(pair,now):
    q=quote(pair,now)
    if not q:return dict(score=0,status='missing or stale market inputs')
    vol=number((pair.get('volume') or {}).get('m5'));tx=(pair.get('txns') or {}).get('m5') or {}
    b,s=number(tx.get('buys')),number(tx.get('sells'));momentum=number((pair.get('priceChange') or {}).get('m5'))
    if None in (vol,b,s,momentum) or min(vol,b,s)<0:return dict(score=0,status='missing tape inputs')
    score=min(30,q['liquidity']/25000*10)+min(30,vol/2000*10)+20*b/max(1,b+s)+max(0,20-abs(momentum-3)*2)
    return dict(score=round(score,2),status='priority only; all entry gates still apply')


def retryable(reason,pair,now):
    # Never retry a safety rejection through this path. Existing retry budget/TTL applies.
    if str(reason).startswith(('volume_1h:unknown','liquidity:unknown')):return True
    q=quote(pair,now)
    return bool(q and q['liquidity']>=18000 and str(reason).startswith(('volume_1h:fail','liquidity:fail')) and (number((pair.get('volume') or {}).get('h1')) or 0)>=7500)


def fill(px,size,liq,side):
    """Conservative constant-product approximation, not an executable route quote."""
    if side not in ('buy','sell'):return None
    if any(number(v) is None or v<=0 for v in (px,size,liq)) or size>liq*.01:return None
    impact=size/(liq/2+size);cost=.003+.01+impact
    return px*(1+cost if side=='buy' else max(0,1-cost))


def connect(path=DB):
    c=sqlite3.connect(str(path),timeout=1);c.row_factory=sqlite3.Row
    c.execute('PRAGMA journal_mode=WAL')
    c.execute('CREATE TABLE IF NOT EXISTS trials(mint TEXT, strategy TEXT, symbol TEXT, pool TEXT, offered REAL, initial REAL, low REAL, last REAL, last_ts REAL, trigger REAL, entry REAL, opened REAL, qty REAL, closed REAL, pnl REAL, status TEXT, PRIMARY KEY(mint,strategy))')
    c.commit();return c


def admit(c,signal,now):
    q=quote(signal['pair'],now)
    if not q:return
    if c.execute("SELECT COUNT(DISTINCT mint) FROM trials WHERE status IN ('watching','triggered','open')").fetchone()[0]>=24:return
    for strategy in ('breakout','pullback','continuation'):
        c.execute('INSERT OR IGNORE INTO trials VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(signal['mint'],strategy,signal['symbol'],q['pool'],now,q['price'],q['price'],q['price'],q['ts'],None,None,None,None,None,None,'watching'))
    c.commit()


def advance(c,market,now):
    for row in c.execute("SELECT * FROM trials WHERE status IN ('watching','triggered','open')").fetchall():
        r=dict(row);key=(r['mint'],r['strategy']);q=quote(market.get(r['mint']),now)
        if now-r['offered']>1800:
            c.execute("UPDATE trials SET status='unresolved',closed=? WHERE mint=? AND strategy=?",(now,)+key);continue
        if not q or q['pool']!=r['pool'] or q['ts']<=r['last_ts']:continue
        px=q['price'];low=min(r['low'],px)
        if r['status']=='watching':
            trigger=(px>=r['initial']*1.02 if r['strategy']=='breakout' else low<=r['initial']*.98 and px>=low*1.01 if r['strategy']=='pullback' else now-r['offered']>=30 and px>r['last']>=r['initial'])
            if trigger:c.execute("UPDATE trials SET status='triggered',trigger=? WHERE mint=? AND strategy=?",(now,)+key)
        elif r['status']=='triggered' and now-r['trigger']>=5:
            execution=fill(px,25,q['liquidity'],'buy')
            if execution:c.execute("UPDATE trials SET status='open',entry=?,opened=?,qty=? WHERE mint=? AND strategy=?",(execution,now,25/execution)+key)
        elif r['status']=='open' and now-r['opened']>=300:
            exit_px=fill(px,r['qty']*px,q['liquidity'],'sell')
            if exit_px:c.execute("UPDATE trials SET status='closed',closed=?,pnl=? WHERE mint=? AND strategy=?",(now,r['qty']*exit_px-25)+key)
        c.execute('UPDATE trials SET low=?,last=?,last_ts=? WHERE mint=? AND strategy=?',(low,px,q['ts'])+key)
    c.execute("DELETE FROM trials WHERE closed<?",(now-7*86400,));c.commit()


def offer(cd,pair,now):
    if not quote(pair,now):return
    try:OFFERS.put_nowait(dict(mint=cd['mint'],symbol=cd.get('name') or cd['mint'][:8],pair=pair))
    except queue.Full:STATS['queue_full']+=1


def worker():
    from common import dex_market
    while True:
        try:
            c=connect()
            try:
                now=time.time()
                for _ in range(24):
                    try:signal=OFFERS.get_nowait()
                    except queue.Empty:break
                    admit(c,signal,now)
                mints=[r[0] for r in c.execute("SELECT DISTINCT mint FROM trials WHERE status IN ('watching','triggered','open')")]
                advance(c,dex_market(mints) if mints else {},time.time())
                STATS['last_cycle']=time.time();STATS['cycles']+=1
            finally:c.close()
        except Exception:STATS['errors']+=1
        time.sleep(15)


def start():
    global THREAD
    if THREAD and THREAD.is_alive():return
    THREAD=threading.Thread(target=worker,daemon=True,name='decision-timing');THREAD.start()


def timing(path=DB):
    if not path.exists():return dict(status='awaiting worker',rows=[])
    c=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=1)
    try:
        rows=[dict(strategy=s,status=st,n=n,net=round(net,4) if net is not None else None) for s,st,n,net in c.execute('SELECT strategy,status,COUNT(*),SUM(pnl) FROM trials GROUP BY strategy,status')]
        return dict(status='isolated paper experiment',rows=rows)
    finally:c.close()


def report(db,hb,data,now,path=DB):
    latest={};errors=[]
    for ts,kind,mint,symbol,raw in db.execute("SELECT ts,kind,mint,symbol,data FROM events WHERE ts BETWEEN ? AND ? AND kind IN ('kill','skip','error','paper_buy','paper_sell','score') ORDER BY ts DESC,rowid DESC LIMIT 4000",(now-86400,now)):
        e=obj(raw)
        if kind=='error':
            if len(errors)<10:errors.append(dict(at=ts,where=e.get('where','unknown')))
            continue
        if not mint or mint in latest:continue
        latest[mint]=dict(symbol=symbol or mint[:8],mint=mint,at=ts,kind=kind,reason=e.get('detail') or e.get('reason') or kind,checks=e.get('checks') or {})
    blockers=[]
    for r in latest.values():
        if r['kind'] not in ('kill','skip'):continue
        checks=r['checks'];missing=[k for k,v in checks.items() if str(v).startswith('unknown')];failed=[k for k,v in checks.items() if str(v).startswith('fail')]
        blockers.append(dict(r,missing=missing,failed=failed,category='missing data' if missing else 'failed rule' if failed else 'recorded gate; details below'))
    trades=[t for t in openings(db,now) if t['closed']<=now]
    accountability=collections.defaultdict(lambda:dict(approve_gain=0,approve_loss=0,oppose_gain=0,oppose_loss=0,flat=0,net=0))
    replay=[]
    for t in trades:
        votes=(t['entry'].get('council') or {}).get('votes') or {}
        for agent,v in votes.items():
            score=number(v[0] if isinstance(v,list) and v else None)
            if score is None:continue
            a=accountability[agent];a['flat' if t['pnl']==0 else ('approve_' if score>=.5 else 'oppose_')+('gain' if t['pnl']>0 else 'loss')]+=1;a['net']+=t['pnl']
        if len(replay)<12:
            events=[]
            for ts,kind,raw in db.execute("SELECT ts,kind,data FROM events WHERE mint=? AND ts BETWEEN ? AND ? ORDER BY ts,rowid LIMIT 80",(t['mint'],t['opened'],t['closed'])):
                e=obj(raw)
                if e.get('book','v3')!=t['book']:continue
                events.append(dict(at=ts,kind=kind,reason=e.get('why') or e.get('reason') or e.get('detail'),votes=(e.get('council') or {}).get('votes')))
            replay.append(dict(symbol=t['symbol'],book=t['book'],net=t['pnl'],opened=t['opened'],closed=t['closed'],events=events,entry_features=t['entry'].get('intelligence_features'),fills=[dict(at=p['closed'],reason=p.get('reason'),price=p.get('exit'),net=p['pnl']) for p in t['parts']]))
    beat=number(hb.get('ts'));age=now-beat if beat is not None else None
    scan=db.execute("SELECT MAX(ts) FROM events WHERE kind='scan' AND ts<=?",(now,)).fetchone()[0]
    health=dict(heartbeat_age_s=age,scan_age_s=now-scan if scan is not None else None,runner_fresh=age is not None and 0<=age<120,errors=errors,queue=hb.get('scan_scheduler'),timing_worker=hb.get('decision_ops_worker'),last_publisher_report=data.get('updated_at'))
    readiness=[dict(check='Runner heartbeat',status='verified' if health['runner_fresh'] else 'blocked',detail='Fresh heartbeat under 120 seconds required'),dict(check='Completed paper evidence',status='review required',detail=str(len(trades))+' completed openings in bounded 7-day sample; count alone does not prove an edge'),dict(check='Executable fills and exit liquidity',status='unverified',detail='Paper impact model is not a confirmed route or sale'),dict(check='Wallet signing and order reconciliation',status='not enabled',detail='No live execution added'),dict(check='Failure recovery and live loss controls',status='unverified',detail='Requires fault-injection and execution integration tests')]
    return dict(release=RELEASE,at=now,runner_release=hb.get('decision_ops_release'),blockers=blockers[:25],blocker_counts=dict(collections.Counter(r['category'] for r in blockers)),ranked=hb.get('ranked_opportunities',[]),rechecks=hb.get('strategy_watch',[]),timing=timing(path),replays=replay,accountability=dict(accountability),health=health,readiness=readiness,live_ready=False,scope='Bounded last 24h decisions (4000 events), 7-day completed v3/vC openings (500 max). Agent outcomes are associations, not causal credit. Timing research includes filter-passed candidates, not execution-approved trades. No live orders or automatic strategy promotion.')
