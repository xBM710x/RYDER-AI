import unittest
from agent_publish import sanitize_heartbeat_agents as export


class PublishTests(unittest.TestCase):
    def test_fresh_verified_paper_telemetry(self):
        hb = {"ts": 100, "specialist_agents": {"paper_only": True,
              "agents": [{"name": "Risk", "status": "observed", "evidence": True}],
              "activity": [{"agent": "Risk", "token": "ABC", "decision": "SKIP",
                            "reason": "liquidity", "paper_only": True}]}}
        result = export(hb, now=105)
        self.assertEqual(result["agents"][0]["name"], "Risk")
        self.assertEqual(result["activity"][0]["reason"], "liquidity")

    def test_stale_fails_closed(self):
        self.assertEqual(export({"ts": 1}, now=1000)["status"], "heartbeat_stale")

    def test_future_fails_closed(self):
        self.assertEqual(export({"ts": 200}, now=100)["status"], "heartbeat_stale")

    def test_missing_source_fails_closed(self):
        self.assertEqual(export({"ts": 100}, now=101)["status"], "agent_data_missing")

    def test_nonpaper_events_filtered(self):
        hb = {"ts": 100, "specialist_agents": {"paper_only": True,
              "agents": [], "activity": [{"agent": "Executor", "paper_only": False}]}}
        self.assertEqual(export(hb, now=101)["activity"], [])


if __name__ == "__main__":
    unittest.main()
