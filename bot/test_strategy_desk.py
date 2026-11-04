import unittest
from strategy_desk import setup,confirmed,near,exit_policy
from paper_entry_window import threshold
from volume_research import Followups


class DeskTests(unittest.TestCase):
    def setUp(self):
        self.p=dict(volume=dict(h1=14000,m5=3000),liquidity=dict(usd=30000),
                    priceChange=dict(h1=18,m5=-2),txns=dict(m5=dict(buys=28,sells=12)),
                    pairAddress='a',priceUsd='1.01',_ts=100)
    def test_pullback_must_recover_before_fill(self):
        self.assertEqual(setup(self.p,105),'pullback')
        self.assertEqual(threshold(self.p,40000,105),10000)
        self.assertTrue(confirmed('pullback',1,self.p,'a',105))
        self.assertFalse(confirmed('pullback',1,self.p,'a',105,100))
        for p in [dict(self.p,priceUsd='0.99'),dict(self.p,pairAddress='b'),
                  dict(self.p,liquidity={}),dict(self.p,_ts=60)]:
            self.assertFalse(confirmed('pullback',1,p,'a',105))
    def test_no_pullback_if_downtrend(self):
        self.assertEqual(setup(dict(self.p,priceChange=dict(h1=-8,m5=-2)),105),'standard')
    def test_momentum_requires_persistent_activity(self):
        self.assertFalse(confirmed('momentum',1,self.p,'a',105))
        self.assertTrue(confirmed('momentum',1,dict(self.p,priceChange=dict(m5=3)),'a',105))
    def test_stale_or_missing_volume_cannot_get_active_admission(self):
        self.assertEqual(setup(self.p,150),'standard')
        self.assertEqual(setup(dict(self.p,volume={}),105),'standard')
    def test_partial_profit_and_trail_vary_by_pressure(self):
        self.assertEqual(exit_policy(self.p),(1/3,.09))
        self.assertEqual(exit_policy(dict(txns=dict(m5=dict(buys=8,sells=15)))),(2/3,.045))
        self.assertEqual(exit_policy({}),(.5,None))
    def test_watch_retries_are_bounded(self):
        self.assertTrue(near(self.p,105)); self.assertFalse(near(self.p,150))
        f=Followups(); f.schedule(dict(mint='m',name='M',retry_reason='liquidity'),100)
        self.assertEqual(f.watch(110)[0]['due'],220)
        self.assertFalse(f.due(220,lambda _:True,1))
        self.assertEqual(f.due(220,lambda _:False,1)[0]['mint'],'m')
    def test_evidence_groups_partial_fills_and_preserves_unknown_history(self):
        import json,sqlite3
        from strategy_desk import evidence
        c=sqlite3.connect(':memory:'); c.row_factory=sqlite3.Row
        c.executescript('CREATE TABLE positions(mint,version,opened,closed,status,pnl,cost,entry,exit,peak,symbol,reason); CREATE TABLE events(id INTEGER PRIMARY KEY,ts,kind,mint,symbol,data);')
        for pnl,closed,reason in [(2,105,'partial_tp'),(-3,110,'trailing_stop')]:
            c.execute('INSERT INTO positions VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',('m','v3',100,closed,'closed',pnl,10,1,1+pnl/10,1.4,'M',reason))
        c.execute('INSERT INTO events(ts,kind,mint,symbol,data) VALUES(?,?,?,?,?)',(100,'paper_buy','m','M',json.dumps({'book':'v3','entry_strategy':'pullback'})))
        c.execute('INSERT INTO events(ts,kind,mint,symbol,data) VALUES(?,?,?,?,?)',(112,'strategy_block','n','N',json.dumps({'strategy':'standard','reason':'liquidity'})))
        r=evidence(c,[],[],120)
        self.assertEqual((r['score']['pullback']['closed'],r['score']['pullback']['net'],r['score']['pullback']['dd']),(1,-1,1))
        self.assertEqual(len(r['replays'][0]['fills']),2)
        self.assertEqual(r['blocked'][0][2],'liquidity')
        c.close()
