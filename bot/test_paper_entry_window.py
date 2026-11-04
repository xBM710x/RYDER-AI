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

    def momentum(self):
        return dict(volume=dict(h1=12000,m5=2500),liquidity=dict(usd=30000),
                    txns=dict(m5=dict(buys=25,sells=12)),priceChange=dict(m5=4),_ts=100)

    def test_recent_momentum_admits_lower_hourly_volume(self):
        self.assertEqual(threshold(self.momentum(),40000,110),10000)
        self.assertEqual(threshold(self.momentum(),8000,110),8000)

    def test_momentum_requires_fresh_complete_supported_data(self):
        for patch in [dict(volume=dict(h1=9999,m5=2500)),
                      dict(volume=dict(h1=12000,m5=1999)),
                      dict(volume=dict(h1=12000,m5=13000)),
                      dict(volume=dict(h1=float('nan'),m5=2500)),
                      dict(liquidity=dict(usd=24999)),dict(_ts=94),dict(_ts=111),
                      dict(txns=dict(m5=dict(buys=19,sells=10))),
                      dict(txns=dict(m5=dict(buys=25,sells=20))),
                      dict(priceChange={}),dict(priceChange=dict(m5=-1)),
                      dict(priceChange=dict(m5=16))]:
            with self.subTest(patch=patch):
                self.assertEqual(threshold(dict(self.momentum(),**patch),40000,110),40000)
