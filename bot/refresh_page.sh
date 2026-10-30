#!/usr/bin/env bash
# Ensures the RYDER supervisor (watchdog for runner + publisher) is alive, then regenerates the Page DATA line.
# The Page cannot pull data itself; after this runs, an agent must push it with EditCanvas (see REFRESH.md).
cd /workspace/night-desk
if ! ps -p "$(cat supervisor.pid 2>/dev/null)" >/dev/null 2>&1; then
  [ -z "$RYDER_GITHUB_TOKEN" ] && echo "warning: RYDER_GITHUB_TOKEN not in env; supervisor will run without publisher"
  setsid nohup bash supervisor.sh >/dev/null 2>&1 < /dev/null & disown; sleep 3
  echo "supervisor started PID $(cat supervisor.pid)"
else echo "supervisor alive PID $(cat supervisor.pid)"; fi
sleep 1
for n in runner publisher; do ps -p "$(cat $n.pid 2>/dev/null)" >/dev/null 2>&1 && echo "$n alive PID $(cat $n.pid)" || echo "$n NOT running (supervisor retries every 20s; see supervisor.log)"; done
python3 export_dashboard.py > /dev/null && echo "wrote $(pwd)/page_data_line.txt ($(wc -c < page_data_line.txt) bytes)"
