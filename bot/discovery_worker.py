"""One background REST poll. The scanner never waits for the network worker."""
import threading
import time


class DiscoveryWorker:
    def __init__(self):
        self.lock = threading.Lock()
        self.running = False
        self.ready = threading.Event()
        self.result = []
        self.next_start = 0
        self.cycles = self.errors = 0
        self.last_duration = None

    def _run(self, poll):
        start = time.monotonic()
        try:
            result = list(poll())
        except Exception as err:
            result = []
            with self.lock:
                self.errors += 1
            print("Discovery poll failed:", type(err).__name__, flush=True)
        with self.lock:
            self.result = result
            self.running = False
            self.cycles += 1
            self.last_duration = round(time.monotonic() - start, 3)
            if result:
                self.ready.set()

    def collect(self, poll, interval=5):
        with self.lock:
            result, self.result = self.result, []
            self.ready.clear()
            now = time.monotonic()
            if not self.running and now >= self.next_start:
                self.running = True
                self.next_start = now + interval
                threading.Thread(target=self._run, args=(poll,), daemon=True,
                                 name="rest-discovery").start()
            return result

    def status(self):
        with self.lock:
            return dict(polls=self.cycles, errors=self.errors, polling=self.running,
                        last_poll_s=self.last_duration)


WORKER = DiscoveryWorker()
