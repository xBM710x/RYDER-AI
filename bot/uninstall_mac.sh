#!/usr/bin/env bash
set -euo pipefail
launchctl bootout "gui/$(id -u)/com.ryder.bot" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/com.ryder.bot.plist"
echo 'RYDER background service stopped; auto-start and auto-update removed. Memory retained.'
