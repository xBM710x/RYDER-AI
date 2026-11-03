#!/usr/bin/env bash
# One-time setup; run after stopping any manually started RYDER.
set -euo pipefail
cd "$(dirname "$0")"
[ "$(uname -s)" = Darwin ] || { echo 'This installer is for macOS.'; exit 1; }
DIR="$PWD"
PY="$DIR/.venv/bin/python"
[ -x "$PY" ] || { echo 'RYDER virtual environment is missing.'; exit 1; }
"$PY" -m unittest test_paper_account test_app_upgrades test_source_performance test_auto_update
mkdir -p "$HOME/Library/LaunchAgents"
PLIST="$HOME/Library/LaunchAgents/com.ryder.bot.plist"
# Safely escape spaces and XML characters using plistlib; never include .env secrets.
"$PY" - "$DIR" "$PLIST" <<'PY'
import plistlib,sys
from pathlib import Path
d=Path(sys.argv[1]);path=Path(sys.argv[2])
job=dict(Label='com.ryder.bot',ProgramArguments=[str(d/'.venv/bin/python'),'-u',str(d/'auto_update.py')],WorkingDirectory=str(d),RunAtLoad=True,KeepAlive=True,ThrottleInterval=30,StandardOutPath=str(d/'auto-update.log'),StandardErrorPath=str(d/'auto-update.log'),EnvironmentVariables=dict(PATH='/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin'))
with path.open('wb') as f:plistlib.dump(job,f)
PY
launchctl bootout "gui/$(id -u)/com.ryder.bot" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "RYDER background startup and tested updates installed. You can close Terminal."
echo "Log: $DIR/auto-update.log"
