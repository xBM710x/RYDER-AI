import unittest
from agent_suite import (RiskPolicy, x_scout, paper_budget,
                         evaluate_position, notification_payload, AgentEvent)


class AgentSuiteTests(unittest.TestCase):
    def test_x_scout_requires_verified_distinct_authors(self):
        mentions = [dict(token="ABC", author=str(i), timestamp=100, verified_source=True) for i in range(3)]
        self.assertEqual(x_scout(mentions, now=110)[0].action, "WATCH")
        mentions[0]["verified_source"] = False
        self.assertEqual(x_scout(mentions, now=110), [])

    def test_x_scout_rejects_stale(self):
        mentions = [dict(token="ABC", author=str(i), timestamp=1, verified_source=True) for i in range(3)]
        self.assertFalse(x_scout(mentions, now=400))

    def test_compounding_only_realized_profit(self):
        x = paper_budget(100, 50)
        self.assertAlmostEqual(x["paper_budget"], 120)
        self.assertAlmostEqual(x["retained_paper_profit"], 30)
        self.assertTrue(x["paper_only"])

    def test_loss_does_not_compound(self):
        self.assertEqual(paper_budget(100, -20)["paper_budget"], 80)

    def test_trailing_stop(self):
        x = evaluate_position(token="A", entry=10, peak=20, current=18,
                              position_value=10, equity=100, total_exposure=10, now=10)
        self.assertEqual(x.action, "PAPER_EXIT")

    def test_partial_exit(self):
        x = evaluate_position(token="A", entry=10, peak=12, current=12,
                              position_value=10, equity=100, total_exposure=10, now=10)
        self.assertEqual(x.action, "PAPER_PARTIAL_EXIT")

    def test_partial_exit_once(self):
        x = evaluate_position(token="A", entry=10, peak=12, current=12,
                              position_value=10, equity=100, total_exposure=10,
                              now=10, partial_already_taken=True)
        self.assertEqual(x.action, "PAPER_HOLD")

    def test_bad_policy_rejected(self):
        with self.assertRaises(ValueError):
            paper_budget(100, 20, RiskPolicy(reinvest_profit_fraction=1.5))

    def test_notifications_are_paper_only(self):
        p = notification_payload(AgentEvent("Risk", "A", "PAPER_HOLD", "ok", 1))
        self.assertTrue(p["paper_only"])
        with self.assertRaises(ValueError):
            notification_payload(AgentEvent("Risk", "A", "BUY", "ok", 1, False))


if __name__ == "__main__":
    unittest.main()
