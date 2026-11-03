"""Twenty-five evidence-backed desk views; bounded read-only ledger queries."""
import collections
import datetime
import json
import math
import sqlite3
import time
from pathlib import Path
from zoneinfo import ZoneInfo
from desk_observations import finite
D=Path(__file__).resolve().parent
TITLES=['Searchable radar','Token detail pages','Source comparison','Discovery speed','Source outage alerts','Data freshness','Pinned watchlist','Near-entry candidates','Decision timeline','Agent disagreement','Confidence calibration','Learning progress','Market-regime performance','Token-age performance','Liquidity performance','Execution cost breakdown','Exit review','Follow-up coverage','Filter review','Experiment scoreboard','Rule-change history','Paper drawdown','Daily recap','Background-service health','Backup management']
KINDS={'kill','skip','score','entry_wait','paper_buy','paper_add','paper_exit','council_votes','strong_agreement','ml_trained','loosen','rollback','promote','threshold_change','rule_change','rule_revert','threshold_fix','self_review','size_brake'}

def obj(raw):
    try:
        d=json.loads(raw)
        return d if isinstance(d,dict) else {}
    except (ValueError,TypeError):return {}

def file(name):
    try:return obj((D/name).read_text())
    except OSError:return {}

def card(i,headers=(),rows=(),note='',series=(),unit=''):
    return dict(id=i,title=TITLES[i-1],headers=list(headers),rows=list(rows),note=note,series=list(series),unit=unit)

def group_stats(items,key):
    g={}
    for p,b in items:
        k=str(key(p,b) or 'Unknown');r=g.setdefault(k,[0,0,0.0]);r[0]+=1;r[1]+=p['pnl']>0;r[2]+=p['pnl']
    return [[k,n,w,round(v,2)] for k,(n,w,v) in sorted(g.items())]

def curve_groups(items,key):
    groups=collections.defaultdict(list)
    for p,b in sorted(items,key=lambda x:x[0].get('closed') or 0):groups[str(key(p,b) or 'Unknown')].append(p)
    out=[]
    for k,ps in list(groups.items())[:8]:
        v=0;points=[]
        for p in ps:v+=p['pnl'];points.append(dict(t=p['closed'],v=round(v,4)))
        out.append(dict(name=k,points=points))
    return out

def build(c,d,hb,clock=time.time):
    now=clock();cut=now-86400
    events=[]
    for r in c.execute('SELECT id,ts,kind,mint,symbol,data FROM events WHERE ts>=? ORDER BY id DESC LIMIT 4000',(now-2*86400,)):
        e=dict(r);e['data']=obj(e['data']);events.append(e)
    bymint=collections.defaultdict(list)
    for e in events:
        if e['mint'] and e['kind'] in KINDS:bymint[e['mint']].append(e)
    ps=[dict(r) for r in c.execute("SELECT * FROM positions WHERE status='closed' AND closed>=? ORDER BY closed LIMIT 3000",(cut,)) if finite(r['pnl']) is not None]
    entries={};items=[]
    for p in ps:
        k=(p['mint'],p['version'],p['opened'])
        if k not in entries:
            rows=c.execute("SELECT data FROM events WHERE mint=? AND kind='paper_buy' AND ts BETWEEN ? AND ? ORDER BY ts DESC LIMIT 20",(p['mint'],p['opened']-5,p['opened']+120))
            entries[k]=next((b for b in (obj(r[0]) for r in rows) if b.get('book','v3')==p['version']),{})
        items.append((p,entries[k]))
    main=[x for x in items if x[0]['version'] in ('v3','vC')]
    import desk_observations
    try:tokens,eq=desk_observations.snapshot(clock,'shared' if d.get('shared_account') else 'main')
    except (sqlite3.Error,OSError):tokens,eq=[],[]
    for t in tokens:
        t['age_s']=max(0,now-t['created']) if t['created'] else None
        t['observation_age_s']=max(0,now-t['last_ts'])
        t['freshness']='recent observation' if t['observation_age_s']<=120 else 'delayed observation'
        t['events']=[dict(t=e['ts'],kind=e['kind'],reason=str(e['data'].get('reason') or e['data'].get('why') or e['data'].get('detail') or '' )[:400]) for e in sorted(bymint[t['mint']],key=lambda e:e['ts'],reverse=True)[:20]][::-1]
        score=next((e['data'].get('score') for e in bymint[t['mint']] if e['kind']=='score'),None)
        t['score']=finite(score)
    cards=[]
    cards.append(card(1,note='Latest 120 observed candidates, not the entire market. Use search, source, liquidity, score and freshness filters.'))
    cards.append(card(2,note='Open a radar token for its recorded observations and last 20 decision events.'))
    cards.append(card(3,['Source','Closed fills','Winning fills','Realized USD'],group_stats(main,lambda p,b:b.get('source')),note='Last 24h; partial exits count as fills. Source attribution must be recorded at entry.',series=curve_groups(main,lambda p,b:b.get('source')),unit='USD'))
    speeds=collections.defaultdict(list);unknown=0
    for t in tokens:
        if t['created'] and 0<=t['first_ts']-t['created']<=86400:speeds[t['source']].append(t['first_ts']-t['created'])
        else:unknown+=1
    import statistics
    cards.append(card(4,['Source','Measured tokens','Median delay seconds'],[[k,len(v),round(statistics.median(v),1)] for k,v in speeds.items()],note=f'Creation-to-first-observation delay in radar sample; {unknown} unknown or implausible launch times excluded.'))
    sources=hb.get('sources') or {};health=[]
    for host,s in sources.items():
        age=now-s['last_ok'] if s.get('last_ok') else None
        health.append([host,'no recent success' if age is None or age>300 else 'recent successful request',round(age) if age is not None else None,s.get('ok'),s.get('err')])
    st=d.get('stonkfun') or {};health.append(['StonkFun',st.get('status','not observed'),st.get('age_s'),None,None])
    cards.append(card(5,['Feed / host','Status','Last success age s','OK requests','Errors'],health,note='In-app warnings only; quiet sources are not automatically classified as outages. Request totals are since runner start.'))
    cards.append(card(6,['Token','Observation age seconds','Status'],[[t['symbol'],round(t['observation_age_s']),t['freshness']] for t in tokens[:20]],note='These are local observation times, not exchange timestamps. Unknown price or liquidity stays unknown.'))
    cards.append(card(7,note='Browser-local pins give quick access to tokens in this bounded observation snapshot. They do not force backend monitoring or approve buys.'))
    cards.append(card(8,['Token','Recorded score','Wait left seconds','Stage'],[[w.get('sym'),w.get('score'),w.get('wait_left'),'entry confirmation'] for w in hb.get('watch',[])],note='Pending candidates still need rechecks. A wait reaching zero does not approve a trade.'))
    cards.append(card(9,['Time','Token','Event','Recorded reason'],[[e['ts'],e['symbol'] or (e['mint'] or '')[:8],e['kind'],str(e['data'].get('reason') or e['data'].get('why1') or e['data'].get('why') or e['data'].get('detail') or 'Not recorded')[:400]] for e in events if e['kind'] in KINDS][:100],note='Existing logger events; newest first; bounded recent window.'))
    councils=[]
    for e in events:
        if e['kind']=='council_votes':
            x=e['data'];councils.append([e['ts'],e['symbol'],json.dumps({k:x.get(k) for k in ('votes','reason','go','consensus','council') if k in x},default=str)[:1200]])
    cards.append(card(10,['Time','Token','Recorded council evidence'],councils[:15],note='Recorded votes and disagreements; empty means no council event in this window.'))
    vote_event=next((e for e in events if e['kind']=='council_votes'),None)
    cards[-1]['votes']=[[k,finite(v.get('vote')),str(v.get('why') or '')[:200]] for k,v in ((vote_event or {}).get('data',{}).get('votes') or {}).items() if isinstance(v,dict)]
    # One outcome per completed opening, not one per partial exit. Open residuals excluded.
    completed=[]
    for k,b in entries.items():
        mint,book,opened=k
        if c.execute("SELECT 1 FROM positions WHERE mint=? AND version=? AND opened=? AND status='open'",k).fetchone():continue
        # Full opening outcome across all its fills, including partials outside this window.
        pnl=c.execute("SELECT SUM(pnl) FROM positions WHERE mint=? AND version=? AND opened=? AND status='closed'",k).fetchone()[0]
        if book in ('v3','vC') and pnl is not None:completed.append((b,pnl))
    bins=collections.defaultdict(list)
    for b,pnl in completed:
        prob=finite(b.get('win_prob'))
        if prob is not None and 0<=prob<=1:bins[min(4,int(prob*5))].append((prob,pnl>0))
    calibration=[[f'{i*20}–{(i+1)*20}%',len(v),round(sum(x[0] for x in v)/len(v)*100,1),round(sum(x[1] for x in v)/len(v)*100,1)] for i,v in sorted(bins.items())]
    cards.append(card(11,['Predicted bin','Completed openings','Mean predicted %','Observed wins %'],calibration,note='Predicted win_prob, not arbitrary confidence. Matched completed openings only; this is descriptive calibration, not held-out validation. Small samples are uncertain.'))
    learned=[e for e in events if e['kind']=='ml_trained']
    cards.append(card(12,['Training time','Recorded samples'],[[e['ts'],e['data'].get('n')] for e in learned[:20]],note='Model and count from runner heartbeat: '+json.dumps(hb.get('model') or {})+'. Training is not proof of improved performance.',series=[dict(name='Training samples',points=[dict(t=e['ts'],v=e['data']['n']) for e in learned[::-1] if finite(e['data'].get('n')) is not None])]))
    headers=['Entry group','Closed fills','Winning fills','Realized USD']
    cards.append(card(13,headers,group_stats(main,lambda p,b:b.get('entry_regime')),note='Entry regime captured only for new fills after this upgrade. Unknown historical regimes are not inferred.'))
    def agekey(p,b):
        age=finite(b.get('entry_age_min'))
        return None if age is None else '<5m' if age<5 else '5–30m' if age<30 else '30m–2h' if age<120 else '>2h'
    cards.append(card(14,headers,group_stats(main,agekey),note='Age at entry; partial exits count as fills.'))
    def liqkey(p,b):
        liq=finite(b.get('liq'))
        return None if liq is None else '<$25k' if liq<25000 else '$25k–$75k' if liq<75000 else '$75k–$250k' if liq<250000 else '>$250k'
    cards.append(card(15,headers,group_stats(main,liqkey),note='Liquidity at entry, never inferred from current pool liquidity.'))
    costs=collections.Counter();costn=0
    for e in events:
        if e['ts']>=cut and e['kind'] in ('paper_buy','paper_exit') and e['data'].get('book') in ('v3','vC'):
            x=e['data'].get('modeled_costs') or {}
            if all(finite(x.get(k)) is not None for k in ('fees','slippage','mev','total')):
                costn+=1
                for k in ('fees','slippage','mev','total'):costs[k]+=x[k]
    cards.append(card(16,['Component','Modeled USD'],[[k,round(costs[k],4)] for k in ('fees','slippage','mev','total')] if costn else [],note=f'{costn} new fill events with decomposed costs. Earlier fills lack these components. These are modeled costs, not real execution measurements.'))
    b19=file('brain19.json');exits=b19.get('scored') or []
    cards.append(card(17,['Token','Actual exit %','Shadow alternative %','Actual reason','Shadow reason'],[[x.get('sym'),x.get('real_pct'),x.get('would_pct'),x.get('real'),x.get('would')] for x in exits[-30:][::-1]],note='Existing exit-manager shadow comparisons. Hindsight prices do not prove an alternative fill was executable.',series=[dict(name=label,points=[dict(t=x['t'],v=x[key]) for x in exits[-30:] if finite(x.get('t')) is not None and finite(x.get(key)) is not None]) for label,key in [('Actual exit %','real_pct'),('Shadow alternative %','would_pct')]],unit='%'))
    tables={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")};follow={}
    for table,fields in [('counterfactual','mint,rule,px0,px1,ts'),('audit','mint,reason,kill_px,later_px,ts')]:
        if table not in tables:continue
        for m,r,a,b,t in c.execute('SELECT '+fields+' FROM '+table+' WHERE ts>=? ORDER BY ts DESC LIMIT 1000',(cut,)):
            if m in follow:continue
            change=(b/a-1)*100 if finite(a) is not None and a>0 and finite(b) is not None and b>0 else None
            follow[m]=(r,change,t)
    skips={e['mint'] for e in events if e['ts']>=cut and e['kind'] in ('kill','skip') and e['mint']}
    observed={m for m,(_,v,_) in follow.items() if v is not None};eligible=skips|set(follow)
    cards.append(card(18,['Measure','Unique tokens'],[['Sampled skipped-token universe',len(eligible)],['Measured follow-up',len(observed)],['No valid later quote / not followed',len(eligible-observed)]],note='Universe = unique skips in bounded logger window plus recent follow-up records. This is sampled coverage, not all-time coverage.'))
    rules=collections.defaultdict(lambda:[0,0,0,0])
    for r,v,t in follow.values():
        g=rules[r or 'Unknown']
        if v is None:g[3]+=1
        else:g[0]+=1;g[1]+=v>=20;g[2]+=v<=-20
    cards.append(card(19,['Reason','Measured','Rose ≥20%','Fell ≥20%','Unknown'],[[r,*v] for r,v in rules.items()],note='Later observed raw price change; excludes fees and fill availability. No filter is changed by this panel.'))
    cards.append(card(20,headers,group_stats(items,lambda p,b:p['version']),note='Last 24h realized results by paper book; partial exits count as fills. No duplicate shared-account totals.',series=curve_groups(items,lambda p,b:p['version']),unit='USD'))
    rule_events=[e for e in events if e['kind'] in ('loosen','rollback','promote','threshold_change','rule_change','rule_revert','threshold_fix','self_review')]
    cards.append(card(21,['Time','Recorded event','Change evidence'],[[e['ts'],e['kind'],json.dumps({k:v for k,v in e['data'].items() if k in ('changes','why','reason','old','new','version','threshold','key','thresholds','lessons','champion','a','b','bad','to','pnl','win_rate')},default=str)[:1000]] for e in rule_events[:25]],note='Applied events only. Coach suggestion: '+str(((d.get('agents5') or {}).get('coach') or {}).get('tweak') or 'none recorded')+' (not automatically applied here).'))
    peak=None;draw=[]
    for r in eq:
        peak=max(peak if peak is not None else r['value'],r['value'])
        draw.append(dict(t=r['ts'],v=round((r['value']/peak-1)*100,4) if peak>0 else 0))
    cards.append(card(22,['Measure','Value'],[['Max observed drawdown %',round(-min([p['v'] for p in draw] or [0]),2)],['Equity observations',len(eq)]],note='Seven-day observed shared-equity window, starting when this collector is installed. No backfilled main-only curve.',series=[dict(name='Drawdown %',points=draw)],unit='%'))
    date=datetime.datetime.fromtimestamp(now,ZoneInfo('America/Los_Angeles')).strftime('%Y-%m-%d')
    midnight=datetime.datetime.fromtimestamp(now,ZoneInfo('America/Los_Angeles')).replace(hour=0,minute=0,second=0,microsecond=0).timestamp()
    today=[p for p,b in main if (p['closed'] or 0)>=midnight]
    reasons=collections.Counter(str(e['data'].get('reason') or 'not recorded') for e in events if e['ts']>=midnight and e['kind'] in ('kill','skip'))
    cards.append(card(23,['Measure','Value'],[['Day (Pacific)',date],['Realized paper USD',round(sum(p['pnl'] for p in today),2)],['Closed fills',len(today)],['Partial fills',sum(p.get('reason')=='partial_tp' for p in today)],['Most frequent skip',reasons.most_common(1)[0][0] if reasons else 'not recorded']],note='Calendar-day Pacific recap. The event window is bounded; this does not send email.'))
    updater=file('updater-status.json');published=file('publisher-status.json')
    cards.append(card(24,['Service','Evidence','Age seconds'],[['Runner','heartbeat',round(now-hb['ts']) if hb.get('ts') else None],['Publisher','last successful push',round(now-published['ts']) if published.get('ts') else None],['Updater',updater.get('state','not yet reported'),round(now-updater['ts']) if updater.get('ts') else None],['Installed code',updater.get('commit','not reported')[:12],None]],note='Separate process evidence; stale or absent timestamps are not healthy. Snapshot generated at '+str(int(now))+'.'))
    backups=[]
    for path in sorted((D/'update-backups').glob('*.db'),key=lambda p:p.stat().st_mtime,reverse=True)[:12]:
        verified=file('update-backups/'+path.name+'.checked.json')
        backups.append([path.name,path.stat().st_size,verified.get('integrity','not recorded'),path.stat().st_mtime])
    legacy=D/'desk-before-shared.db'
    if legacy.exists():backups.append([legacy.name,legacy.stat().st_size,'not rechecked',legacy.stat().st_mtime])
    cards.append(card(25,['Backup name','Bytes','Integrity at creation','Saved time'],backups,note='Retained local database backups. Display only; recovery guide requires stopping all workers and preserving current state before any manual restore.'))
    # No raw event blobs, configuration, environment or user filesystem paths are exported.
    return dict(schema=1,generated_at=now,cards=cards,tokens=tokens,scope='24h realized fills; latest 120 radar observations; up to 4000 recent logger events',paper_only=True)
