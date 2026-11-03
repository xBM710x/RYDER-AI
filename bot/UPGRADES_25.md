# Research desk: 25 production views

The existing overview, star, paper account, copy desk, logger and bottom navigation stay in place. Four tabs below source badges expose the new views. `mission.js` renders only `data.json.mission_control`; no demonstration fixtures are loaded in production.

| # | View | Evidence and limits |
|---|---|---|
|1|Searchable radar|Latest 120 evaluated candidates; source, liquidity, score, age and recent-observation filters. Not all Solana tokens.|
|2|Token detail|Observed fields and last 20 matching decision events per radar token.|
|3|Source comparison|Last 24h realized fill attribution and cumulative curves; unknown entry source remains unknown.|
|4|Discovery speed|Reported pool creation to first local observation; missing or implausible launch times excluded.|
|5|Source warnings|Runner HTTP last-success ages and StonkFun status; in-app only. Quiet feeds are not declared outages.|
|6|Freshness|Local observation ages; no claim of exchange timestamp freshness.|
|7|Watchlist pins|Browser-local quick-access pins. No forced monitoring, orders or approvals. Tokens outside the bounded snapshot stay labeled.|
|8|Near-entry|Actual pending entries from heartbeat; reaching zero wait does not approve a trade.|
|9|Decision timeline|Searchable existing event records, bounded recent window.|
|10|Disagreement|Recorded council votes, explanations and decisions.|
|11|Calibration|Recorded win_prob versus completed-opening outcomes; partials aggregated, residual open positions excluded. Descriptive, not held-out evaluation.|
|12|Learning progress|Recorded model training events and heartbeat model counts. No invented intelligence score.|
|13|Regime results|Regime recorded at entry for new fills. Historical unknowns stay unknown.|
|14|Age results|Pool age at entry for new fills, grouped into explicit bands.|
|15|Liquidity results|Entry liquidity groups with closed-fill counts.|
|16|Costs|Exact additive decomposition of existing paper-fill prices into modeled fees, slippage and MEV. Collection begins with new fills.|
|17|Exit review|Existing exit-manager shadow comparisons and curves, not hindsight execution promises.|
|18|Coverage|Unique skipped tokens in bounded logger sample plus recent follow-ups; missing later prices are unknown, not losses.|
|19|Filter review|Deduplicated audit/counterfactual outcomes by reason. No safety filter is changed.|
|20|Experiments|Last-24h realized fills by paper book. Shared totals are not double counted.|
|21|Rules|Actual rule-change/revert/threshold/self-review events and coach suggestion status.|
|22|Drawdown|Persistent observed equity curve by scope, up to seven days; starts on installation.|
|23|Daily recap|Pacific calendar-day realized fills and sampled skip reasons. No email action.|
|24|Service health|Runner heartbeat, previous successful publisher push, updater status and installed commit.|
|25|Backups|Retained DB inventory, recorded integrity at creation, and read-only recovery guide. No automatic restore/delete.|

`desk_observations.py` writes display-only data to `bot/desk-observations.db`, separate from trading memory. Collection failures are isolated from evaluation. The publisher adds equity observations and reads the ledger; it never uses these views to authorize buys. Tokens are observations, not endorsements.

Exports are bounded: up to 120 radar tokens, 4,000 recent events, 3,000 recent closed fills, 1,000 outcomes per follow-up table, 12 backup inventory entries, and seven days of equity observations. Views with no evidence say not recorded/collecting. The curves use actual timestamps; groups can have different samples and should not be treated as controlled experiments.

Automatic updates run the existing suites plus `test_mission_control`. The first installation of the new test manifest is also checked before release. No dependency changes are required.

## Validation

- 32 accounting, discovery, updater, source and research unit tests.
- Existing 17 safety breaker checks.
- Python compilation, JavaScript syntax and shell syntax.
- Read-only export against restored state: 25 views, no ledger mutation.
- Simulated-fixture browser check is isolated at `previews/live-ui-check.html`, explicitly labeled and disconnected. It is never loaded by the live app.

Browser checks passed for source/search/liquidity filtering, token timeline dialog, pinning, all four tab inventories (25 views), logger search and the recovery guide. No application JavaScript errors were observed in that fixture check.
