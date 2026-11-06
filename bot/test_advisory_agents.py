"""Offline checks for read-only advisory agents. Run: python3 -m unittest bot/test_advisory_agents.py"""
import importlib.util
from pathlib import Path
import unittest

PATH = Path(__file__).resolve().parents[1] / "ryder_agents.py"
spec = importlib.util.spec_from_file_location("ryder_agents_test", PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class AdvisoryTests(unittest.TestCase):
    def test_no_evidence_is_not_invented(self):
        result = module.evaluate_agents({})
        self.assertEqual([a["name"] for a in result], ["Hunter", "Strategist", "Sentinel"])
        self.assertIn("Waiting", result[0]["text"])
        self.assertIn("Waiting", result[1]["text"])
    def test_safety_flags_and_closed_paper_outcomes(self):
        result = module.evaluate_agents({
            "candidates": [{"symbol": "TEST", "volume_24h": 100000,
                            "liquidity_usd": 15000, "price_change_1h": 5,
                            "mint_authority_enabled": True}],
            "closed": [{"pnl": 2.4}]})
        self.assertIn("TEST", result[0]["text"])
        self.assertIn("2 risk flag", result[2]["text"])
        self.assertIn("+2.40", result[1]["text"])
    def test_missing_values_never_rank(self):
        result = module.evaluate_agents({"candidates": [{"symbol": "UNKNOWN", "volume_24h": None,
                            "liquidity_usd": None, "price_change_1h": None}]})
        self.assertEqual(result[0]["stat"], "0 ranked")

if __name__ == "__main__":
    unittest.main()
