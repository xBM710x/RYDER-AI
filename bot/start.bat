@echo off
REM Start RYDER (PAPER ONLY) on Windows. Keep this window open.
cd /d "%~dp0"
py -3 -u start.py
if errorlevel 9009 python -u start.py
pause
