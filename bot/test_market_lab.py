import ast
import collections
import json
import queue
import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch
import market_breadth as breadth
from scan_scheduler import Scheduler
import capacity_lab as lab
import learning_evaluation as evaluation

class BreadthTests(unittest.TestCase):
    def row(self,mint='A'*32):
        return dict(attributes=dict(name='TOKEN / SOL'),relationships=dict(base_token=dict(data=dict(id='solana_'+mint)),dex=dict(data=dict(id='meteora'))))
    def test_dedupe_validation_and_cadence(self):
        d=breadth.Discovery();calls=[]
        def fetch(url):calls.append(url);return dict(data=[self.row(),self.row(),self.row('bad')])
        self.assertEqual(len(d.discover(fetch,clock=lambda:1000)),1)
        self.assertIn('page=3',calls[0]);self.assertEqual(d.discover(fetch,clock=lambda:1050),[])
        d.discover(fetch,clock=lambda:1090);self.assertIn('page=4',calls[-1])
    def test_schema_failure_backs_off(self):
        d=breadth.Discovery();self.assertEqual(d.discover(lambda _:dict(bad=[]),clock=lambda:1000),[])
        self.assertEqual(d.next,1180);self.assertEqual(d.stats['errors'],1)
    def test_rotates_supported_pages(self):
        self.assertEqual(max(p for _,p in breadth.PLAN),10)
        self.assertEqual({r for r,_ in breadth.PLAN},{'new_pools','trending_pools','pools'})

class SchedulerTests(unittest.TestCase):
    def test_bound_dedupe_and_backpressure(self):
        s=Scheduler(capacity=3,max_inflight=2);s.offer([dict(mint=str(i),source='a') for i in range(5)],clock=lambda:100)
        self.assertEqual(len(s.pending),3);self.assertEqual(s.stats['overflow'],2)
        self.assertEqual(len(s.take({'busy'},clock=lambda:101)),1)
        self.assertEqual(s.take({'busy','busy2'},clock=lambda:101),[])
    def test_source_fairness(self):
        s=Scheduler(max_inflight=2)
        s.offer([dict(mint=str(i),source='flood') for i in range(100)]+[dict(mint='rare',source='rare')],clock=lambda:100)
        self.assertIn('rare',[r['mint'] for r in s.take(set(),clock=lambda:101)])
    def test_expired_rejected_and_inflight_not_redispatched(self):
        s=Scheduler(ttl=10);s.offer([dict(mint='old'),dict(mint='reject'),dict(mint='busy')],clock=lambda:100)
        out=s.take({'busy'},lambda m:m=='reject',clock=lambda:105);self.assertEqual([x['mint'] for x in out],['old'])
        self.assertEqual(s.take(set(),clock=lambda:120),[])
    def test_duplicate_preserves_first_seen(self):
        s=Scheduler(ttl=10);s.offer([dict(mint='A',score=1)],clock=lambda:100)
        s.offer([dict(mint='A',score=2)],clock=lambda:109)
        self.assertEqual(s.take(set(),clock=lambda:111),[])

class CapacityTests(unittest.TestCase):
    def setUp(self):
        self.c=sqlite3.connect(':memory:');self.c.row_factory=sqlite3.Row
        self.c.executescript("""CREATE TABLE wallets(book TEXT PRIMARY KEY,cash REAL);
        CREATE TABLE fills(id INTEGER PRIMARY KEY,book TEXT,mint TEXT,symbol TEXT,source TEXT,opened REAL,entry REAL,qty REAL,cost REAL,peak REAL,mark REAL,mark_ts REAL,closed REAL,exit REAL,pnl REAL,reason TEXT);
        CREATE TABLE signals(mint TEXT,ts REAL,source TEXT,PRIMARY KEY(mint,ts));
        INSERT INTO wallets VALUES('control',300),('challenger',300);""")
    def tearDown(self):self.c.close()
    def signal(self,m='A',t=100000):return dict(mint=m,symbol=m,quote=1,liq=50000,observed=t,offered=t,score=.7,source='test')
    def test_capacity_only_difference_and_no_real_ledger(self):
        for i in range(10):lab.enter(self.c,self.signal(str(i)),clock=lambda:100000)
        counts=dict(self.c.execute('SELECT book,COUNT(*) FROM fills GROUP BY book'))
        self.assertEqual(counts,dict(control=4,challenger=8))
        self.assertFalse(self.c.execute("SELECT name FROM sqlite_master WHERE name='account'").fetchone())
        self.assertGreaterEqual(min(r[0] for r in self.c.execute('SELECT cash FROM wallets')),0)
    def test_duplicate_signal_no_duplicate_position(self):
        for _ in range(3):lab.enter(self.c,self.signal(),clock=lambda:100000)
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM fills').fetchone()[0],2)
    def test_stale_and_future_quotes_never_fill(self):
        lab.enter(self.c,self.signal(t=99000),clock=lambda:100000)
        lab.enter(self.c,self.signal(t=100001),clock=lambda:100000)
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM fills').fetchone()[0],0)
    def test_missing_quote_not_fake_exit(self):
        lab.enter(self.c,self.signal(),clock=lambda:100000)
        lab.mark(self.c,{},clock=lambda:102000)
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM fills WHERE closed IS NOT NULL').fetchone()[0],0)
    def test_stop_exit_includes_costs(self):
        lab.enter(self.c,self.signal(),clock=lambda:100000)
        lab.mark(self.c,{'A':dict(priceUsd=.8,_ts=100015,liquidity=dict(usd=50000))},clock=lambda:100015)
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM fills WHERE closed IS NOT NULL').fetchone()[0],2)
        self.assertTrue(all(r[0]<0 for r in self.c.execute('SELECT pnl FROM fills')))
    def test_daily_loss_cap(self):
        self.c.execute("INSERT INTO fills(book,mint,opened,closed,pnl) VALUES('control','prior',99900,99999,-45)")
        lab.enter(self.c,self.signal(),clock=lambda:100000)
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM fills WHERE book='control' AND closed IS NULL").fetchone()[0],0)
    def test_offer_requires_fresh_price_and_liquidity(self):
        q=queue.Queue(maxsize=1)
        with patch.object(lab,'QUEUE',q):
            self.assertFalse(lab.offer('A','A',dict(priceUsd=1,_ts=100000),.7,clock=lambda:100000))
            pair=dict(priceUsd=1,_ts=100000,liquidity=dict(usd=50000))
            self.assertTrue(lab.offer('A','A',pair,.7,clock=lambda:100000))
            self.assertFalse(lab.offer('B','B',pair,.7,clock=lambda:100000))
    def test_executor_handoff_occurs_after_gates_before_cap_and_debit(self):
        s=Path(__file__).with_name('executor.py').read_text()
        self.assertLess(s.index('skz ='),s.index("capacity_lab"))
        self.assertLess(s.index('size = pa.cap_order'),s.index("capacity_lab"))
        self.assertLess(s.index("capacity_lab"),s.index("fully_gated=True"))
        self.assertLess(s.index("fully_gated=True"),s.index('INSERT INTO positions('))
        self.assertIn('lab_eligible',s);self.assertIn('c.rollback(); c.close()',s)

class EvaluationTests(unittest.TestCase):
    def samples(self):
        return [dict(mint=str(i),opened=i*100,closed=i*100+50,score=.6 if i%2 else .8,pnl=-1 if i%2 else 2,roi=-.03 if i%2 else .06) for i in range(70)]
    def test_no_future_outcome_leakage(self):
        a=self.samples();b=[dict(x) for x in a]
        for x in b[40:]:x['pnl']*=-100;x['roi']*=-100
        first=evaluation.evaluate(a)['folds'][0];other=evaluation.evaluate(b)['folds'][0]
        self.assertEqual(first['threshold'],other['threshold'])
        self.assertNotEqual(first['challenger']['mean_net_pct'],other['challenger']['mean_net_pct'])
    def test_overlap_purge_and_insufficient_data(self):
        x=self.samples()
        for s in x[:40]:s['closed']=999999
        self.assertEqual(evaluation.evaluate(x)['folds'],[])
        self.assertFalse(evaluation.evaluate([])['promotion_allowed'])
    def test_confidence_interval_and_no_promotion(self):
        out=evaluation.evaluate(self.samples());self.assertTrue(out['folds']);self.assertFalse(out['promotion_allowed'])
        m=evaluation.metrics(self.samples())
        self.assertTrue(0<=m['win_rate_interval_95'][0]<=m['win_rate_interval_95'][1]<=100)


class ExecutorRegressionTests(unittest.TestCase):
    def run_gate(self,stale=False,budget=True):
        import executor,types
        from contextlib import ExitStack
        c=sqlite3.connect(':memory:');c.row_factory=sqlite3.Row
        c.executescript("""CREATE TABLE account(k TEXT PRIMARY KEY,v REAL);
        CREATE TABLE positions(id INTEGER PRIMARY KEY,mint TEXT,symbol TEXT,pair TEXT,entry REAL,qty REAL,cost REAL,stop REAL,peak REAL,trailing INT,opened REAL,closed REAL,exit REAL,pnl REAL,reason TEXT,status TEXT,version TEXT);
        INSERT INTO account VALUES('cash_main_copy',300);""")
        for i in range(4):c.execute("INSERT INTO positions(mint,cost,pnl,opened,closed,status,version) VALUES(?,10,1,99999,99999,'closed','v3')",(str(i),))
        c.commit()
        class Conn:
            def execute(self,*a):return c.execute(*a)
            def commit(self):return c.commit()
            def rollback(self):return c.rollback()
            def close(self):pass
        wrapper=Conn();offered=[]
        modules={
         'brain17':types.SimpleNamespace(stale=lambda p:'stale' if stale else None,liq_blocked=lambda *a:None,gate=lambda m,s,p,x,v,e:(True,e)),
         'brain15':types.SimpleNamespace(size_mult=lambda *a:(1,[])),
         'brain6':types.SimpleNamespace(split_slip=lambda *a:.005),
         'brain19':types.SimpleNamespace(mood_mult=lambda:(1,'normal')),
         'brain18':types.SimpleNamespace(two_loss_mult=lambda *a:1,skeptic=lambda *a:None),
         'capacity_lab':types.SimpleNamespace(offer=lambda *a:offered.append(a))}
        with ExitStack() as stack:
            stack.enter_context(patch.dict('sys.modules',modules))
            for obj,name,value in [(executor,'conn',lambda:wrapper),(executor,'log',lambda *a,**k:None),(executor.time,'time',lambda:100000),(executor.pa,'MODE',True),(executor.pa,'ensure',lambda *a,**k:None),(executor.pa,'key_for',lambda *a:'cash_main_copy'),(executor.pa,'cap_order',lambda c,v,size,*a:size if budget else 0)]:
                stack.enter_context(patch.object(obj,name,value))
            executor.buy('A','A',dict(priceUsd=1,_ts=100000,pairAddress='pair',liquidity=dict(usd=50000)),.7,extra=dict(_runner_eligible=True,source='test'))
        cash=c.execute("SELECT v FROM account WHERE k='cash_main_copy'").fetchone()[0]
        count=c.execute('SELECT COUNT(*) FROM positions').fetchone()[0]
        c.close();return offered,cash,count
    def test_hourly_block_never_debits_shared_account(self):
        offers,cash,count=self.run_gate()
        self.assertEqual(len(offers),1);self.assertEqual(cash,300);self.assertEqual(count,4)
    def test_stale_gate_cannot_reach_capacity_lab(self):
        offers,cash,count=self.run_gate(stale=True)
        self.assertEqual(offers,[]);self.assertEqual(cash,300)
    def test_final_budget_veto_cannot_reach_capacity_lab(self):
        offers,cash,count=self.run_gate(budget=False)
        self.assertEqual(offers,[]);self.assertEqual(cash,300)

if __name__=='__main__':unittest.main()

