import threading
import unittest
from discovery_worker import DiscoveryWorker
from scan_scheduler import Scheduler


class WorkerTests(unittest.TestCase):
    def test_blocked_poll_does_not_block_live_scan_or_duplicate_results(self):
        worker=DiscoveryWorker()
        entered,release=threading.Event(),threading.Event()
        calls=[]
        def poll():
            calls.append(1)
            entered.set()
            release.wait(2)
            return [{'mint':'one'}]
        try:
            self.assertEqual(worker.collect(poll,60),[])
            self.assertTrue(entered.wait(1))
            self.assertEqual(worker.collect(poll,60),[])
            self.assertTrue(worker.status()['polling'])
        finally:
            release.set()
        self.assertTrue(worker.ready.wait(1))
        self.assertEqual(worker.collect(poll,60),[{'mint':'one'}])
        self.assertEqual(worker.collect(poll,60),[])
        self.assertEqual(calls,[1])

    def test_backlog_wakes_only_when_dispatch_possible(self):
        scheduler=Scheduler(max_inflight=1)
        scheduler.offer([{'mint':'a'}],clock=lambda:5)
        self.assertFalse(scheduler.has_room_for_pending({'b'}))
        self.assertTrue(scheduler.has_room_for_pending(set()))
        scheduler.take(set(),clock=lambda:8)
        self.assertEqual(scheduler.status()['wait_p90_s'],3)
        self.assertFalse(scheduler.has_room_for_pending(set()))
