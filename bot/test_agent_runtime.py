import unittest
from agent_runtime import runtime_agents, policy_status


class AgentRuntimeTests(unittest.TestCase):
    def test_no_fake_connected_sources(self):
        result = runtime_agents({"risk": {}, "council": {}, "b16": {}}, now=100)
        by_name = {x["name"]: x for x in result["agents"]}
        self.assertFalse(by_name["X Scout"]["evidence"])
        self.assertEqual(by_name["X Scout"]["status"], "not_connected")
        self.assertTrue(by_name["Risk"]["evidence"])
        self.assertTrue(result["paper_only"])

    def test_missing_state_fails_closed(self):
        self.assertEqual(runtime_agents(None)["status"], "unavailable")

    def test_real_skip_events_only(self):
        result = runtime_agents({"kills_live": [{"sym": "ABC", "reason": "low liquidity"}]}, now=100)
        self.assertEqual(result["activity"][0]["reason"], "low liquidity")
        self.assertEqual(result["activity"][0]["decision"], "SKIP")

    def test_policy_is_advisory_only(self):
        self.assertFalse(policy_status()["active_order_routing"])


if __name__ == "__main__":
    unittest.main()
