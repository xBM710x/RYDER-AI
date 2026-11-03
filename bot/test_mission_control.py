import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import desk_observations as obs
import mission_control as mc

class MissionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.p1=patch.object(obs,'DB',self.root/'observations.db');self.p1.start()
        self.p2=patch.object(mc,'D',self.root);self.p2.start()
        self.c=sqlite3.connect(':memory:');self.c.row_factory=sqlite3.Row
        self.c.executescript('''CREATE TABLE events(id INTEGER PRIMARY KEY,ts REAL,kind TEXT,mint TEXT,symbol TEXT,data TEXT);
        CREATE TABLE positions(id INTEGER PRIMARY KEY,mint TEXT,symbol TEXT,version TEXT,status TEXT,opened REAL,closed REAL,entry REAL,pnl REAL,reason TEXT);
        CREATE TABLE counterfactual(mint TEXT,rule TEXT,px0 REAL,px1 REAL,ts REAL);
        CREATE TABLE audit(mint TEXT,reason TEXT,kill_px REAL,later_px REAL,ts REAL);''')
    def tearDown(self):self.p1.stop();self.p2.stop();self.c.close();self.tmp.cleanup()
    def event(self,ts,kind,mint='A',**data):self.c.execute('INSERT INTO events(ts,kind,mint,symbol,data) VALUES(?,?,?,?,?)',(ts,kind,mint,mint,json.dumps(data)))
    def build(self):return mc.build(self.c,{'shared_account':{},'stonkfun':{}},{},clock=lambda:100000)
    def test_all_25_without_fabricated_history_or_secrets(self):
        self.event(99900,'start',token='do-not-export',cfg={'SECRET':'no'})
        out=self.build();self.assertEqual({c['id'] for c in out['cards']},set(range(1,26)))
        self.assertNotIn('do-not-export',json.dumps(out));self.assertEqual(out['tokens'],[])
        self.assertEqual(out['cards'][10]['rows'],[])
    def test_collector_preserves_first_seen_and_unknowns(self):
        cd=[dict(mint='A',source='stonkfun',name='A',dex='unknown')]
        obs.observe(cd,{'A':dict(pairCreatedAt=99000000,priceUsd='1',liquidity={'usd':50000})},'hot',clock=lambda:99900)
        obs.observe(cd,{'A':dict(priceUsd='nan',liquidity={})},clock=lambda:99950)
        ts,_=obs.snapshot(clock=lambda:100000);self.assertEqual(ts[0]['first_ts'],99900)
        self.assertIsNone(ts[0]['price']);self.assertIsNone(ts[0]['liquidity']);self.assertEqual(ts[0]['created'],99000)
    def test_partial_fills_calibration_and_cross_book_attribution(self):
        self.event(99000,'paper_buy',book='v3',source='stonkfun',entry_regime='hot',entry_age_min=4,win_prob=.7,liq=30000)
        self.event(99001,'paper_buy',book='vC',source='wrong',win_prob=.1)
        self.c.executemany('INSERT INTO positions VALUES(?,?,?,?,?,?,?,?,?,?)',[
            (1,'A','A','v3','closed',99000,99500,1,2,'partial_tp'),
            (2,'A','A','v3','closed',99000,99600,1,-1,'stop')])
        cards=self.build()['cards'];cal=cards[10]['rows']
        self.assertEqual(cal[0][1],1);self.assertEqual(cal[0][3],100)
        self.assertEqual(cards[2]['rows'][0],['stonkfun',2,1,1.0])
        self.c.execute("INSERT INTO positions VALUES(3,'A','A','v3','open',99000,NULL,1,NULL,NULL)")
        self.assertEqual(self.build()['cards'][10]['rows'],[])
    def test_followups_deduplicate_and_missing_quote_not_a_loss(self):
        self.c.execute("INSERT INTO audit VALUES('A','volume',1,0,99900)")
        self.c.execute("INSERT INTO audit VALUES('B','risk',1,3,99900)")
        self.c.execute("INSERT INTO counterfactual VALUES('B','risk',1,1.5,99950)")
        self.event(99900,'kill',reason='volume');self.event(99900,'kill',mint='C',reason='risk')
        cards=self.build()['cards'];coverage=dict(cards[17]['rows'])
        self.assertEqual(coverage['Sampled skipped-token universe'],3)
        self.assertEqual(coverage['Measured follow-up'],1)
        rows={r[0]:r[1:] for r in cards[18]['rows']};self.assertEqual(rows['volume'],[0,0,0,1]);self.assertEqual(rows['risk'],[1,1,0,0])
    def test_equity_scope_and_drawdown(self):
        obs.equity(300,'shared',clock=lambda:99000);obs.equity(270,'shared',clock=lambda:99500);obs.equity(900,'main',clock=lambda:99600)
        out=mc.build(self.c,{'shared_account':{'equity':270}},{},clock=lambda:100000)
        self.assertEqual(out['cards'][21]['rows'][0][1],10)
        self.assertEqual(len(out['cards'][21]['series'][0]['points']),2)
    def test_private_config_not_in_token_timeline(self):
        obs.observe([dict(mint='A',name='A',source='pumpfun')],{},clock=lambda:99900)
        self.event(99901,'score',score=.7,cfg={'secret':'DO_NOT_EXPORT'})
        self.assertNotIn('DO_NOT_EXPORT',json.dumps(self.build()))
    def test_backup_inventory_no_restore_or_absolute_path(self):
        folder=self.root/'update-backups';folder.mkdir();(folder/'desk-a.db').write_bytes(b'example')
        (folder/'desk-a.db.checked.json').write_text(json.dumps({'integrity':'ok','ts':99900}))
        row=self.build()['cards'][24]['rows'][0];self.assertEqual(row[0],'desk-a.db');self.assertEqual(row[2],'ok')
        self.assertNotIn(str(self.root),json.dumps(self.build()))

class CostTests(unittest.TestCase):
    def test_entry_cost_components_reconcile(self):
        from executor import buy_costs
        quote=1;slip=.01;fee=.003;mv=.002;size=30;fill=quote*(1+slip)/(1-fee)*(1+mv)
        costs=buy_costs(size,fill,quote,slip)
        self.assertAlmostEqual(sum(costs[k] for k in ['fees','slippage','mev']),costs['total'])
        self.assertAlmostEqual(costs['total'],size-size/fill*quote)
    def test_exit_cost_partial_uses_sold_quantity(self):
        from executor import exit_costs
        a=exit_costs({},1,.98,5);b=exit_costs({},1,.98,10)
        self.assertAlmostEqual(a['total']*2,b['total'])
        self.assertAlmostEqual(sum(a[k] for k in ['fees','slippage','mev']),a['total'])

if __name__=='__main__':unittest.main()
