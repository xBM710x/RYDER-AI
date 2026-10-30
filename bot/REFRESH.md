# Refreshing the RIDER Night Desk Page
Page canvas_id: 81d90075-51be-4a50-970c-dba545f40e8d (same link every time).
The Page has no network access, so its data has to be pushed in by an agent:
1. `bash /workspace/night-desk/refresh_page.sh`  (restarts the runner if dead; writes page_data_line.txt from desk.db)
2. ReadCanvas(canvas_id) and copy the single line that starts with `const DATA: any = ` (it sits between `// DATA LINE` and `// END DATA LINE`).
3. EditCanvas(canvas_id, old_string=<that line exactly>, new_string=<contents of page_data_line.txt>).
Do not change anything else. If the edit doesn't match, ReadCanvas again and retry.

## v3 (Oct 30 2026) process model
- `supervisor.sh` (PID in supervisor.pid) is the watchdog: every 20s it restarts runner.py / publish.py if dead, and kills+restarts
  the runner if heartbeat.json is >3 min stale. Log: supervisor.log. refresh_page.sh only (re)starts the supervisor.
- The publisher needs RYDER_GITHUB_TOKEN in the env of whoever starts the supervisor (inherited; never printed or written to disk).
- No crontab/systemd on this box, so after a reboot nothing starts until the next refresh_page.sh run.
- publish.py pushes data.json every 180s (stats or heartbeat commit), adding `heartbeat` {at, runner_alive, runner_last_beat_s, pending_entries, live_feed, live_feed_events, publish_every_s}.
- v2 code backup: backup_v2/.
