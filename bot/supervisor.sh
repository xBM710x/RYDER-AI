#!/usr/bin/env bash
# RYDER watchdog (PAPER ONLY). Restarts runner + publisher if they die. Token comes only from this process's
# inherited env (RYDER_GITHUB_TOKEN); it is never printed, logged or written to disk.
cd /workspace/night-desk
echo $$ > supervisor.pid
alive() { ps -p "$(cat "$1" 2>/dev/null)" >/dev/null 2>&1; }
while true; do
  if ! alive runner.pid; then
    setsid nohup python3 -u runner.py >> runner.log 2>&1 < /dev/null & echo $! > runner.pid
    echo "$(date '+%F %T') runner (re)started PID $(cat runner.pid)" >> supervisor.log
  fi
  if ! alive publisher.pid; then
    if [ -n "$RYDER_GITHUB_TOKEN" ]; then
      setsid nohup python3 -u publish.py --loop >> publisher.log 2>&1 < /dev/null & echo $! > publisher.pid
      echo "$(date '+%F %T') publisher (re)started PID $(cat publisher.pid)" >> supervisor.log
    else echo "$(date '+%F %T') publisher down; RYDER_GITHUB_TOKEN not in env" >> supervisor.log; fi
  fi
  # stale runner (no heartbeat for 3 min) -> kill so it restarts next loop
  if [ -f heartbeat.json ] && [ $(( $(date +%s) - $(stat -c %Y heartbeat.json) )) -gt 180 ] && alive runner.pid; then
    echo "$(date '+%F %T') runner heartbeat stale; restarting" >> supervisor.log; kill "$(cat runner.pid)"; touch heartbeat.json
  fi
  sleep 20
done
