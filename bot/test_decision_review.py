import json,sqlite3,unittest
from decision_review import build
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
if __name__=='__main__':unittest.main()
