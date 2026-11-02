# RYDER app upgrades

Prepared: StonkFun read-only discovery, source freshness/status, last-24-hour realized recap, cost exposure, trade journal and pass-rate exports. Existing mascot, copy gates and paper-only mode stay intact. Main+Copy shared capital remains opt-in; follow SHARED_PAPER_ACCOUNT.md.

StonkFun discovery polls at most once per minute with a bounded two-page newest sweep. Candidates enter the existing Scout/DexScreener/filters pipeline. It does not trust source USD price as a fill, assume a non-SOL quote equals USD, call any transaction endpoint, or treat absent liquidity as safe. Failures back off; the status export marks old data delayed. Live API response access was unavailable in the preparation environment, so the parser has fixture tests but needs a read-only live smoke test before enabling the source. Set RYDER_STONKFUN_ENABLED=0 to disable it while validating.

The app cards only display app_upgrades published by the new publisher; otherwise they show awaiting update. No fabricated trades or returns. Journal entry reasons absent in historical events remain 'Not recorded'. Recap counts closed fills including partials rather than claiming those are distinct trades. Source docs: https://www.stonkfunxyz.com/developers

Run: python -m unittest discover -s bot -p test_paper_account.py
Run: python -m unittest discover -s bot -p test_app_upgrades.py

The running bot is outside ChatGPT's filesystem. Pull this change into that runtime, back up the database, stop duplicate processes, verify environment and run the publisher before restarting. Do not claim activation based only on GitHub commits. Check new data.json for shared_account, app_upgrades and stonkfun, and check timestamps keep advancing.
