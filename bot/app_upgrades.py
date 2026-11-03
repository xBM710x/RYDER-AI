"""Read-only exports for app recap, exposure, journal and signal-quality cards."""
import datetime
import time
from zoneinfo import ZoneInfo

def build(c, d, books=('v3',), clock=time.time):
    now = clock(); cutoff = now - 24 * 3600
    sql = 'SELECT * FROM positions WHERE version IN (' + ','.join('?' for _ in books) + ')'
    ps = [dict(r) for r in c.execute(sql, books)]
    opened = [p for p in ps if p['status'] == 'open']
    closes = [p for p in ps if p['status'] == 'closed' and p.get('pnl') is not None]
    recent = [p for p in closes if (p.get('closed') or 0) >= cutoff]
    pnl = sum(p['pnl'] for p in recent)
    # Cost exposure is an allocation metric, explicitly not a live market valuation.
    cost = sum(p['cost'] for p in opened)
    equity = float(d['equity']); start = float(d['start'])
    journals = []
    for p in sorted(closes, key=lambda p:p.get('closed') or 0, reverse=True)[:10]:
        ev = c.execute("SELECT data FROM events WHERE mint=? AND kind='paper_buy' AND ts<=? ORDER BY ts DESC LIMIT 20", (p['mint'],p['opened']+120)).fetchall()
        import json
        why = None
        for r in ev:
            try: x = json.loads(r[0])
            except (ValueError, TypeError): continue
            if x.get('book', 'v3') == p['version']:
                why = x.get('why_bought') or x.get('why1') or None; break
        journals.append(dict(sym=p['symbol'], book=p['version'], pnl=round(p['pnl'],2),
                             reason=p.get('reason'), entry_reason=why,
                             closed=p.get('closed'), partial=p.get('reason')=='partial_tp'))
    return dict(recap=dict(window='last 24 hours', realized=round(pnl,2), closed_fills=len(recent),
                           wins=sum(p['pnl']>0 for p in recent), starting_capital=start,
                           current_equity=equity, generated_at=now),
                exposure=dict(cost_usd=round(cost,2), open_positions=len(opened),
                              pct_of_equity=round(cost/equity*100,2) if equity>0 else None,
                              max_trade_pct=10, basis='entry cost'),
                journal=journals,
                source_performance=__import__("source_performance").build(c, books, clock),
                signal_quality=dict(scanned=d.get('seen'), passed=d.get('passed'),
                                    pass_rate_pct=round(d['passed']/d['seen']*100,3) if d.get('seen') else None,
                                    scope='current version; checks can overlap', books=list(books)))
