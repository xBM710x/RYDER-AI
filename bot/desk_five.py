"""Compact publisher evidence for the trade funnel and token timeline."""
from collections import defaultdict
import json
import time

STAGES = ("Discovered", "Passed", "Confirmed", "Paper buys")


def build(db, now=None):
    since = (time.time() if now is None else now) - 86400
    cohort = {r[0] for r in db.execute("SELECT mint FROM seen WHERE first_ts >= ?", (since,))}
    stages = [set(cohort), set(), set(), set()]
    histories = defaultdict(list)
    names = {}
    for ts, kind, mint, symbol, raw in db.execute(
        """SELECT ts,kind,mint,symbol,data FROM events WHERE ts>=? AND mint IS NOT NULL
        AND version='v3' AND kind IN ('entry_wait','entry_confirmed','paper_buy','paper_exit',
        'paper_add','kill','skip','strong_agreement') ORDER BY ts,id""", (since,)
    ):
        try:
            detail = json.loads(raw or '{}')
        except ValueError:
            continue
        if detail.get('book', 'v3') != 'v3' or detail.get('experimental'):
            continue
        if mint in cohort:
            if kind in ('entry_wait','entry_confirmed','paper_buy'):
                level = {'entry_wait':1, 'entry_confirmed':2, 'paper_buy':3}[kind]
                for stage in stages[1:level+1]:
                    stage.add(mint)
        names[mint] = symbol or mint[:8]
        reason = detail.get('detail') or detail.get('why') or detail.get('reason') or ''
        item = dict(ts=ts, kind=kind, why=str(reason)[:180])
        votes = (detail.get('council') or {})
        if isinstance(votes,dict) and isinstance(votes.get('votes'),dict):
            item['votes'] = {str(k):str(v)[:100] for k,v in list(votes['votes'].items())[:8]}
        histories[mint].append(item)
        histories[mint] = histories[mint][-10:]
    def recency(m):
        return histories[m][-1]['ts'] if histories.get(m) else 0
    rows = [sorted(group,key=lambda m:(recency(m),m),reverse=True)[:20] for group in stages]
    chosen = set().union(*rows)
    chosen.update(sorted(histories,key=recency,reverse=True)[:60])
    return dict(stages=[dict(label=k,count=len(g),mints=r) for k,g,r in zip(STAGES,stages,rows)],
                tokens={m:dict(symbol=names.get(m,m[:8]),events=histories.get(m,[])) for m in chosen})


def equity_ranges(db,scope,now):
    result = {}
    for label, days in [('24H',1),('7D',7),('All',None)]:
        rows = list(db.execute('SELECT ts,value FROM equity WHERE scope=? AND ts>=? ORDER BY ts',
                               (scope,now-days*86400 if days else 0)))
        stride = max(1,(len(rows)+199)//200)
        points = []
        for start in range(0,len(rows),stride):
            group = rows[start:start+stride]
            points.extend((min(group,key=lambda r:r[1]),max(group,key=lambda r:r[1])))
        if rows:
            points.extend((rows[0],rows[-1]))
        result[label] = sorted({(r[0],r[1]) for r in points})
    return result
