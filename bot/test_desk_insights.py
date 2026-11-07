import json,sqlite3,unittest
from desk_insights import build
class InsightTests(unittest.TestCase):
 def setUp(self):
  self.c=sqlite3.connect(':memory:');self.c.row_factory=sqlite3.Row
  self.c.executescript('CREATE TABLE positions(mint,version,opened,closed,status,pnl,cost,entry,exit,peak,symbol,reason);CREATE TABLE events(ts,kind,mint,symbol,data);')
  self.now=1794034800
 def tearDown(self):self.c.close()
 def event(self,kind,m='A',ago=10,**d):self.c.execute('INSERT INTO events VALUES(?,?,?,?,?)',(self.now-ago,kind,m,m,json.dumps(d)))
 def trade(self,pnl=2,peak=1.2,book='v3',closed=None):
  self.c.execute('INSERT INTO positions VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',('A',book,self.now-100,self.now-20 if closed is None else closed,'closed',pnl,10,1,1.1,peak,'A','stop'))
 def report(self,hb=None,data=None):return build(self.c,hb or {'ts':self.now},data or {},self.now)
 def test_empty_does_not_claim_no_opportunities(self):
  r=self.report();self.assertEqual(r['health']['state'],'scanning stalled or unreported');self.assertEqual(r['confidence'],[]);self.assertEqual(r['recap']['completed'],0)
 def test_stale_future_and_errors(self):
  self.event('scan');self.assertEqual(self.report({'ts':self.now+1})['health']['state'],'runner stale')
  self.event('error',where='fetch');self.assertIn('worker errors',self.report()['health']['state'])
 def test_pending_numeric_latest_and_timestamp(self):
  self.event('scan');r=self.report({'ts':self.now,'watch':[dict(sym='A',mint='A',latest=1.2,quote_ts=self.now-1,wait_left=20)]})
  self.assertEqual(r['pending'][0]['ready_at'],self.now+20);self.assertTrue(r['pending'][0]['quote_fresh']);self.assertIn('pending',r['health']['state'])
 def test_quote_missing_not_fresh(self):
  r=self.report({'ts':self.now,'watch':[dict(sym='A',latest=1.2)]});self.assertFalse(r['pending'][0]['quote_fresh']);self.assertIsNone(r['pending'][0]['ready_at'])
 def test_confidence_conditions_partial_fills(self):
  self.trade();self.trade(-1);self.event('paper_buy',ago=100,council={'votes':{'Analyst':[.8,'yes'],'bad':[2,'invalid']}},entry_strategy='pullback',intelligence_features={'momentum':3,'volume':2000})
  r=self.report();self.assertEqual(r['confidence'][0]['n'],1);self.assertEqual(len(r['confidence']),1);self.assertEqual(r['confidence'][0]['net'],1)
  self.assertEqual(r['conditions'][0]['condition'],'uptrend');self.assertEqual(r['exits'][0]['capture_pct'],50);self.assertEqual(r['exits'][0]['giveback_pp'],10)
 def test_missing_peak_and_future_exit(self):
  self.trade(peak=None);self.assertIsNone(self.report()['exits'][0]['capture_pct'])
  self.c.execute('DELETE FROM positions');self.trade(closed=self.now+1);self.assertEqual(self.report()['exits'],[])
 def test_skip_association_and_invalid_followups(self):
  self.event('kill',ago=1000,reason='liquidity');d={'session_research':{'replays':[dict(mint='A',symbol='A',entry=self.now-900,exit=self.now-300,net=1),dict(mint='B',entry=self.now,exit=self.now+1,net=999)]}}
  r=self.report(data=d);self.assertEqual(len(r['missed']),1);self.assertEqual(r['missed'][0]['reason'],'liquidity')
 def test_readonly_and_future_events_excluded(self):
  self.event('scan',ago=-10);self.c.execute('PRAGMA query_only=ON');r=self.report();self.assertIsNone(r['health']['scan_at'])
 def test_source_counters_not_recent_errors(self):
  r=self.report({'ts':self.now,'sources':{'dex':{'last_ok':self.now-1,'err':100,'ok':200}}});self.assertEqual(r['health']['sources'][0]['status'],'recent success');self.assertEqual(r['health']['recent_errors'],[])
if __name__=='__main__':unittest.main()
