import unittest,sqlite3,json
from unittest.mock import patch
import intelligence as i
class IntelligenceTests(unittest.TestCase):
 def f(self,**kw):
  f=dict(liquidity=30000,momentum=3,age_s=400,buys=30,sells=10,volume=3000,quote_age_s=3,price=1);f.update(kw);return f
 def db(self):
  c=sqlite3.connect(':memory:');c.row_factory=sqlite3.Row;return c
 def test_missing_and_future_quotes_withhold_confidence(self):
  for age in [None,-1,31]:self.assertEqual(i.quality(self.f(quote_age_s=age))['confidence'],'withheld')
  self.assertIsNone(i.quality(self.f())['unique_buyers'])
  self.assertEqual(i.quality(self.f())['buy_share'],.75)
 def test_invalid_values_are_not_features(self):
  f=i.features({'priceUsd':'nan','_ts':float('inf'),'liquidity':{'usd':True}},100)
  self.assertIsNone(f['price']);self.assertIsNone(f['liquidity']);self.assertEqual(i.quality(f)['confidence'],'withheld')
 def test_similarity_excludes_same_mint_and_future_outcomes(self):
  cases=[dict(mint='a',closed=90,features=self.f(),net_pct=3,symbol='A'),dict(mint='b',closed=110,features=self.f(),net_pct=100,symbol='B'),dict(mint='c',closed=80,features=self.f(),net_pct=-2,symbol='C')]
  r=i.neighbors(cases,self.f(),'a',100,1)
  self.assertEqual(r['n'],1);self.assertEqual(r['mean_net_pct'],-2)
  self.assertIsNone(i.neighbors(cases,self.f(),'a',100,10)['mean_net_pct'])
 def test_missing_and_distant_features_excluded(self):
  self.assertIsNone(i.distance(self.f(),{}));self.assertGreater(i.distance(self.f(),self.f(liquidity=1e12,momentum=100)),1)
 def test_regime_no_guessing(self):
  self.assertEqual(i.regime({}),'unknown');self.assertEqual(i.regime(self.f()),'uptrend');self.assertEqual(i.regime(self.f(volume=200)),'quiet')
 def test_mistake_labels_do_not_claim_unavoidable_or_rug(self):
  t=dict(entry={},parts=[dict(entry=1,exit=.9,peak=1.3,closed=100)],cost=10,pnl=-1)
  labels=i.classify(t);self.assertIn('Net loss; cause requires review',labels)
  self.assertTrue(any('peak' in l for l in labels));self.assertFalse(any('rug' in l for l in labels))
 def test_version_activation_and_rollback(self):
  c=self.db();i.schema(c);original=c.execute('SELECT version FROM intelligence_active').fetchone()[0]
  second=i.save_version(c,dict(i.BASE,min_train=50));c.commit()
  self.assertEqual(i.activate(c,second,'candidate research trial'),original)
  self.assertEqual(i.activate(c,original,'revert trial'),second)
  self.assertEqual(c.execute('SELECT COUNT(*) FROM intelligence_history').fetchone()[0],2)
  with self.assertRaises(ValueError):i.activate(c,'fake','bad')
  with self.assertRaises(ValueError):i.save_version(c,dict(i.BASE,min_train=1))
  c.close()
 def test_held_out_evaluation_uses_only_prior_completed_trades(self):
  from learning_evaluation import evaluate
  samples=[dict(mint=str(n),opened=n*100,closed=n*100+50,score=.7,pnl=1,roi=.1) for n in range(60)]
  out=evaluate(samples,40,10);self.assertEqual(len(out['folds']),2);self.assertFalse(out['promotion_allowed'])
  for s in samples[:40]:s['closed']=10000
  self.assertFalse(evaluate(samples,40,10)['folds'])
 def test_export_persists_cases_without_changing_ledger(self):
  c=self.db();o=self.db()
  c.executescript('CREATE TABLE positions(mint,version,opened,closed,status,pnl,cost,entry,exit,peak,symbol,reason);CREATE TABLE events(id INTEGER PRIMARY KEY,ts,kind,mint,symbol,data);')
  c.execute("INSERT INTO positions VALUES('m','v3',100,200,'closed',1,10,1,1.1,1.2,'M','trailing_stop')")
  e=dict(book='v3',score=.7,win_prob=.7,intelligence_features=self.f(),entry_strategy='momentum',council={'votes':{'risk':[.3,'concern']}})
  c.execute('INSERT INTO events(ts,kind,mint,symbol,data) VALUES(?,?,?,?,?)',(100,'paper_buy','m','M',json.dumps(e)));c.commit()
  before=c.total_changes;r=i.build(c,o,{}, {'intelligence_release':i.RELEASE},300)
  self.assertEqual(c.total_changes,before);self.assertEqual(r['memory_cases'],1);self.assertEqual(r['calibration'][0]['actual'],1)
  self.assertEqual(r['objections']['risk']['objected_gain'],1)
  self.assertEqual(i.build(c,o,{}, {},300)['memory_cases'],1)
  c.close();o.close()
if __name__=='__main__':unittest.main()
