import unittest
from agent_suite import AgentEvent
from agent_coordination import coordinate


def event(agent, action, token="ABC"):
    return AgentEvent(agent, token, action, "verified input", 100)


class CoordinationTests(unittest.TestCase):
    def test_two_confirmations_eligible_only(self):
        result = coordinate("ABC", [event("Scout", "WATCH"),
                                    event("Analyst", "APPROVE")], equity=100)
        self.assertEqual(result.action, "PAPER_ENTRY_ELIGIBLE")
        self.assertTrue(result.paper_only)

    def test_no_analyst_stays_watch(self):
        self.assertEqual(coordinate("ABC", [event("Scout", "WATCH")], equity=100).action, "WATCH")

    def test_risk_veto_overrides_agreement(self):
        events = [event("Scout", "WATCH"), event("Analyst", "APPROVE"), event("Risk", "SKIP")]
        self.assertEqual(coordinate("ABC", events, equity=100).action, "SKIP")

    def test_wrong_token_cannot_approve(self):
        events = [event("Scout", "WATCH"), event("Analyst", "APPROVE", "OTHER")]
        self.assertEqual(coordinate("ABC", events, equity=100).action, "WATCH")

    def test_exposure_cap(self):
        events = [event("Scout", "WATCH"), event("Analyst", "APPROVE")]
        self.assertEqual(coordinate("ABC", events, equity=100, total_exposure=40).action, "SKIP")

    def test_nonpaper_event_ignored(self):
        bad = AgentEvent("Analyst", "ABC", "APPROVE", "bad", 100, False)
        self.assertEqual(coordinate("ABC", [event("Scout", "WATCH"), bad], equity=100).action, "WATCH")

    def test_missing_account_fails_closed(self):
        self.assertEqual(coordinate("ABC", [], equity=float("nan")).action, "SKIP")


if __name__ == "__main__":
    unittest.main()
