"""Purged walk-forward replay on recorded completed paper openings. No model promotion."""
import json
import math
import statistics

def metrics(samples):
    if not samples:return dict(n=0,mean_net_pct=None,realized=None,win_rate_pct=None,win_rate_interval_95=None)
    n=len(samples);wins=sum(s['pnl']>0 for s in samples);p=wins/n;z=1.96;den=1+z*z/n
    center=(p+z*z/(2*n))/den
    half=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/den
    return dict(n=n,mean_net_pct=round(statistics.mean(s['roi'] for s in samples)*100,4),realized=round(sum(s['pnl'] for s in samples),2),win_rate_pct=round(p*100,2),win_rate_interval_95=[round(max(0,center-half)*100,2),round(min(1,center+half)*100,2)])

def evaluate(samples,min_train=40,test_size=10):
    samples=sorted(samples,key=lambda s:s['opened']);folds=[]
    for i in range(min_train,len(samples)-test_size+1,test_size):
        test=samples[i:i+test_size];cutoff=min(s['opened'] for s in test);test_mints={s['mint'] for s in test}
        train=[s for s in samples[:i] if s['closed']<cutoff and s['mint'] not in test_mints]
        if len(train)<min_train:continue
        options=[]
        for threshold in (.55,.60,.65,.70,.75):
            chosen=[s for s in train if s.get('score') is not None and s['score']>=threshold]
            if len(chosen)>=max(10,len(train)//5):options.append((metrics(chosen)['mean_net_pct'],-threshold,threshold))
        if not options:continue
        threshold=max(options)[2]
        chosen=[s for s in test if s.get('score') is not None and s['score']>=threshold]
        folds.append(dict(train_n=len(train),test_start=cutoff,threshold=threshold,baseline=metrics(test),challenger=metrics(chosen)))
    return dict(status='walk-forward replay available' if folds else 'insufficient completed, matched history',sample_n=len(samples),minimum_train=min_train,test_size=test_size,folds=folds[-20:],promotion_allowed=False,note='Threshold selected on earlier completed trades; overlapping outcomes and repeated test mints purged from training. Replay only covers executed paper trades, not untraded opportunities. Net recorded P&L includes the existing fill model. Wilson win-rate intervals are descriptive and assume independent outcomes; market dependence may make uncertainty larger. No parameter changes or profitability claims.')

def build(c):
    samples=[];unmatched=0
    rows=c.execute("""SELECT mint,version,opened,MAX(closed) AS closed,SUM(cost) AS cost,SUM(pnl) AS pnl FROM positions
      WHERE status='closed' AND version IN ('v3','vC') GROUP BY mint,version,opened ORDER BY opened DESC LIMIT 5000""").fetchall()
    for row in rows:
        p=dict(row);k=(p['mint'],p['version'],p['opened'])
        if c.execute("SELECT 1 FROM positions WHERE mint=? AND version=? AND opened=? AND status='open'",k).fetchone():continue
        if any(not isinstance(p.get(k),(int,float)) or not math.isfinite(p[k]) for k in ('cost','pnl','opened','closed')) or p['cost']<=0 or p['closed']<p['opened']:continue
        ev=c.execute("SELECT data FROM events WHERE mint=? AND kind='paper_buy' AND ts BETWEEN ? AND ? ORDER BY ts LIMIT 20",(p['mint'],p['opened']-1,p['opened']+5))
        entry=None
        for r in ev:
            try:x=json.loads(r[0])
            except (TypeError,ValueError):continue
            if isinstance(x,dict) and x.get('book','v3')==p['version']:entry=x;break
        if entry is None:unmatched+=1;continue
        score=entry.get('score')
        if not isinstance(score,(int,float)) or not math.isfinite(score):unmatched+=1;continue
        roi=p['pnl']/p['cost']
        if not math.isfinite(roi):continue
        samples.append(dict(mint=p['mint'],opened=p['opened'],closed=p['closed'],score=score,pnl=p['pnl'],roi=roi))
    out=evaluate(samples);out['unmatched_openings']=unmatched;return out
