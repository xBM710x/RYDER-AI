import unittest
from reliability import assess


class ReliabilityTests(unittest.TestCase):
    def check(self,price=12,stamp=950,cash=90):
        return assess([dict(mint='a',qty=1,cost=10)], {'a':dict(priceUsd=price,_ts=stamp)},
                      dict(cash=cash,realized=0,equity=102,start=100),1000)
    def test_clean(self):
        self.assertEqual([r['stat'] for r in self.check()],['checked','balanced'])
    def test_missing_price(self):
        self.assertEqual([r['stat'] for r in self.check(None)],['warning','partial'])
    def test_cash_discrepancy_and_stale(self):
        self.assertEqual([r['stat'] for r in self.check(stamp=500,cash=91)],['warning','mismatch'])
    def test_unknown_age(self):
        self.assertEqual(self.check(stamp=None)[0]['stat'],'unknown')
