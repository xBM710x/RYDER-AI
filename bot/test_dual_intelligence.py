import unittest
from dual_intelligence import Signal, decide


class DualIntelligenceTests(unittest.TestCase):
    def signal(self, source="copy", action="BUY", liquidity=50000, time=100):
        return Signal(source, "TOKEN", action, 0.9, liquidity, time)

    def test_copy_buy_paper_only(self):
        result = decide([self.signal()], 110)
        self.assertEqual(result.action, "BUY")
        self.assertTrue(result.paper_only)

    def test_independent_buy(self):
        self.assertEqual(decide([self.signal(source="independent")], 110).action, "BUY")

    def test_conflict_skips(self):
        result = decide([self.signal(), self.signal("independent", "SELL")], 110)
        self.assertEqual(result.action, "SKIP")
        self.assertEqual(result.reason, "copy_independent_conflict")

    def test_stale_skips(self):
        self.assertEqual(decide([self.signal()], 300).action, "SKIP")

    def test_unknown_liquidity_skips(self):
        self.assertEqual(decide([self.signal(liquidity=None)], 110).action, "SKIP")

    def test_mixed_tokens_skips(self):
        other = Signal("independent", "OTHER", "BUY", 0.9, 50000, 100)
        self.assertEqual(decide([self.signal(), other], 110).action, "SKIP")

    def test_empty_skips(self):
        self.assertEqual(decide([], 110).action, "SKIP")


if __name__ == "__main__":
    unittest.main()
