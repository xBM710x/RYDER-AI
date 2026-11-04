"""Paper-desk strategy labels, confirmed entries and exit policies."""
import math
import time


def number(x):
    if isinstance(x, bool): return None
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError): return None


def setup(pair, now):
    pair = pair or {}
    def field(section, key):
        return number((pair.get(section) or {}).get(key))
    vol, recent = field('volume','h1'), field('volume','m5')
    liq, delta = field('liquidity','usd'), field('priceChange','m5')
    tape = (pair.get('txns') or {}).get('m5') or {}
    b, s = number(tape.get('buys')), number(tape.get('sells'))
    ts = number(pair.get('_ts'))
    if None in (vol,recent,liq,delta,b,s,ts): return 'standard'
    if not (0 <= now-ts <= 15 and vol >= 10000 and 2000 <= recent <= vol
            and liq >= 25000 and s >= 0 and b >= 20 and b >= 1.5*max(1,s)):
        return 'standard'
    if 0 < delta <= 15: return 'momentum'
    hour = field('priceChange','h1')
    if hour is not None and 5 <= hour <= 45 and -5 <= delta <= -0.5:
        return 'pullback'
    return 'standard'


def confirmed(kind, initial, pair, pool, now, signal_ts=None):
    if kind == 'standard': return True
    q = number(pair.get('priceUsd')); stamp = number(pair.get('_ts'))
    if not (pool and pool == pair.get('pairAddress') and q and initial and stamp and 0 <= now-stamp <= 15): return False
    if signal_ts is not None and stamp <= signal_ts: return False
    # Pullbacks need an observed bounce after the signal. Momentum must persist.
    liq=number((pair.get('liquidity') or {}).get('usd'))
    if liq is None or liq<25000: return False
    change = q/initial-1
    buys = (pair.get('txns') or {}).get('m5') or {}
    b,s = number(buys.get('buys')),number(buys.get('sells'))
    return (b is not None and s is not None and s >= 0 and b > s and
            (0.005 <= change <= .10 if kind=='pullback' else
             0 <= change <= .10 and setup(pair,now)=='momentum'))


def exit_policy(pair):
    tape=(pair.get('txns') or {}).get('m5') or {}
    b,s=number(tape.get('buys')),number(tape.get('sells'))
    if b is None or s is None or min(b,s)<0 or b+s<10: return .5,None
    if b >= 1.5*max(1,s): return 1/3,.09
    if s>b: return 2/3,.045
    return .5,None


def near(pair, now):
    pair=pair or {}; vol=number((pair.get('volume') or {}).get('h1'))
    liq=number((pair.get('liquidity') or {}).get('usd'))
    ts=number(pair.get('_ts'))
    return bool(ts and 0<=now-ts<=30 and vol and vol>=7500 and liq and liq>=18000)


def evidence(db, follow, updater, now):
    from decision_review import openings, obj
    rows={k:{'closed':0,'net':0.,'dd':0.,'peak':0.} for k in ('momentum','pullback','standard','unclassified')}
    replays=[]
    for t in sorted(openings(db,now),key=lambda t:t['closed']):
        if t['book']!='v3': continue
        k=t['entry'].get('entry_strategy','unclassified')
        r=rows.get(k,rows['unclassified']);r['closed']+=1;r['net']+=t['pnl']
        r['peak']=max(r['peak'],r['net']);r['dd']=max(r['dd'],r['peak']-r['net'])
        parts=sorted(t['parts'],key=lambda p:p['closed'])
        entry=parts[0]['entry']
        if entry and entry>0:
            peaks=[p['peak'] for p in parts if p.get('peak')]
            replays.append(dict(symbol=t['symbol'],reason=parts[-1]['reason'],entry=entry,
                opened=t['opened'],peak=max(peaks) if peaks else None,
                fills=[[p['closed'],p['exit'],p['reason']] for p in parts if p.get('exit')]))
    blocked=[]
    for sym,ts,raw in db.execute("SELECT symbol,ts,data FROM events WHERE kind='strategy_block' AND ts>=? ORDER BY id DESC LIMIT 16",(now-86400,)):
        d=obj(raw);blocked.append([sym,d.get('strategy'),d.get('reason'),ts])
    return dict(release='strategy-desk-1',score=rows,replays=replays[-10:][::-1],blocked=blocked,watch=follow,updater=updater)
