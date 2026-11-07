import json,sqlite3,unittest
from decision_review import build, openings
class ReviewTests(unittest.TestCase):
 def setUp(self):
  self.c=sqlite3.connect(':memory:');self.c.row_factory=sqlite3.Row
  self.c.executescript('CREATE TABLE positions(mint,version,opened,closed,status,pnl,cost,entry,exit,peak,symbol,reason);CREATE TABLE events(ts,kind,mint,symbol,data);CREATE TABLE counterfactual(mint,rule,px0,px1,ts);')
 def tearDown(self):self.c.close()
 def trade(self,m='A',book='v3',opened=99000,closed=99900,status='closed',pnl=2,cost=10):
  self.c.execute('INSERT INTO positions VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(m,book,opened,closed,status,pnl,cost,1,1.2,1.5,m,'stop'))
 def test_partial_aggregate_and_book_match(self):
  self.trade();self.trade(pnl=-1,cost=5);self.trade(book='v3x',pnl=100)
  for book,src in [('vC','wrong'),('v3','pumpfun')]:self.c.execute('INSERT INTO events VALUES(?,?,?,?,?)',(99000,'paper_buy','A','A',json.dumps(dict(book=book,source=src,dex='meteora'))))
  self.c.execute('PRAGMA query_only=ON');r=build(self.c,clock=lambda:100000)
  self.assertEqual(len(r['sources']),1);self.assertEqual(r['sources'][0]['source'],'pumpfun');self.assertEqual(r['sources'][0]['openings'],1);self.assertEqual(r['sources'][0]['realized'],1)
 def test_open_residual_excluded(self):
  self.trade();self.trade(status='open',closed=None);self.assertEqual(build(self.c,clock=lambda:100000)['sources'],[])
 def test_reentry_does_not_inherit_old_source(self):
  self.trade();self.c.execute('INSERT INTO events VALUES(?,?,?,?,?)',(98000,'paper_buy','A','A','{"source":"old"}'));self.assertEqual(build(self.c,clock=lambda:100000)['sources'][0]['source'],'Unknown')
 def test_followup_unknown_quote_and_coverage(self):
  self.c.executemany('INSERT INTO counterfactual VALUES(?,?,?,?,?)',[('A','risk',1,0,99900),('B','liq',1,2,99900)])
  self.c.execute('INSERT INTO events VALUES(?,?,?,?,?)',(99800,'kill','C','C','{}'));m=build(self.c,clock=lambda:100000)['missed'];self.assertEqual((m['measured'],m['unknown'],m['universe']),(1,2,3))
 def test_peak_not_invented_on_time_axis(self):
  self.trade();r=build(self.c,clock=lambda:100000)['replays'][0];self.assertEqual(r['peak_pct'],50);self.assertEqual(len(r['points']),2);self.assertEqual(r['giveback_pp'],30)
 def test_diagnostics_dedupes_and_preserves_unknowns(self):
  self.trade(); self.trade(m='B')
  self.c.executemany('INSERT INTO events VALUES(?,?,?,?,?)',[
   (99980,'kill','A','A','{"reason":"old"}'),(99990,'skip','A','A','{"reason":"volume"}'),
   (99000,'paper_buy','A','A','{"win_prob":1}'),(99000,'paper_buy','B','B','{"win_prob":5}')])
  d=build(self.c,clock=lambda:100000)['diagnostics']
  self.assertEqual(d['reasons'],[('volume',1)])
  self.assertEqual((d['scored'],d['completed'],d['measured']),(1,2,2))
  self.assertEqual(d['calibration'],[dict(band=4,count=1,predicted=100,actual=100)])
 def test_future_trade_excluded_until_report_time(self):
  self.trade(closed=100001)
  self.assertEqual(build(self.c,clock=lambda:100000)['sources'],[])
  self.assertEqual(len(openings(self.c,100001)),1)
 def test_future_records_do_not_crowd_out_valid_history(self):
  self.trade()
  for i in range(501):self.trade(m='future'+str(i),closed=100100+i)
  self.assertEqual([t['mint'] for t in openings(self.c,100000)],['A'])
 def test_invalid_partial_times_reject_whole_opening(self):
  for closed in [None,98999,float('inf'),'broken']:
   with self.subTest(closed=closed):
    self.c.execute('DELETE FROM positions');self.trade();self.trade(closed=closed)
    self.assertEqual(openings(self.c,100000),[])
 def test_invalid_entry_time_rejected(self):
  for opened in [None,'broken',-1,100001]:
   with self.subTest(opened=opened):
    self.c.execute('DELETE FROM positions');self.trade(opened=opened)
    self.assertEqual(openings(self.c,100000),[])
 def test_buy_evidence_cannot_come_after_report_or_exit(self):
  self.trade(opened=99999,closed=100000)
  self.c.execute('INSERT INTO events VALUES(?,?,?,?,?)',(100001,'paper_buy','A','A','{"source":"future"}'))
  self.assertEqual(openings(self.c,100000)[0]['entry'],{})
  self.assertEqual(openings(self.c,100005)[0]['entry'],{})
 def test_future_skips_do_not_inflate_missed_universe(self):
  self.c.executemany('INSERT INTO events VALUES(?,?,?,?,?)',[(99999,'kill','A','A','{}'),(100001,'kill','B','B','{}')])
  self.assertEqual(build(self.c,clock=lambda:100000)['missed']['universe'],1)
 def test_exact_cutoff_and_valid_partial_fills_preserved(self):
  self.trade(closed=99999,pnl=1);self.trade(closed=100000,pnl=-.5)
  self.c.execute('PRAGMA query_only=ON');t=openings(self.c,100000)[0]
  self.assertEqual(t['pnl'],.5);self.assertEqual(len(t['parts']),2)
 def test_invalid_report_clock_rejected(self):
  for now in [None,True,float('nan'),float('inf')]:
   with self.assertRaises(ValueError):openings(self.c,now)
if __name__=='__main__':unittest.main()
