# RYDER specialist agents — implementation status

The new `bot/agent_suite.py` contains **paper-only**, provider-neutral building blocks:

- **X Scout:** accepts only timestamped, verified-source social mentions from a future read-only provider; distinct-author thresholds prevent a single author from masquerading as a trend. It does **not** connect to X.
- **Compounding:** allocates a configurable fraction of **realized net paper profits** to a simulated budget. Defaults to 40% reinvested, 60% retained; losses reduce the paper budget.
- **Risk:** deterministic trailing stop, partial exit, exposure caps and fail-closed validation. Outputs advisory paper events, not orders.
- **Notifications:** structured payloads for an optional future email/push delivery adapter. No messages are sent yet.

Run tests from repository root:

```sh
cd bot
python3 -m unittest -v test_agent_suite test_dual_intelligence test_copy_intelligence test_dual_telemetry
```

**Not yet connected:** live X or FOMO feeds, real agent scheduling, paper execution runtime, persistent position peaks/partial-exit state, notifications transport, Night Desk agent feed, or historical performance verification. These must be wired and tested in follow-up PRs; do not label any of them as live. No real trading.
