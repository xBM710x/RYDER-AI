import json, sqlite3, tempfile, unittest
from pathlib import Path
import decision_ops as d

def pair(t=100,px=1,pool='pool',liq=30000):
 return dict(priceUsd=px,liquidity={'usd':liq},_ts=t,pairAddress=pool,volume={'m5':3000,'h1':10000},txns={'m5':{'buys':20,'sells':10}},priceChange={'m5':3})
class OpsTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'timing.db';self.c=d.connect(self.path)
 def tearDown(self):self.c.close();self.tmp.cleanup()
 def admit(self):d.admit(self.c,dict(mint='A',symbol='A',pair=pair()),100)
 def state(self,strategy='breakout'):return dict(self.c.execute('SELECT * FROM trials WHERE strategy=?',(strategy,)).fetchone())
 def test_quote_rejects_stale_future_invalid(self):
  for q in [pair(60),pair(101),pair(px=float('nan')),pair(px=True),pair(pool=''),pair(liq=0)]:self.assertIsNone(d.quote(q,100))
 def test_ranking_requires_complete_fresh_inputs(self):
  self.assertGreater(d.rank(pair(),100)['score'],0);self.assertEqual(d.rank(pair(60),100)['score'],0)
  q=pair();q['txns']={};self.assertEqual(d.rank(q,100)['score'],0)
 def test_retry_never_overrides_safety(self):
  self.assertFalse(d.retryable('rug:fail',pair(),100));self.assertTrue(d.retryable('liquidity:unknown',None,100))
  self.assertTrue(d.retryable('volume_1h:fail',pair(),100));self.assertFalse(d.retryable('volume_1h:fail',pair(liq=100),100))
 def test_fill_costs_and_capacity(self):
  buy=d.fill(1,25,30000,'buy');sell=d.fill(1,25,30000,'sell');self.assertLess(25/buy*sell,25)
  self.assertIsNone(d.fill(1,25,100,'buy'));self.assertIsNone(d.fill(1,25,30000,'bad'))
 def test_breakout_delayed_distinct_same_pool_execution(self):
  self.admit();d.advance(self.c,{'A':pair(101,1.03)},101);self.assertEqual(self.state()['status'],'triggered')
  for q,t in [(pair(101,1.03),110),(pair(111,1.03,'other'),111),(pair(70,1.03),112)]:d.advance(self.c,{'A':q},t);self.assertEqual(self.state()['status'],'triggered')
  d.advance(self.c,{'A':pair(115,1.03)},115);self.assertEqual(self.state()['status'],'open')
  d.advance(self.c,{'A':pair(415,1.03)},415);self.assertEqual(self.state()['status'],'closed');self.assertLess(self.state()['pnl'],0)
 def test_pullback_and_continuation(self):
  self.admit();d.advance(self.c,{'A':pair(110,.97)},110);d.advance(self.c,{'A':pair(120,.985)},120)
  self.assertEqual(self.state('pullback')['status'],'triggered')
  d.advance(self.c,{'A':pair(130,1)},130);d.advance(self.c,{'A':pair(140,1.01)},140);self.assertEqual(self.state('continuation')['status'],'triggered')
 def test_unresolved_dedup_and_capacity(self):
  self.admit();self.admit();self.assertEqual(self.c.execute('SELECT COUNT(*) FROM trials').fetchone()[0],3)
  for i in range(30):d.admit(self.c,dict(mint=str(i),symbol='B',pair=pair()),100)
  self.assertEqual(self.c.execute('SELECT COUNT(DISTINCT mint) FROM trials').fetchone()[0],24)
  d.advance(self.c,{},2000);self.assertEqual(self.state()['status'],'unresolved');self.assertIsNone(self.state()['pnl'])
 def test_report_readonly_scope_votes_and_book_isolation(self):
  c=sqlite3.connect(':memory:');c.row_factory=sqlite3.Row
  c.executescript('CREATE TABLE positions(mint,version,opened,closed,status,pnl,cost,entry,exit,peak,symbol,reason);CREATE TABLE events(ts,kind,mint,symbol,data);')
  for pnl,cost in [(2,10),(-1,5)]:c.execute('INSERT INTO positions VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',('A','v3',100,200,'closed',pnl,cost,1,1.2,1.5,'A','stop'))
  rows=[(100,'paper_buy','A','A',{'book':'v3','council':{'votes':{'analyst':[.8,'yes']}}}),(110,'skip','A','A',{'book':'vC','reason':'wrong book'}),(210,'kill','B','B',{'checks':{'liquidity':'unknown/dex','volume':'fail/dex'}}),(220,'kill','B','B',{'checks':{'volume':'fail/dex'}}),(221,'kill','C','C',{'checks':{'liquidity':'unknown/dex'}}),(400,'kill','D','D',{})]
  c.executemany('INSERT INTO events VALUES(?,?,?,?,?)',[(a,b,m,s,json.dumps(e)) for a,b,m,s,e in rows]);c.execute('PRAGMA query_only=ON')
  r=d.report(c,{'ts':299},{},300,self.path);self.assertFalse(r['live_ready']);self.assertTrue(r['health']['runner_fresh'])
  self.assertEqual(r['blocker_counts'],{'failed rule':1,'missing data':1,'recorded gate; details below':1})
  self.assertEqual(r['accountability']['analyst']['approve_gain'],1);self.assertEqual(r['replays'][0]['net'],1)
  self.assertNotIn('wrong book',str(r['replays']));self.assertFalse(d.report(c,{'ts':301},{},300,self.path)['health']['runner_fresh']);c.close()
if __name__=='__main__':unittest.main()
