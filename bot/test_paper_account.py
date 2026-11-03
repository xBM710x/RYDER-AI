"""Offline accounting tests. python -m unittest discover -s bot -p test_paper_account.py"""
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch
import paper_account as pa

class PaperAccountTests(unittest.TestCase):
    def setUp(self):
        self.flag = patch.object(pa, 'MODE', True); self.flag.start()
        self.c = sqlite3.connect(':memory:'); self.c.row_factory = sqlite3.Row
        self.c.executescript('''CREATE TABLE account(k TEXT PRIMARY KEY,v REAL);
        CREATE TABLE positions(id INTEGER PRIMARY KEY,version TEXT,mint TEXT,status TEXT,cost REAL,qty REAL,entry REAL,pnl REAL,closed REAL);
        INSERT INTO account VALUES('cash_v3',302.4),('cash_vC',300);''')
    def tearDown(self):
        self.c.close(); self.flag.stop()
    def test_seed_once_and_preserve_legacy(self):
        pa.ensure(self.c); pa.ensure(self.c)
        self.assertAlmostEqual(pa.cash(self.c,'v3'),302.4)
        self.assertEqual(pa.key_for('v3'),pa.key_for('vC'))
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM paper_account_migration').fetchone()[0],2)
        self.assertEqual(self.c.execute("SELECT v FROM account WHERE k='cash_vC'").fetchone()[0],300)
        self.assertEqual(pa.key_for('v3x'),'cash_v3x')
    def test_profit_loss_both_in_one_balance(self):
        pa.ensure(self.c)
        self.c.execute('UPDATE account SET v=v-5 WHERE k=?',(pa.KEY,));self.c.commit()
        self.assertAlmostEqual(pa.cash(self.c,'v3'),297.4)
        self.assertAlmostEqual(pa.cash(self.c,'vC'),297.4)
    def test_open_mark_and_strategy_attribution(self):
        self.c.execute("UPDATE account SET v=272.4 WHERE k='cash_v3'")
        self.c.execute("INSERT INTO positions VALUES(1,'v3','A','open',30,10,3,NULL,NULL)")
        self.c.execute("INSERT INTO positions VALUES(2,'vC','B','closed',10,1,10,-2,1)")
        self.c.execute("UPDATE account SET v=298 WHERE k='cash_vC'");self.c.commit()
        pa.ensure(self.c); s=pa.summary(self.c,{'A':4})
        self.assertAlmostEqual(s['cash'],270.4)
        self.assertAlmostEqual(s['equity'],310.4)
        self.assertEqual(s['strategies']['vC'],-2)
        self.assertEqual(s['fallback_marks'],0)
    def test_oversubscribed_migration_refuses_without_changes(self):
        self.c.execute('UPDATE account SET v=100');self.c.commit()
        with self.assertRaises(RuntimeError): pa.ensure(self.c)
        self.assertIsNone(self.c.execute('SELECT v FROM account WHERE k=?',(pa.KEY,)).fetchone())
    def test_missing_book_cash_refuses_existing_positions(self):
        self.c.execute("DELETE FROM account WHERE k='cash_vC'")
        self.c.execute("INSERT INTO positions VALUES(1,'vC','X','open',10,1,10,NULL,NULL)");self.c.commit()
        with self.assertRaises(RuntimeError): pa.ensure(self.c)
    def test_shared_per_coin_cap(self):
        pa.ensure(self.c)
        self.c.execute("INSERT INTO positions VALUES(1,'vC','X','open',30,1,30,NULL,NULL)")
        self.c.execute('UPDATE account SET v=v-30 WHERE k=?',(pa.KEY,));self.c.commit()
        self.c.execute('BEGIN IMMEDIATE')
        self.assertAlmostEqual(pa.cap_order(self.c,'v3',30,'X',.1,.12),6.288)
        self.c.rollback()
    def test_daily_loss_checks_both_books(self):
        import time
        pa.ensure(self.c)
        self.c.execute("INSERT INTO positions VALUES(1,'v3','X','closed',30,1,30,-25,?)",(time.time(),))
        self.c.execute("INSERT INTO positions VALUES(2,'vC','Y','closed',30,1,30,-20,?)",(time.time(),));self.c.commit()
        self.c.execute('BEGIN IMMEDIATE')
        self.assertEqual(pa.cap_order(self.c,'v3',30,'Z',.1,.12),0)
        self.c.rollback()
    def test_disabling_after_migration_refuses_split_accounts(self):
        pa.ensure(self.c)
        with patch.object(pa,'MODE',False):
            with self.assertRaises(RuntimeError): pa.ensure(self.c)
    def test_concurrent_last_cash_cannot_be_spent_twice(self):
        pa.ensure(self.c)
        with tempfile.TemporaryDirectory() as d:
            path=d+'/test.db'; dest=sqlite3.connect(path); self.c.backup(dest);dest.close()
            out=[]
            def spend(book):
                c=sqlite3.connect(path,timeout=5); c.row_factory=sqlite3.Row
                c.execute('BEGIN IMMEDIATE')
                value=pa.cap_order(c,book,300,book,1,1)
                c.execute('UPDATE account SET v=v-? WHERE k=?',(value,pa.KEY));c.commit();c.close();out.append(value)
            ts=[threading.Thread(target=spend,args=(v,)) for v in pa.BOOKS]
            for t in ts:t.start()
            for t in ts:t.join()
            self.assertEqual(len(out),2)
            self.assertAlmostEqual(sum(out),302.4)

if __name__=='__main__': unittest.main()
