"""Evidence-backed advisory intelligence. No execution or exit-rule imports."""
import json,math,time,hashlib
from collections import defaultdict,Counter
from decision_review import openings,obj
RELEASE='intelligence-1'
BASE={'min_neighbors':10,'min_train':40,'test_size':10}
def num(x):
    if isinstance(x,bool):return None
    try:x=float(x)
    except (TypeError,ValueError):return None
    return x if math.isfinite(x) else None

def features(pair,now):
    p=pair or {};tx=(p.get('txns') or {}).get('m5') or {};created=num(p.get('pairCreatedAt'));stamp=num(p.get('_ts'))
    return dict(captured_at=now,liquidity=num((p.get('liquidity') or {}).get('usd')),momentum=num((p.get('priceChange') or {}).get('m5')),volume=num((p.get('volume') or {}).get('m5')),buys=num(tx.get('buys')),sells=num(tx.get('sells')),age_s=max(0,now-created/1000) if created and now>=created/1000 else None,quote_age_s=now-stamp if stamp is not None else None,price=num(p.get('priceUsd')),pool=p.get('pairAddress'))

def quality(f):
    warnings=[];age=f.get('quote_age_s')
    if age is None or not 0<=age<=30:warnings.append('Price freshness unverified')
    if not f.get('liquidity') or f['liquidity']<=0:warnings.append('Liquidity missing')
    if not f.get('price') or f['price']<=0:warnings.append('Price missing')
    if f.get('buys') is None or f.get('sells') is None:warnings.append('Transaction counts missing')
    b,s=f.get('buys'),f.get('sells');total=b+s if b is not None and s is not None else None
    return dict(warnings=warnings,confidence='withheld' if warnings else 'inputs present; outcome confidence needs calibration',buy_share=round(b/total,3) if total and total>0 and b>=0 and s>=0 else None,unique_buyers=None,buyer_quality='Unverified: transaction counts do not identify independent buyers')

def regime(f):
    v,m=f.get('volume'),f.get('momentum')
    if v is None or m is None:return 'unknown'
    return 'quiet' if v<1000 else 'uptrend' if m>2 else 'downtrend' if m< -2 else 'choppy'

def classify(t):
    e=t['entry'];parts=t['parts'];labels=[];f=e.get('intelligence_features') or {};q=quality(f)
    if f and q['warnings']:labels.append('Entry data incomplete or stale')
    costs=(e.get('modeled_costs') or {}).get('total');costs=num(costs)
    if costs is not None and costs>t['cost']*.03:labels.append('Entry costs exceeded 3% of allocation')
    peaks=[p.get('peak') for p in parts if num(p.get('peak')) is not None];last=max(parts,key=lambda p:p['closed']);entry=num(last.get('entry'));exit=num(last.get('exit'))
    if peaks and entry and exit and max(peaks)>entry*1.1 and exit<max(peaks)*.9:labels.append('Recorded peak gave back over 10% before final fill')
    if t['pnl']<0:labels.append('Net loss; cause requires review')
    elif t['pnl']>0:labels.append('Net profitable opening')
    else:labels.append('Flat net opening')
    return labels

def distance(a,b):
    keys=('liquidity','momentum','age_s','buys','sells');ds=[]
    for k in keys:
        x,y=num(a.get(k)),num(b.get(k))
        if x is None or y is None:return None
        if k=='momentum':ds.append(abs(x-y)/10)
        elif x<0 or y<0:return None
        else:ds.append(abs(math.log1p(x)-math.log1p(y)))
    return sum(ds)/len(ds)

def neighbors(cases,f,mint,at,minimum=10):
    ranked=[]
    for c in cases:
        if c['closed']>=at or c['mint']==mint:continue
        d=distance(f,c['features'])
        if d is not None and d<=1:ranked.append((d,c))
    selected=sorted(ranked,key=lambda r:r[0])[:50]
    return dict(n=len(selected),status='comparable evidence' if len(selected)>=minimum else 'insufficient comparable history',mean_net_pct=round(sum(c['net_pct'] for _,c in selected)/len(selected),3) if len(selected)>=minimum else None,examples=[dict(symbol=c['symbol'],net_pct=c['net_pct'],distance=round(d,3)) for d,c in selected[:5]])

def schema(obs):
    obs.executescript('''CREATE TABLE IF NOT EXISTS intelligence_cases(id TEXT PRIMARY KEY,mint TEXT,closed REAL,payload TEXT);
    CREATE TABLE IF NOT EXISTS intelligence_versions(id TEXT PRIMARY KEY,created REAL,config TEXT);
    CREATE TABLE IF NOT EXISTS intelligence_active(singleton INTEGER PRIMARY KEY CHECK(singleton=1),version TEXT);
    CREATE TABLE IF NOT EXISTS intelligence_history(ts REAL,previous TEXT,version TEXT,reason TEXT);''')
    v=save_version(obs,BASE)
    obs.execute('INSERT OR IGNORE INTO intelligence_active VALUES(1,?)',(v,));obs.commit()

def save_version(obs,config):
    if set(config)!=set(BASE) or any(type(v) is not int for v in config.values()):raise ValueError('Invalid research configuration')
    if not 5<=config['min_neighbors']<=50 or not 20<=config['min_train']<=500 or not 5<=config['test_size']<=100:raise ValueError('Research sample limits out of range')
    raw=json.dumps(config,sort_keys=True);v=hashlib.sha256(raw.encode()).hexdigest()[:16]
    obs.execute('INSERT OR IGNORE INTO intelligence_versions VALUES(?,?,?)',(v,time.time(),raw));return v

def activate(obs,version,reason):
    if not reason.strip():raise ValueError('A reason is required')
    if not obs.execute('SELECT 1 FROM intelligence_versions WHERE id=?',(version,)).fetchone():raise ValueError('Unknown version')
    old=obs.execute('SELECT version FROM intelligence_active WHERE singleton=1').fetchone()[0]
    with obs:
        obs.execute('UPDATE intelligence_active SET version=? WHERE singleton=1',(version,))
        obs.execute('INSERT INTO intelligence_history VALUES(?,?,?,?)',(time.time(),old,version,reason))
    return old

def build(db,obs,data,hb,now):
    schema(obs);version=obs.execute('SELECT version FROM intelligence_active WHERE singleton=1').fetchone()[0]
    config=json.loads(obs.execute('SELECT config FROM intelligence_versions WHERE id=?',(version,)).fetchone()[0])
    trades=[t for t in openings(db,now) if t['closed']<=now]
    for t in trades:
        f=t['entry'].get('intelligence_features') or {}
        if f:
            case={k:t[k] for k in ('mint','symbol','opened','closed','net_pct','pnl','book')};case.update(features=f,strategy=t['entry'].get('entry_strategy','unknown'))
            key=json.dumps([t['mint'],t['book'],t['opened']]);obs.execute('INSERT OR REPLACE INTO intelligence_cases VALUES(?,?,?,?)',(key,t['mint'],t['closed'],json.dumps(case)))
    obs.execute('DELETE FROM intelligence_cases WHERE closed<?',(now-180*86400,));obs.commit()
    cases=[obj(r[0]) for r in obs.execute('SELECT payload FROM intelligence_cases WHERE closed<=? ORDER BY closed DESC LIMIT 2000',(now,))]
    mistakes=[dict(symbol=t['symbol'],net=t['pnl'],findings=classify(t)) for t in trades[:20]]
    bands=defaultdict(list);objections=defaultdict(Counter);byregime=defaultdict(list)
    for t in trades:
        e=t['entry'];prob=num(e.get('win_prob'))
        if prob is not None and 0<=prob<=1:bands[min(4,int(prob*5))].append((prob,t['pnl']>0))
        votes=(e.get('council') or {}).get('votes') or {}
        for agent,v in votes.items():
            score=num(v[0]) if isinstance(v,list) and v else None
            if score is not None and score<.5:objections[agent]['objected_loss' if t['pnl']<0 else 'objected_gain' if t['pnl']>0 else 'objected_flat']+=1
    for c in cases:byregime[(c['strategy'],regime(c['features']))].append(c['net_pct'])
    calibration=[dict(band=k,n=len(v),predicted=round(sum(p for p,w in v)/len(v),3),actual=round(sum(w for p,w in v)/len(v),3),brier=round(sum((p-w)**2 for p,w in v)/len(v),4)) for k,v in sorted(bands.items())]
    strategies=[dict(strategy=k[0],regime=k[1],n=len(v),mean_net_pct=round(sum(v)/len(v),3),status='review on held-out data' if len(v)>=30 else 'insufficient sample') for k,v in byregime.items()]
    watch=[]
    for w in hb.get('watch',[])[:10]:
        f=dict(w.get('intelligence_features') or {})
        captured=num(f.get('captured_at')); age=num(f.get('quote_age_s'))
        if captured is not None and age is not None:f['quote_age_s']=age+max(0,now-captured)
        watch.append(dict(symbol=w.get('sym'),mint=w['mint'],condition=regime(f),quality=quality(f),memory=neighbors(cases,f,w['mint'],now,config['min_neighbors'])))
    import learning_evaluation
    evaluation=learning_evaluation.build(db,config['min_train'],config['test_size'],now)  # Existing purged replay, no promotion.
    session=data.get('session_research') or {};missed=session.get('replays') or []
    return dict(release=RELEASE,runner_release=hb.get('intelligence_release'),at=now,mode='advisory; execution and exits unchanged',memory_cases=len(cases),watch=watch,mistakes=mistakes,calibration=calibration,regimes=strategies,objections=dict(objections),liquidity=session.get('depths') or [],missed=missed[:15],walk_forward=evaluation,version=version,config=config,versions=[dict(id=r[0],created=r[1]) for r in obs.execute('SELECT id,created FROM intelligence_versions ORDER BY created DESC LIMIT 10')],history=[dict(ts=r[0],previous=r[1],version=r[2],reason=r[3]) for r in obs.execute('SELECT * FROM intelligence_history ORDER BY ts DESC LIMIT 10')],scope='Cases: at most 2,000 completed openings, retained 180 days; new features only. Reviews: last 7 days, at most 500 openings. Similarity excludes the same token and future outcomes. Buyer independence and causality are not inferred. Challengers replay executed trades only, not the full opportunity set.')

if __name__=='__main__':
    import argparse,desk_observations
    p=argparse.ArgumentParser(description='Version research settings only. Never edits trading parameters.')
    p.add_argument('--save',help='JSON research config');p.add_argument('--activate');p.add_argument('--reason',default='');args=p.parse_args()
    c=desk_observations.connect()
    try:
        schema(c)
        if args.save:v=save_version(c,json.loads(args.save));c.commit();print(v)
        if args.activate:print('Previous research version:',activate(c,args.activate,args.reason))
        print('Active research version:',c.execute('SELECT version FROM intelligence_active').fetchone()[0])
    finally:c.close()
