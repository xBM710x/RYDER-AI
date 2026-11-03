#!/usr/bin/env bash
# Start RYDER (PAPER ONLY) on Mac/Linux. On a Mac, caffeinate -i keeps the computer awake while RYDER runs.
cd "$(dirname "$0")"
if [ -x .venv/bin/python ]; then PY="$PWD/.venv/bin/python"; else PY="$(command -v python3 || command -v python)"; fi
if command -v caffeinate >/dev/null 2>&1; then exec caffeinate -i "$PY" -u start.py; else exec "$PY" -u start.py; fi
