import json
import sqlite3
import unittest
from source_performance import build

class PerformanceTests(unittest.TestCase):
    def setUp(self):
        self.c=sqlite3.connect(':memory:');self.c.row_factory=sqlite3.Row
        self.c.executescript('''CREATE TABLE positions(mint TEXT,version TEXT,status TEXT,opened REAL,closed REAL,pnl REAL,reason TEXT);
        CREATE TABLE events(mint TEXT,kind TEXT,ts REAL,data TEXT);
        CREATE TABLE audit(mint TEXT,reason TEXT,kill_px REAL,later_px REAL,ts REAL);
        CREATE TABLE counterfactual(mint TEXT,rule TEXT,px0 REAL,px1 REAL,ts REAL);''')
    def tearDown(self): self.c.close()
    def test_book_entry_attribution_and_partial_fills(self):
        self.c.executemany('INSERT INTO positions VALUES(?,?,?,?,?,?,?)',[
            ('A','v3','closed',99900,99950,2,'partial_tp'),
            ('A','v3','closed',99900,99970,-1,'stop'),
            ('A','v3x','closed',99900,99970,900,'stop'),
            ('B','vC','closed',99900,99970,3,'stop')])
        self.c.executemany('INSERT INTO events VALUES(?,?,?,?)',[
            ('A','paper_buy',99901,json.dumps(dict(book='vC',source='wrong'))),
            ('A','paper_buy',99900,json.dumps(dict(book='v3',source='stonkfun',dex='meteora'))),
            ('B','paper_buy',90000,json.dumps(dict(book='vC',source='old')))])
        out=build(self.c,clock=lambda:100000)
        self.assertEqual(sum(x['realized'] for x in out['sources']),4)
        st=next(x for x in out['sources'] if x['source']=='stonkfun')
        self.assertEqual((st['closed_fills'],st['partial_fills'],st['win_rate_pct']),(2,1,50))
        self.assertTrue(any(x['source']=='Unknown' for x in out['sources']))
    def test_missing_quote_unknown_and_duplicate_jobs(self):
        self.c.executemany('INSERT INTO audit VALUES(?,?,?,?,?)',[
            ('A','volume',1,0,99900),('B','safety',1,2,99900)])
        self.c.execute("INSERT INTO counterfactual VALUES('B','safety',1,1.5,99910)")
        out=build(self.c,clock=lambda:100000)['missed']
        self.assertEqual((out['measured'],out['unknown'],out['rose_20'],out['fell_20']),(1,1,1,0))
        self.assertEqual(next(x for x in out['samples'] if x['mint']=='B')['change_pct'],50)
    def test_optional_tables_absent_and_read_only(self):
        self.c.executescript('DROP TABLE audit; DROP TABLE counterfactual;')
        self.c.execute('PRAGMA query_only=ON')
        out=build(self.c,clock=lambda:100000)
        self.assertEqual(out['missed']['measured'],0)
        self.assertEqual(out['sources'],[])

if __name__=='__main__': unittest.main()
