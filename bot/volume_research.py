"""Timed missing-data follow-ups and a separate paired paper-volume study."""
import collections
import queue
import threading
import time
from pathlib import Path
import capacity_lab as lab

DELAYS = (120, 300, 900)
LIMIT = 1000
BOOKS = {'standard': 4, 'lower': 4}
DB = Path(__file__).resolve().parent / 'volume-study.db'
OFFERS = queue.Queue(maxsize=100)


class Followups:
    def __init__(self):
        self.jobs = {}
        self.lock = threading.Lock()
        self.stats = collections.Counter()

    def schedule(self, candidate, now):
        mint = candidate['mint']
        with self.lock:
            if mint in self.jobs:
                return True
            if candidate.get('volume_retry') or len(self.jobs) >= LIMIT:
                self.stats['not_admitted'] += 1
                return False
            self.jobs[mint] = (now, 0, dict(candidate))
            self.stats['scheduled'] += 1
            return True

    def contains(self, mint):
        with self.lock:
            return mint in self.jobs

    def finish(self, mint):
        with self.lock:
            self.jobs.pop(mint,None)

    def due(self, now, blocked, capacity):
        out = []
        with self.lock:
            for mint,(start,index,cd) in list(self.jobs.items()):
                if now-start > 1200:
                    del self.jobs[mint]
                    self.stats['expired'] += 1
                    continue
                if len(out)>=capacity or blocked(mint) or now < start+DELAYS[index]:
                    continue
                # Coalesce overdue slots after a pause instead of issuing back-to-back checks.
                while index+1<len(DELAYS) and now>=start+DELAYS[index+1]:
                    index += 1
                out.append(dict(cd,volume_retry=DELAYS[index]))
                if index+1==len(DELAYS):
                    del self.jobs[mint]
                else:
                    self.jobs[mint]=(start,index+1,cd)
                self.stats['checked'] += 1
        return out

    def watch(self, now):
        with self.lock:
            return [dict(mint=m,symbol=cd.get("name") or m[:8],due=start+DELAYS[i],reason=cd.get("retry_reason","missing volume"))
                    for m,(start,i,cd) in sorted(self.jobs.items(),key=lambda x:x[1][0]+DELAYS[x[1][1]])[:12]]

    def status(self):
        with self.lock:
            return dict(self.stats,pending=len(self.jobs))


FOLLOW = Followups()


def offer(cd, pair, volume, threshold, now):
    if volume is None or volume < threshold*0.75:
        return
    price=lab.positive(pair.get('priceUsd'))
    liq=lab.positive((pair.get('liquidity') or {}).get('usd'))
    stamp=lab.positive(pair.get('_ts'))
    if not price or not liq or not stamp or not 0<=now-stamp<=30:
        return
    signal=dict(mint=cd['mint'],symbol=(pair.get('baseToken') or {}).get('symbol') or cd['name'],
                quote=price,liq=liq,observed=stamp,offered=now,source=cd.get('source') or 'unknown',
                books=['standard','lower'] if volume>=threshold else ['lower'])
    try:
        OFFERS.put_nowait(signal)
    except queue.Full:
        pass


def worker():
    from common import dex_market
    while True:
        db=None
        try:
            db=lab.connect(DB,BOOKS)
            for _ in range(30):
                try:
                    signal=OFFERS.get_nowait()
                except queue.Empty:
                    break
                lab.enter(db,signal,limits={b:BOOKS[b] for b in signal['books']})
            mints=[r[0] for r in db.execute('SELECT DISTINCT mint FROM fills WHERE closed IS NULL')]
            if mints:
                lab.mark(db,dex_market(mints))
        except Exception as err:
            print('volume study worker:',type(err).__name__,flush=True)
        finally:
            if db is not None: db.close()
        time.sleep(15)


def summary():
    return lab.summary(db_path=DB,limits=BOOKS).get('books',[])


def evidence(db,now):
    import json
    counts = collections.defaultdict(collections.Counter)
    for raw, in db.execute("""SELECT data FROM events WHERE kind='kill' AND ts>=?
                              ORDER BY ts DESC LIMIT 4000""",(now-86400,)):
        try:
            event=json.loads(raw)
        except (ValueError,TypeError):
            continue
        if event.get('reason') != 'volume_1h': continue
        tag=(event.get('checks') or {}).get('volume_1h','').split('/')[0]
        key={'unknown':'missing','fail':'low'}.get(tag,'unclassified')
        venue=str(event.get('dex') or event.get('source') or 'unknown').lower()
        counts[venue][key]+=1
    attempts=collections.Counter()
    for raw, in db.execute("SELECT data FROM events WHERE kind='volume_followup' AND ts>=?",(now-86400,)):
        try: record=json.loads(raw)
        except (ValueError,TypeError): continue
        attempts['checked']+=1
        attempts['observed']+=record.get('volume') in ('pass','fail')
        attempts['passed']+=record.get('passed_filters') is True
    return dict(venues=dict(counts),attempts=dict(attempts))
