# Active paper entry window

This experimental main v3 paper admission rule allows a candidate below the usual
hourly volume threshold to proceed to the remaining filters. It does not place
an order directly and is not a validated profitable strategy.

Requirements for the new window:

- Observed hourly volume at least $10,000.
- Observed five-minute volume at least $2,000 and no greater than hourly volume.
- Liquidity at least $25,000.
- At least 20 buys in five minutes and buys at least 1.5 times sells.
- Five-minute price change greater than zero and at most 15%.
- Quote snapshot age from zero to 15 seconds.

Missing or invalid inputs do not qualify. Existing standard admission and the
previous liquid-token window remain available. Every remaining filter, scoring
gate, confirmation delay, position limit, loss limit and exit rule still applies.
The four-entry-per-hour limit is unchanged because the observed bottleneck is
filter admission, not that limit. Logs identify a lowered volume threshold as
`paper activity window` and record its required volume.

The installed auto-updater runs test_paper_entry_window before adopting this
change. Rollback consists of restoring paper_entry_window.py and filters.py from
the preceding release. A broader candidate pool may increase losses; measure
completed paper trades after modeled fees and slippage before judging results.
