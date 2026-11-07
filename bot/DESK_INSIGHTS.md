# Desk insights · desk-insights-1

Eight read-only extensions use recorded events and completed paper openings:

1. Overview agent rows expand to the latest relevant recorded token/event and a suggested next review. This is not a claim that an independent agent is currently executing.
2. Open Positions and Markets expand to pending-entry recheck countdowns. New heartbeat quote timestamps support freshness checks. Stale heartbeats pause countdowns; elapsed time never authorizes entry.
3. Research / Missed opportunities associates existing same-pool after-cost followups with the preceding skip rule. Selected followups cannot establish that an excluded token was safe or executable.
4. Research / Exit replay reports cost-weighted exit capture and giveback against recorded peaks. Missing peaks stay unknown and peak liquidity/timing are not inferred.
5. Research / Strategies groups completed results by entry strategy and token tape regime. This is not a market-wide regime estimate or automatic strategy switch.
6. Research / Decision checks compares agent score bands with completed outcomes. Scores are not calibrated probabilities; small samples are labeled insufficient.
7. Existing feed card and More / System distinguish stale heartbeat, missing scans, pending entries, pauses, recent worker errors and per-host last-success evidence. Recovery actions remain the existing runner's responsibility.
8. Morning recap, expandable in the existing Overview feed card and Research / Session review, states session wins/losses/net and proposes a review-only paper experiment from observed blockers. Session starts at 6 PM Pacific; blocker sample covers 24h.

No new Overview cards, wallet integration, live orders, altered entry/exit gates or automatic parameter promotion. Snapshot scope: up to 4000 events/24h and 500 completed main/shared openings/7d. Mac installation must be confirmed by a published desk_insights report; upload alone does not prove installation.

Validation: test_desk_insights plus the updater test suite; JavaScript syntax and full-app DOM navigation/countdown/escaping checks. Device screenshot appearance is not verified by DOM tests.
