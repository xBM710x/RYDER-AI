import unittest
from copy_intelligence import WalletEvent, PaperSignalDesk, normalize_copy_event
from dual_intelligence import Signal


class CopyIntelligenceTests(unittest.TestCase):
    def event(self, **kw):
        fields = dict(wallet="tracked", mint="MINT", side="BUY",
                      observed_at=100.0, liquidity_usd=50000.0,
                      confidence=0.85, signature="tx1")
        fields.update(kw)
        return WalletEvent(**fields)

    def test_unapproved_wallet_is_rejected(self):
        self.assertIsNone(normalize_copy_event(self.event(), approved_wallets=set()))

    def test_missing_signature_is_rejected(self):
        self.assertIsNone(normalize_copy_event(self.event(signature=""), approved_wallets={"tracked"}))

    def test_nonfinite_confidence_is_rejected(self):
        self.assertIsNone(normalize_copy_event(self.event(confidence=float("nan")), approved_wallets={"tracked"}))

    def test_copy_signal_and_duplicate(self):
        desk = PaperSignalDesk(["tracked"])
        first = desk.evaluate(self.event(), [], 105)
        self.assertEqual(first.action, "BUY")
        self.assertTrue(first.paper_only)
        self.assertIsNone(desk.evaluate(self.event(), [], 105))
        self.assertEqual(len(desk.history), 1)

    def test_disagreeing_independent_signal_blocks(self):
        desk = PaperSignalDesk(["tracked"])
        independent = Signal("independent", "MINT", "SELL", 0.9, 50000, 100)
        result = desk.evaluate(self.event(), [independent], 105)
        self.assertEqual(result.action, "SKIP")


if __name__ == "__main__":
    unittest.main()
