# Decision operations

Release `decision-ops-1` adds evidence inside Research and More; Overview remains unchanged. No live execution or automatic strategy promotion is enabled.

- Diagnostics: most recent decision per token in a bounded 24-hour sample, with missing inputs separated from failed rules.
- Strategies: fresh market-input ranking controls evaluation order within source-fair batches. Existing entry and exit gates still apply.
- Missed: bounded scheduled retries now include unavailable liquidity as well as unavailable volume. Hard safety rejections do not use this retry path.
- Timing: breakout, pullback and continuation research use a separate `bot/decision-timing.db`, never the shared paper balance. At most 24 tokens are active. Trials start from filter-passed candidates, which are not necessarily execution-approved.
- Fills: $25 trials require fresh, increasing-timestamp quotes from the original pool, a later quote after at least five seconds, 0.3% fees and 1% slippage allowance each side plus modeled pool impact, and size at most 1% of liquidity. Exits are modeled after five minutes. No valid outcome within 30 minutes is unresolved, never assumed profitable. This is not an executable route quote.
- Replay and accountability: recorded events and agent votes are associated with completed main/shared openings; absent evidence stays absent. Association is not causal credit.
- Recovery monitoring: heartbeat, scan freshness, errors and worker state. Existing recovery mechanisms are retained; this release does not claim fault-injection certification.
- Readiness: evidence checklist explicitly stays NOT READY until execution, reconciliation and recovery are independently verified.

The UI displays an awaiting-report state until the Mac updater installs this release and a successful publisher run includes `decision_ops`. Runner release confirmation requires the matching heartbeat marker. Never commit runtime databases or token files.

Validation: `python -m unittest test_decision_ops` plus the updater TESTS suite.
