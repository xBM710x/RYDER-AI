# Main + Copy shared PAPER account

This change is prepared for the local bot runtime. It does not change a running process by updating GitHub. No wallets, signing or real orders are added.

## What changes

Main (v3) and Copy (vC) draw from one cash ledger, `cash_main_copy`. Both dashboard cards show the same total. Strict/FOMO experiments and old versions remain separate.

Starting capital is counted ONCE: shared cash = old Main cash + old Copy cash − one starting balance. At the inspected snapshot: $302.40 + $300 − $300 = $302.40. Existing open positions remain invested; they are not deposited again. The migration rejects missing cash for existing positions, invalid cash, or a negative combined cash balance. Old cash rows are preserved as migration records, not active spending accounts.

Final shared order checks run under a SQLite write lock. Main and Copy both honor available cash, the existing 10% maximum order size, combined 12% per-coin exposure and combined 15% daily realized-loss limit. Existing safety gates and smaller Copy sizing remain in place. Adds also recheck funds. Shared exits refresh the position under the write lock to prevent two workers crediting the same full exit.

The publisher fetches marks for open Main/Copy positions and publishes `shared_account`. Missing marks are counted in `fallback_marks`; entry-price fallback is not a fresh market price. Per-strategy realized results are included separately. The previous Main-only equity curve is not relabeled as shared history; a single current shared-equity point is exported until joint history is collected. W/L, historical version summaries and calendar remain strategy/research views; they are not a second pool of spendable capital.

## Activation on the machine running RYDER

1. Stop ALL RYDER runner, supervisor and publisher processes, so none can write the legacy cash accounts.
2. Back up desk.db with SQLite's backup command/API, including a verified copy of the current schema and balances. Keep the existing source checkout for recovery.
3. Pull this branch (after review/merge) and run the offline tests below.
4. Set `RYDER_SHARED_PAPER_ACCOUNT=1` in the environment used by BOTH runner and publisher. The current shared pair is explicitly v3 + vC; changing the primary version later requires a separate migration decision.
5. Start ONE publisher once. It initializes the shared account and produces data.json. Verify shared_account.start/cash/equity, strategy results, and fallback_marks. Both cards must show that same equity.
6. Start the runner and supervisor with the same environment. Confirm paper=True and no duplicate bot instances. Keep old processes stopped.

Do not merely turn the flag off after activation: the code refuses split-account execution when it detects a shared ledger. Recovery requires stopping all processes and restoring the backed-up database AND old code together. An offline test failure or migration rejection must be investigated before starting the runner.

## Offline validation

`python -m unittest discover -s bot -p test_paper_account.py`

Tests cover single starting balance, migration idempotence/refusal, shared gains and losses, unrealized marks, strategy attribution, coin exposure, combined daily losses and simultaneous cash allocation. Compile checks cover modified Python entrypoints. A real production desk.db and live bot runtime are not available in ChatGPT; activation and runtime reconciliation must happen on the machine running RYDER.
