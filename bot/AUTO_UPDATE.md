# Mac background startup and updates

Stop the manually running bot with Control+C, then run `git pull --ff-only` and `bash bot/install_mac.sh` from the repository root. No sudo or token in the command is needed. Keep `.env` local.

The login LaunchAgent owns one updater, supervisor, runner and publisher. Terminal can close after installation. It starts on login; it does not run while logged out, powered off, or with the laptop sleeping. Keep the Mac powered and awake. `start.sh` retains caffeinate behavior while running.

Every five minutes the updater fetches main from the exact RYDER-AI origin. A data/dashboard-only change fast-forwards without interrupting scanning. Bot code is extracted into a temporary directory, compiled, and checked with the accounting, discovery, source-performance and updater offline tests using the existing virtual environment. Tests do not receive .env or tokens. Failed checks, local tracked edits, non-fast-forward history, dependency changes and bot runtime-data changes hold the update and leave the current process running.

After checks pass, the updater stops its private process group, saves an integrity-checked SQLite backup under `bot/update-backups`, fast-forwards, and reloads itself and the bot. It never resets the working tree, copies .env, restores a ledger, or removes memory. Startup errors after passing tests are handled by existing restart supervision; this is not an automatic runtime-health rollback. Dependency updates need separate setup. Update backups are retained until you choose to remove them.

`bot/auto-update.log` shows applied or held updates. `bash bot/uninstall_mac.sh` stops the service and removes login startup without removing state. Only one machine should publish. The installer replaces the earlier com.ryder.bot login job.

### Candidate test coverage

The updater reads the incoming `bot/auto_update.py` TESTS list as a literal
Python list, without importing candidate code to discover tests. Validation runs
the union of the running updater's tests and the candidate's tests. Missing test
modules, duplicate or malformed declarations, nonliteral lists, and failed tests
hold the update while the current runner remains in place. Removing a retained
test requires an explicit updater migration rather than silently dropping coverage.

Regression coverage includes actual isolated subprocess runs where an added test
fails, an existing test fails, and both pass. This changes installation validation
only; it does not modify trading parameters, exits, or the dashboard.
