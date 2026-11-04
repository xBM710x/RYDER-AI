import sqlite3
import unittest

from desk_five import build, equity_ranges


class DeskFiveTests(unittest.TestCase):
    def test_funnel_counts_mints_and_excludes_other_books(self):
        db = sqlite3.connect(':memory:')
        db.executescript("""
        CREATE TABLE seen(mint,first_ts);
        CREATE TABLE events(id INTEGER PRIMARY KEY,ts,kind,mint,symbol,data,version);
        INSERT INTO seen VALUES ('a',90000),('b',90000),('old',1);
        """)
        for mint,kind,detail in [('a','paper_buy','{}'),('a','paper_buy','{}'),
                                 ('b','paper_buy','{"book":"v3b"}'),('old','entry_wait','{}')]:
            db.execute('INSERT INTO events VALUES(NULL,95000,?,?,?,?,?)',(kind,mint,mint,detail,'v3'))
        self.assertEqual([r['count'] for r in build(db,100000)['stages']],[2,1,1,1])

    def test_ranges_preserve_scope_endpoints_and_extrema(self):
        db = sqlite3.connect(':memory:')
        db.execute('CREATE TABLE equity(ts,value,scope)')
        db.executemany('INSERT INTO equity VALUES(?,?,?)',[(i*3600,500 if i==5 else 300,'shared') for i in range(401)])
        db.execute("INSERT INTO equity VALUES(1,900,'main')")
        result = equity_ranges(db,'shared',400*3600)
        self.assertEqual(result['24H'][0][0],376*3600)
        self.assertEqual(result['7D'][0][0],232*3600)
        self.assertIn((5*3600,500),result['All'])
        self.assertEqual(result['All'][0],(0,300))
