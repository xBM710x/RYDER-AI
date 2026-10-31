"""Breaker self-tests (paper only, no network writes). Usage: python3 test_breakers.py  -> exit 1 if any brake fails to fire."""
import sys, logger
logger.log = lambda *a, **k: None  # don't write test rows to the live event log
import brain17; brain17.log = logger.log
r = brain17.selftest(alert=False)
for k, v in r.items(): print(f"{'PASS' if v else 'FAIL'}  {k}")
sys.exit(0 if all(r.values()) else 1)
