import unittest
from coordination_runtime import coordination_from_runtime


class CoordinationRuntimeTests(unittest.TestCase):
    def test_observed_skip_only(self):
        result = coordination_from_runtime({"kills_live": [
            {"mint": "TOKEN", "reason": "liquidity"}]}, 100)
        self.assertEqual(result["decisions"][0]["action"], "SKIP")
        self.assertEqual(result["decisions"][0]["reason"], "liquidity")
        self.assertTrue(result["decisions"][0]["paper_only"])

    def test_missing_source_never_approves(self):
        result = coordination_from_runtime({}, 100)
        self.assertEqual(result["decisions"], [])

    def test_deduplicates(self):
        result = coordination_from_runtime({"kills_live": [
            {"mint": "TOKEN", "reason": "old"},
            {"mint": "TOKEN", "reason": "new"}]}, 100)
        self.assertEqual(len(result["decisions"]), 1)
        self.assertEqual(result["decisions"][0]["reason"], "new")

    def test_invalid_rows_ignored(self):
        self.assertEqual(coordination_from_runtime({"kills_live": [None, {}, 42]}, 100)["decisions"], [])


if __name__ == "__main__":
    unittest.main()
