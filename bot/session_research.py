"""Evidence for the session recap and six paper research views."""
from collections import Counter, defaultdict
from datetime import datetime, timedelta, time as day_time
from statistics import median
from zoneinfo import ZoneInfo
import math

from decision_review import obj


def positive(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) and value>0


def proceeds(qty, price, liquidity):
    """Balanced constant-product pool estimate with 0.3% fee; reserves inferred from USD depth."""
    if not all(positive(v) for v in (qty,price,liquidity)): return None
    sold_value = qty*price*0.997
    return sold_value/(1+2*sold_value/liquidity)


def depth(qty,price,liquidity):
    if not positive(liquidity): return None
    normal=proceeds(qty,price,liquidity)
    if normal is None: return None
    return dict(expected=round(normal,4),half=round(proceeds(qty,price,liquidity/2),4))


def replay(entry,exit):
    size=25
    _,p,l=entry
    _,q,k=exit
    received=(size*0.997/p)/(1+2*size*0.997/l)
    return round(proceeds(received,q,k)-size,4)


def objections(council):
    if not isinstance(council,dict): return []
    votes={k:v[0] for k,v in (council.get('votes') or {}).items()
           if isinstance(v,(list,tuple)) and v and isinstance(v[0],(int,float)) and 0<=v[0]<=1}
    if not votes or max(votes.values())<0.5: return []
    return [k for k,v in votes.items() if v<0.5]


def changed_rule(checks):
    failures=[k for k,v in checks.items() if not k.startswith('_') and k!='volume_1h' and v[0]=='fail']
    return failures[0] if failures else 'unknown: remaining checks or entry decision'


def session_start(now):
    tz=ZoneInfo('America/Los_Angeles')
    local=datetime.fromtimestamp(now,tz)
    date=local.date() if local.hour>=18 else local.date()-timedelta(days=1)
    return datetime.combine(date,day_time(18),tzinfo=tz).timestamp()


def build(db, observations, now):
    start=session_start(now)
    new=db.execute('SELECT COUNT(*) FROM seen WHERE first_ts BETWEEN ? AND ?',(start,now)).fetchone()[0]
    orders=db.execute("SELECT COUNT(DISTINCT mint||':'||version||':'||opened) FROM positions WHERE version IN ('v3','vC') AND opened BETWEEN ? AND ?",(start,now)).fetchone()[0]
    pnl=db.execute("SELECT SUM(pnl) FROM positions WHERE version IN ('v3','vC') AND closed BETWEEN ? AND ?",(start,now)).fetchone()[0] or 0
    events=db.execute("SELECT ts,kind,mint,symbol,data FROM events WHERE ts BETWEEN ? AND ? AND kind IN ('kill','volume_followup','paper_buy') ORDER BY ts DESC,rowid DESC",(start,now))
    skips={}; reasons=Counter(); rules=Counter(); depths=[]; agents=defaultdict(Counter); rescued=set()
    for ts,kind,m,s,raw in events:
        info=obj(raw)
        if kind=='volume_followup' and info.get('passed_filters'): rescued.add(m)
        if kind=='kill':
            reason=info.get('reason') or 'unknown'
            reasons[str(reason)]+=1
            if 'volume_rule_replay' in info: rules[str(info['volume_rule_replay'])]+=1
            if m and ts<=now-2700 and m not in skips and len(skips)<250: skips[m]=(ts,s or m[:8],info.get('council'))
        if kind=='paper_buy' and info.get('book','v3') in ('v3','vC'):
            if info.get('exit_depth') and len(depths)<15:
                depths.append(dict(symbol=s,mint=m,**info['exit_depth']))
            dissent=objections(info.get('council'))
            if dissent:
                opening=db.execute('SELECT opened FROM positions WHERE mint=? AND version=? AND opened BETWEEN ? AND ? ORDER BY ABS(opened-?) LIMIT 1',(m,info.get('book','v3'),ts-5,ts+1,ts)).fetchone()
                if opening:
                    net,remaining=db.execute("SELECT SUM(pnl),SUM(CASE WHEN status='closed' THEN 0 ELSE 1 END) FROM positions WHERE mint=? AND version=? AND opened=?",(m,info.get('book','v3'),opening[0])).fetchone()
                    if not remaining and net is not None:
                        for agent in dissent: agents[agent]['loss' if net<0 else 'gain' if net>0 else 'flat']+=1
    examples=[]
    for m,(ts,s,council) in skips.items():
        first=observations.execute('SELECT ts,price,liq,pool FROM research_quotes WHERE mint=? AND ts>? AND ts<=? ORDER BY ts LIMIT 1',(m,ts,min(now,ts+1800))).fetchone()
        if not first: continue
        last=observations.execute('SELECT ts,price,liq FROM research_quotes WHERE mint=? AND pool=? AND ts BETWEEN ? AND ? ORDER BY ts LIMIT 1',(m,first[3],first[0]+300,min(now,first[0]+900))).fetchone()
        if last:
            net=replay(first[:3],last)
            examples.append(dict(symbol=s,mint=m,net=net,entry=first[0],exit=last[0]))
            for agent in objections(council): agents[agent]['skipped_gain' if net>0 else 'skipped_nonpositive']+=1
    delays=defaultdict(list)
    for venue,ts,created in observations.execute('SELECT venue,ts,created FROM first_usable WHERE ts BETWEEN ? AND ?',(start,now)):
        delays[venue].append(ts-created if created and ts>=created else None)
    timing=[]
    for venue,items in delays.items():
        valid=[x for x in items if x is not None]
        timing.append(dict(venue=venue,n=len(valid),unknown=len(items)-len(valid),median_s=round(median(valid)) if valid else None))
    evidence = {}
    evidence['New tokens'] = [r[0] for r in db.execute('SELECT mint FROM seen WHERE first_ts BETWEEN ? AND ? ORDER BY first_ts DESC LIMIT 8',(start,now))]
    evidence['Rescued'] = sorted(rescued)[:8]
    evidence['Paper entries'] = [r[0] for r in db.execute("SELECT DISTINCT symbol FROM positions WHERE version IN ('v3','vC') AND opened BETWEEN ? AND ? LIMIT 8",(start,now))]
    evidence['Net realized'] = [f'{r[0]}: ${r[1]:+.2f}' for r in db.execute("SELECT symbol,SUM(pnl) FROM positions WHERE version IN ('v3','vC') AND closed BETWEEN ? AND ? GROUP BY symbol LIMIT 8",(start,now)) if r[1] is not None]
    evidence['Top blocker'] = [f'{k}: {n} decisions' for k,n in reasons.most_common(8)]
    return dict(evidence=evidence,start=start,new=new,orders=orders,pnl=round(pnl,2),rescued=len(rescued),blockers=reasons.most_common(8),
                rules=rules.most_common(),sample=len(skips),measured=len(examples),replays=examples[:20],
                depths=depths,agents=dict(agents),timing=timing)
