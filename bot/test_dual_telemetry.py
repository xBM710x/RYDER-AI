import json
import tempfile
import unittest
from pathlib import Path
from copy_intelligence import PaperSignalDesk, WalletEvent
from dual_telemetry import signal_from_scanner, summarize, write_snapshot


class TelemetryTests(unittest.TestCase):
    def test_scanner_normalization(self):
        s = signal_from_scanner("MINT", "BUY", 0.8, 50000, 100)
        self.assertEqual(s.source, "independent")

    def test_bad_scanner_input_rejected(self):
        self.assertIsNone(signal_from_scanner("MINT", "BUY", float("nan"), 50000, 100))

    def test_paper_snapshot_excludes_wallet(self):
        desk = PaperSignalDesk(["tracked"])
        event = WalletEvent("tracked", "MINT", "BUY", 100, 50000, 0.9, "sig1")
        desk.evaluate(event, [], 105)
        result = summarize(desk)
        self.assertEqual(result["mode"], "paper")
        self.assertEqual(result["decisions"][0]["decision"], "BUY")
        self.assertNotIn("tracked", json.dumps(result))
        self.assertNotIn("sig1", json.dumps(result))

    def test_atomic_export(self):
        desk = PaperSignalDesk()
        with tempfile.TemporaryDirectory() as folder:
            path = write_snapshot(desk, Path(folder) / "telemetry.json")
            self.assertEqual(json.loads(path.read_text())["count"], 0)


if __name__ == "__main__":
    unittest.main()
