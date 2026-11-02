#!/usr/bin/env bash
# Install RYDER as an always-on Mac background job (starts at login, restarts if it stops).
set -e; cd "$(dirname "$0")"; DIR="$(pwd)"
mkdir -p ~/Library/LaunchAgents
sed "s#RYDER_DIR#$DIR#g" com.ryder.bot.plist > ~/Library/LaunchAgents/com.ryder.bot.plist
launchctl unload ~/Library/LaunchAgents/com.ryder.bot.plist 2>/dev/null || true
launchctl load ~/Library/LaunchAgents/com.ryder.bot.plist
echo "RYDER installed and started. Log: $DIR/supervisor.log"
