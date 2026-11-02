#!/usr/bin/env bash
# Stop RYDER's Mac background job and remove auto-start.
launchctl unload ~/Library/LaunchAgents/com.ryder.bot.plist 2>/dev/null || true
rm -f ~/Library/LaunchAgents/com.ryder.bot.plist; echo "RYDER stopped and auto-start removed."
