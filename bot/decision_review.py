"""Bounded, read-only research: opening-level results, sampled skips and exit evidence."""
import collections
import json
import math
import time

BOOKS=('v3','vC')
def num(v):
    return isinstance(v,(float,int)) and not isinstance(v,bool) and math.isfinite(v)
def obj(v):
    try:
        x=json.loads(v or '{}');return x if isinstance(x,dict) else {}
    except (TypeError,ValueError):return {}
def openings(c,now):
    out=[]
    groups=c.execute("SELECT mint,version,opened,MAX(closed) ended FROM positions WHERE version IN ('v3','vC') GROUP BY mint,version,opened HAVING ended>=? ORDER BY ended DESC LIMIT 500",(now-7*86400,)).fetchall()
    for g in groups:
        ps=[dict(r) for r in c.execute('SELECT * FROM positions WHERE mint=? AND version=? AND opened=?',tuple(g)[:3])]
        if any(p['status']!='closed' for p in ps):continue
        if any(not num(p.get('pnl')) or not num(p.get('cost')) or p['cost']<=0 for p in ps):continue
        ev=[(r[0],obj(r[1])) for r in c.execute("SELECT ts,data FROM events WHERE mint=? AND kind='paper_buy' AND ts BETWEEN ? AND ? ORDER BY ABS(ts-?) LIMIT 30",(g['mint'],g['opened']-1,g['opened']+5,g['opened']))]
        e=next((d for t,d in ev if d.get('book','v3')==g['version']),{})
        pnl=sum(p['pnl'] for p in ps);cost=sum(p['cost'] for p in ps)
        out.append(dict(mint=g['mint'],book=g['version'],opened=g['opened'],closed=g['ended'],symbol=ps[-1].get('symbol') or g['mint'][:8],pnl=round(pnl,6),cost=cost,net_pct=pnl/cost*100,entry=e,parts=ps))
    return out

def build(c,hb=None,clock=time.time):
    now=clock();trades=openings(c,now);sources={};replays=[]
    for t in trades:
        e=t['entry'];source=str(e.get('source') or 'Unknown');dex=str(e.get('dex') or 'Unknown');k=(source,dex)
        s=sources.setdefault(k,dict(source=source,dex=dex,openings=0,wins=0,realized=0,cost=0,curve=[]))
        s['openings']+=1;s['wins']+=t['pnl']>0;s['realized']+=t['pnl'];s['cost']+=t['cost'];s['curve'].append(dict(t=t['closed'],v=t['pnl']))
        parts=sorted(t['parts'],key=lambda p:p['closed']);entry=parts[0].get('entry');peaks=[p['peak'] for p in parts if num(p.get('peak')) and p['peak']>0]
        peak=max(peaks) if peaks else None;end=parts[-1].get('exit');valid=num(entry) and entry>0
        peakpct=(peak/entry-1)*100 if valid and peak else None
        exitpct=(end/entry-1)*100 if valid and num(end) else None
        replays.append(dict(symbol=t['symbol'],mint=t['mint'],book=t['book'],opened=t['opened'],closed=t['closed'],net_pct=round(t['net_pct'],2),pnl=round(t['pnl'],2),peak_pct=round(peakpct,2) if peakpct is not None else None,giveback_pp=round(max(0,peakpct-exitpct),2) if peakpct is not None and exitpct is not None else None,reason=parts[-1].get('reason'),points=[dict(t=t['opened'],v=0)]+[dict(t=p['closed'],v=round((p['exit']/entry-1)*100,2)) for p in parts if valid and num(p.get('exit'))],fills=len(parts)))
    for s in sources.values():
        running=0
        for p in sorted(s['curve'],key=lambda p:p['t']):running+=p['v'];p['v']=round(running,2)
        s['curve'].sort(key=lambda p:p['t']);s['realized']=round(s['realized'],2);s['net_pct']=round(s['realized']/s['cost']*100,2);s['win_rate']=round(s['wins']/s['openings']*100,1)
    tables={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")};follow={}
    for table,fields in [('counterfactual','mint,rule,px0,px1,ts'),('audit','mint,reason,kill_px,later_px,ts')]:
        if table not in tables:continue
        for m,r,a,b,ts in c.execute('SELECT '+fields+' FROM '+table+' WHERE ts BETWEEN ? AND ? ORDER BY ts DESC LIMIT 500',(now-86400,now)):
            if m in follow:continue
            ok=num(a) and a>0 and num(b) and b>0;change=(b/a-1)*100 if ok else None
            if change is not None and not num(change):change=None
            skip=c.execute("SELECT ts,symbol FROM events WHERE mint=? AND kind IN ('kill','skip') AND ts<=? ORDER BY ts DESC LIMIT 1",(m,ts)).fetchone()
            follow[m]=dict(mint=m,symbol=skip['symbol'] if skip else m[:8],reason=r,change_pct=round(change,2) if change is not None else None,checked_at=ts,horizon_s=round(ts-skip['ts']) if skip else None,evidence=table)
    rows=list(follow.values());measured=[x for x in rows if x['change_pct'] is not None]
    skips={r[0] for r in c.execute("SELECT mint FROM events WHERE kind IN ('kill','skip') AND ts>=? ORDER BY ts DESC LIMIT 4000",(now-86400,)) if r[0]};universe=skips|set(follow)
    return dict(schema=1,generated_at=now,sources=sorted(sources.values(),key=lambda s:-s['realized']),missed=dict(universe=len(universe),measured=len(measured),unknown=len(universe)-len(measured),rows=rows[:30]),replays=replays[:30],scope='Last 7 days completed main/shared openings (maximum 500); last 24h sampled skipped-token follow-ups. Residual open positions excluded. Source means discovery origin; DEX shown separately.',note='Raw follow-up price changes are not executable returns. Unknown baseline timing stays unknown. Exit lines connect recorded fills only; peaks have no recorded timestamp and are not plotted at invented times. Paper results include ledger modeled costs; no strategy is promoted.')
