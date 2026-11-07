"""Read-only operational evidence. No execution rules or strategy promotion."""
from collections import defaultdict, Counter
from decision_review import openings, obj
from decision_ops import number
from intelligence import regime
from session_research import session_start
RELEASE='desk-insights-1'

def fresh(ts,now,limit):
    ts=number(ts)
    return ts is not None and 0<=now-ts<=limit

def build(db,hb,data,now):
    events=[dict(at=t,kind=k,mint=m,symbol=s,detail=obj(raw)) for t,k,m,s,raw in db.execute('SELECT ts,kind,mint,symbol,data FROM events WHERE ts BETWEEN ? AND ? ORDER BY ts DESC,rowid DESC LIMIT 4000',(now-86400,now))]
    beat=fresh(hb.get('ts'),now,120)
    scan=next((r for r in events if r['kind']=='scan'),None)
    sources=[]
    for host,s in (hb.get('sources') or {}).items():
        ok=fresh(s.get('last_ok'),now,180)
        sources.append(dict(host=host,status='recent success' if ok else 'no recent success',last_ok=s.get('last_ok'),errors=s.get('err',0),successes=s.get('ok',0)))
    recent_scan=bool(scan and fresh(scan['at'],now,120))
    pending=[]
    for w in hb.get('watch',[])[:10]:
        seconds=number(w.get('wait_left'));ts=w.get('quote_ts')
        pending.append(dict(symbol=w.get('sym'),mint=w.get('mint'),strategy=w.get('strategy'),ready_at=hb.get('ts',now)+max(0,seconds) if seconds is not None and number(hb.get('ts')) is not None else None,status='waiting for entry recheck' if beat else 'stale runner report',next='Recheck quote, movement, risk and council; elapsed timer does not authorize a buy',quote_fresh=fresh(ts,now,30)))
    reasons=Counter()
    latest={}
    for r in events:
        if r['mint'] and r['mint'] not in latest and r['kind'] in ('kill','skip','paper_buy','score'):
            latest[r['mint']]=r
            if r['kind'] in ('kill','skip'):reasons[str(r['detail'].get('reason') or 'unknown')]+=1
    state='runner stale' if not beat else 'scanning stalled or unreported' if not recent_scan else 'entries pending recheck' if pending else 'evaluating; no pending entry reported'
    failures=[r for r in events if r['kind']=='error' and fresh(r['at'],now,300)]
    if beat and failures:state='recent worker errors; review required'
    if beat and hb.get('paused'):state='entries paused: '+str(hb['paused'])
    health=dict(state=state,heartbeat_at=hb.get('ts'),scan_at=scan['at'] if scan else None,sources=sources,recent_errors=[dict(at=r['at'],where=r['detail'].get('where','unknown')) for r in failures[:8]],recovery=hb.get('selfheal'),paused=hb.get('paused'),next='Inspect runner and updater logs' if not beat else 'Review recent worker errors' if failures else 'Observe next scan and entry recheck')
    mapping={'Scout':('scan',),'Filter':('kill','skip'),'Analyst':('score',),'Executor':('paper_buy','paper_sell'),'Risk':('paper_sell','kill'),'Logger':tuple({r['kind'] for r in events})}
    activity=[]
    for agent,kinds in mapping.items():
        r=next((r for r in events if r['kind'] in kinds),None)
        activity.append(dict(agent=agent,symbol=r['symbol'] if r else None,at=r['at'] if r else None,status='recent recorded event' if r and beat and fresh(r['at'],now,120) else 'last recorded event' if r else 'awaiting evidence',evidence=(r['detail'].get('detail') or r['detail'].get('reason') or r['kind']) if r else None,next='Inspect pending candidates' if agent=='Scout' else 'Review recorded gates' if agent=='Filter' else 'Compare score with outcomes' if agent=='Analyst' else 'Await validated paper entry or exit' if agent=='Executor' else 'Review exit and risk evidence' if agent=='Risk' else 'Record next decision'))
    trades=[t for t in openings(db,now) if t['closed']<=now]
    buckets=defaultdict(list);conditions=defaultdict(list);exits=[]
    for t in trades:
        e=t['entry'];condition=regime(e.get('intelligence_features') or {})
        conditions[(e.get('entry_strategy','unknown'),condition)].append(t)
        for name,v in ((e.get('council') or {}).get('votes') or {}).items():
            score=number(v[0]) if isinstance(v,list) and v else None
            if score is not None and 0<=score<=1:buckets[(name,'high' if score>=.7 else 'medium' if score>=.5 else 'low')].append((score,t['pnl']))
        peak_return=weighted_return=weight=0
        for p in t['parts']:
            entry,peak,end,cost=map(number,(p.get('entry'),p.get('peak'),p.get('exit'),p.get('cost')))
            if None in (entry,peak,end,cost) or min(entry,peak,end,cost)<=0:continue
            peak_return+=cost*(peak/entry-1);weighted_return+=cost*(end/entry-1);weight+=cost
        exits.append(dict(symbol=t['symbol'],book=t['book'],net=t['pnl'],capture_pct=round(100*weighted_return/peak_return,1) if weight==t['cost'] and peak_return>0 else None,giveback_pp=round(100*(peak_return-weighted_return)/weight,2) if weight==t['cost'] and weight>0 else None,note='Cost-weighted recorded exit versus recorded peak; peak timing and executable peak liquidity unknown'))
    confidence=[dict(agent=a,band=b,n=len(rows),mean_score=round(sum(s for s,p in rows)/len(rows),3),win_rate=round(sum(p>0 for s,p in rows)/len(rows),3),net=round(sum(p for s,p in rows),2),status='descriptive sample' if len(rows)>=30 else 'insufficient sample') for (a,b),rows in sorted(buckets.items())]
    conditions=[dict(strategy=s,condition=c,n=len(ts),net=round(sum(t['pnl'] for t in ts),2),wins=sum(t['pnl']>0 for t in ts),status='descriptive sample' if len(ts)>=30 else 'insufficient sample') for (s,c),ts in conditions.items()]
    missed=[]
    # Reuse recorded same-pool followups, then associate the actual preceding skip rule.
    for row in (data.get('session_research') or {}).get('replays',[])[:20]:
        entry=number(row.get('entry'));end=number(row.get('exit'));net=number(row.get('net'))
        if None in (entry,end,net) or not entry<end<=now:continue
        r=db.execute("SELECT data FROM events WHERE mint=? AND kind IN ('kill','skip') AND ts<=? ORDER BY ts DESC,rowid DESC LIMIT 1",(row['mint'],entry)).fetchone()
        missed.append(dict(row,reason=obj(r[0]).get('reason','unknown') if r else 'unknown',classification='positive modeled follow-up; inspect rule' if net>0 else 'nonpositive modeled follow-up'))
    start=session_start(now);session=[t for t in trades if start<=t['closed']<=now];wins=[t for t in session if t['pnl']>0];losses=[t for t in session if t['pnl']<0]
    top=reasons.most_common(1)
    recap=dict(start=start,completed=len(session),wins=len(wins),losses=len(losses),net=round(sum(t['pnl'] for t in session),2),worked=f'{len(wins)} profitable completed paper openings' if wins else 'No profitable completed opening in this sample',failed=f'{len(losses)} losing completed paper openings' if losses else 'No losing completed opening in this sample',experiment='Review '+top[0][0]+' in isolated matched follow-ups; retain live gates' if top else 'Collect completed opening evidence before proposing a rule change')
    return dict(release=RELEASE,at=now,activity=activity,pending=pending,health=health,missed=missed,exits=exits[:30],conditions=conditions,confidence=confidence,recap=recap,scope='Read-only: latest 4000 events/24h; completed main/shared openings up to 500/7d. Recap since 6 PM Pacific. Scores are not calibrated probabilities. Conditions describe token tape, not the entire market. Follow-ups are selected observations, not proof a skip was wrong. No strategy or exit-rule changes.')
