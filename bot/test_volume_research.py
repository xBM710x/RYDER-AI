import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import capacity_lab
import volume_research as vr


class VolumeResearchTests(unittest.TestCase):
    def test_schedule_is_relative_to_first_missing_event(self):
        jobs=vr.Followups()
        candidate=dict(mint='M',name='M',dex='pumpfun',source='ws')
        jobs.schedule(candidate,0)
        jobs.schedule(candidate,90)
        for at,expected in [(119,[]),(120,[120]),(299,[]),(301,[300]),(900,[900]),(901,[])]:
            due=jobs.due(at,lambda mint:False,2)
            self.assertEqual([d['volume_retry'] for d in due],expected)
        self.assertFalse(jobs.contains('M'))
        self.assertFalse(jobs.schedule(dict(candidate,volume_retry=900),902))

    def test_dedupe_and_safety(self):
        jobs=vr.Followups()
        jobs.schedule(dict(mint='A'),0)
        self.assertFalse(jobs.due(120,lambda m:True,1))
        self.assertEqual(jobs.due(310,lambda m:False,1)[0]['volume_retry'],300)
        jobs.finish('A')
        self.assertFalse(jobs.due(900,lambda m:False,1))

    def test_missing_is_separate_from_measured_fail(self):
        db=sqlite3.connect(':memory:')
        db.execute('CREATE TABLE events(kind,ts,data)')
        for tag in ('unknown','fail'):
            db.execute('INSERT INTO events VALUES(?,?,?)',('kill',100,json.dumps(dict(reason='volume_1h',dex='meteora',checks={'volume_1h':tag+'/dexscreener'}))))
        self.assertEqual(vr.evidence(db,100)['venues']['meteora'],{'missing':1,'low':1})

    def test_threshold_isolation_and_costs(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'test.db'
            db=capacity_lab.connect(path,vr.BOOKS)
            pair=dict(priceUsd=1,liquidity=dict(usd=50000),_ts=1000)
            for mint,volume in [('below',74),('lower',75),('both',100)]:
                vr.offer(dict(mint=mint,name=mint),pair,volume,100,1000)
            for _ in range(2):
                signal=vr.OFFERS.get_nowait()
                capacity_lab.enter(db,signal,clock=lambda:1000,limits={b:4 for b in signal['books']})
            fills=db.execute('SELECT book,mint,entry FROM fills').fetchall()
            self.assertEqual({(r[0],r[1]) for r in fills},{('lower','lower'),('standard','both'),('lower','both')})
            self.assertTrue(all(r[2]>1 for r in fills))
            db.close()
