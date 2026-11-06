# Intelligence 1

This release adds an advisory learning layer. Existing entries, stops, partial exits, emergency exits, agent voting, and position sizing are unchanged. No wallet or live execution integration.

## Delivered capabilities
1. Similar-setup memory: retain completed main/shared opening cases with liquidity, momentum, pool age and transaction counts. Nearest cases exclude the same mint, future outcomes and incomplete feature vectors. Default minimum ten comparable cases before displaying an average.
2. Mistake review: evidence tags for incomplete entry inputs, entry costs above 3%, peak giveback and net outcome. Tags are observations, not proven causes or claims of unavoidable loss.
3. Calibration: compare explicitly recorded win probabilities with completed outcomes, with Brier error. A ranking score is not silently treated as a probability.
4. Condition-aware strategy review: compare momentum/standard/pullback results by the entry's quiet/uptrend/downtrend/choppy condition. Small samples remain insufficient; no strategy switches automatically.
5. Buyer evidence: transaction buy share plus explicit unknown independent-buyer quality. Wallet-level identity is unavailable in these inputs; transaction counts cannot prove organic participation.
6. Liquidity resilience: surface the existing recorded normal/half-depth exit proceeds model in Research / Exit replay.
7. Freshness: stale, future, missing prices or missing liquidity/counts withhold advisory confidence. Candidate age grows with elapsed time after its recorded snapshot.
8. Disagreement: tally objections against completed opening outcomes. Does not alter agent weights or require unanimous exits.
9. Missed opportunities: expose existing same-pool, after-cost skipped-token replay under Missed opportunities. This is simulated evidence, not executable profit.
10. Training/evaluation separation: reuse purged walk-forward evaluation, excluding overlapping outcomes and repeated test mints; reject future-closed rows in the intelligence report.
11. Challenger: earlier data selects the score threshold; later trades compare challenger with baseline. Different selection counts shown; replay only covers executed trades, not every market opportunity.
12. Version/rollback: content-addressed research configuration with activation journal. Research settings only; trading parameters cannot be supplied. No automatic promotion.

## Existing UI locations
Research / Strategies: memory, condition review, challenger evaluation.
Research / Decision checks: mistake review, calibration, freshness/buyer evidence, disagreement.
Research / Exit replay: resilience. Missed opportunities: net replay. Strategy race: held-out challenger results.
More / Agents: combined expandable intelligence detail. Overview is unchanged.

Both publisher and runner report `intelligence-1` independently. Missing features from historical trades are not invented. New entry features begin accumulating after the Mac updater installs this release. Evidence uses up to 500 completed openings in the last seven days; retained memory holds up to 2,000 loaded cases from 180 days. Current watchlist maximum ten.

## Research version commands
Run from bot directory using its virtualenv Python. No changes to execution settings:

    .venv/bin/python intelligence.py
    .venv/bin/python intelligence.py --save '{"min_neighbors":10,"min_train":50,"test_size":10}'
    .venv/bin/python intelligence.py --activate RETURNED_VERSION_ID --reason 'Evaluate a larger training sample'

To roll back, activate the prior version ID shown in the history. This changes only advisory research sampling. None of these commands enables trading, updates risk limits, or deploys a learned trading policy.
