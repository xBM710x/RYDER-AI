import unittest
from paper_entry_window import threshold

class EntryTests(unittest.TestCase):
    def setUp(self):
        self.p=dict(volume=dict(h1=30000),liquidity=dict(usd=50000),txns=dict(m5=dict(buys=14,sells=8)),_ts=100)
    def test_active(self):
        self.assertEqual(threshold(self.p,40000,110),30000)
    def test_missing_stale_and_quiet(self):
        for patch in [dict(volume={}),dict(_ts=1),dict(liquidity=dict(usd=49999)),dict(txns=dict(m5=dict(buys=9,sells=8))),dict(volume=dict(h1=29999))]:
            self.assertEqual(threshold(dict(self.p,**patch),40000,110),40000)
    def test_floor(self):
        self.assertEqual(threshold(self.p,22000,110),20000)
