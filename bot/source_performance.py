"""Read-only attribution and skipped-token outcomes. Never changes trading rules."""
import json
import math
import time


def number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def payload(raw):
    try:
        d = json.loads(raw)
        return d if isinstance(d, dict) else {}
    except (ValueError, TypeError):
        return {}


def build(c, books=('v3', 'vC'), clock=time.time):
    now = clock()
    groups = {}
    sql = "SELECT * FROM positions WHERE status='closed' AND closed>=? AND version IN (" + ','.join('?' for _ in books) + ')'
    for row in c.execute(sql, (now-86400, *books)):
        p = dict(row)
        if not number(p.get('pnl')): continue
        # Match this opening, never attribute a previous entry or another book.
        events = c.execute("SELECT data FROM events WHERE mint=? AND kind='paper_buy' AND ts>=? AND ts<=? ORDER BY ts DESC", (p['mint'], p['opened']-5, p['opened']+120))
        entry = next((x for x in (payload(r[0]) for r in events) if x.get('book', 'v3') == p['version']), {})
        source = entry.get('source') or 'Unknown'
        dex = entry.get('dex') or 'Unknown'
        key = (str(source), str(dex))
        g = groups.setdefault(key, dict(source=key[0], dex=key[1], realized=0, closed_fills=0, winning_fills=0, partial_fills=0))
        g['realized'] += p['pnl']; g['closed_fills'] += 1
        g['winning_fills'] += p['pnl'] > 0
        g['partial_fills'] += p.get('reason') == 'partial_tp'
    for g in groups.values():
        g['realized'] = round(g['realized'], 2)
        g['win_rate_pct'] = round(100*g['winning_fills']/g['closed_fills'], 1)
    tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    outcomes = {}
    # Both jobs may observe one mint; prefer counterfactual and do not double count.
    for table, fields in [('counterfactual', 'mint,rule,px0,px1,ts'), ('audit', 'mint,reason,kill_px,later_px,ts')]:
        if table not in tables: continue
        for mint, reason, a, b, ts in c.execute('SELECT '+fields+' FROM '+table+' WHERE ts>=? ORDER BY ts DESC', (now-86400,)):
            if mint in outcomes: continue
            valid = number(a) and a > 0 and number(b) and b > 0
            change = (b/a-1)*100 if valid else None
            outcomes[mint] = dict(mint=mint, reason=reason, change_pct=round(change, 2) if change is not None and math.isfinite(change) else None, checked_at=ts, evidence=table)
    rows = list(outcomes.values())
    valid = [r for r in rows if r['change_pct'] is not None]
    return dict(window='last 24 hours', sources=sorted(groups.values(), key=lambda g:-g['realized']),
        missed=dict(status='recorded' if rows else 'awaiting follow-up observations', measured=len(valid), unknown=len(rows)-len(valid),
        rose_20=sum(r['change_pct'] >= 20 for r in valid), fell_20=sum(r['change_pct'] <= -20 for r in valid),
        samples=sorted(rows, key=lambda r:r['checked_at'], reverse=True)[:12]),
        note='Sampled follow-ups, not all skips. Price changes exclude fees, slippage and execution availability; a rise does not prove a safe trade. Partial exits count as closed fills. Unknown attribution stays Unknown.')
