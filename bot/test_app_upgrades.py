import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import stonkfun as st
import app_upgrades

class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        st._NEXT=0;st._ERRORS=0
        self.tmp=tempfile.TemporaryDirectory();self.p=patch.object(st,'STATE_FILE',Path(self.tmp.name)/'status.json');self.p.start()
    def tearDown(self):self.p.stop();self.tmp.cleanup()
    def row(self):return dict(mint='So11111111111111111111111111111111111111112',symbol='FIXTURE',quote=dict(symbol='TEST'),market=dict(priceUsd='0.02'))
    def test_candidates_unknowns_and_no_quote_conversion(self):
        out=st.discover(lambda u:dict(data=dict(tokens=[self.row()])),clock=lambda:1000)
        self.assertEqual(out[0]['source'],'stonkfun');self.assertEqual(out[0]['source_price_usd'],.02)
        self.assertIsNone(out[0]['source_liquidity_usd']);self.assertEqual(out[0]['quote_symbol'],'TEST')
        self.assertNotIn('safe',out[0]);self.assertTrue(st.status(clock=lambda:1001)['ok'])
    def test_deduplicates_and_poll_spacing(self):
        calls=[]
        def get(u):calls.append(u);return dict(data=[self.row(),self.row()])
        self.assertEqual(len(st.discover(get,clock=lambda:1000)),1)
        self.assertEqual(st.discover(get,clock=lambda:1010),[]);self.assertEqual(len(calls),1)
    def test_schema_failure_is_not_a_live_feed(self):
        self.assertEqual(st.discover(lambda u:dict(unexpected=[]),clock=lambda:1000),[])
        self.assertFalse(st.status(clock=lambda:1001)['ok'])
        self.assertGreater(st._NEXT,1000)
    def test_stale_status_is_visible(self):
        st.discover(lambda u:dict(tokens=[]),clock=lambda:1000)
        self.assertEqual(st.status(clock=lambda:1400)['status'],'delayed')
    def test_bad_mints_and_invalid_numbers(self):
        self.assertIsNone(st.normalize(dict(mint='bad'),1000))
        self.assertIsNone(st.number(float('nan')));self.assertIsNone(st.number(-1));self.assertIsNone(st.number(True))

class ExportTests(unittest.TestCase):
    def test_recap_filters_books_and_partial_fills_labelled(self):
        c=sqlite3.connect(':memory:');c.row_factory=sqlite3.Row
        c.executescript('''CREATE TABLE positions(mint TEXT,symbol TEXT,version TEXT,status TEXT,cost REAL,qty REAL,entry REAL,pnl REAL,opened REAL,closed REAL,reason TEXT);
        CREATE TABLE events(mint TEXT,kind TEXT,ts REAL,data TEXT);
        INSERT INTO positions VALUES('A','A','v3','closed',30,1,30,2.4,99000,99900,'trailing_stop');
        INSERT INTO positions VALUES('B','B','vC','open',10,1,10,NULL,99900,NULL,NULL);
        INSERT INTO positions VALUES('C','C','v3x','closed',30,1,30,900,99000,99900,'stop');''')
        d=dict(equity=302.4,start=300,seen=100,passed=4)
        out=app_upgrades.build(c,d,('v3','vC'),clock=lambda:100000)
        self.assertEqual(out['recap']['realized'],2.4);self.assertEqual(out['exposure']['cost_usd'],10)
        self.assertEqual(out['signal_quality']['pass_rate_pct'],4)
        self.assertIsNone(out['journal'][0]['entry_reason']);c.close()

if __name__=='__main__':unittest.main()
