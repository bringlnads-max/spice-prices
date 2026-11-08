@echo off
REM Spice Price Tracker - daily update. Double-click this, or schedule it in Windows Task Scheduler.
cd /d "%~dp0"
if not exist data mkdir data
python tracker.py >> data\log.txt 2>&1
start "" "%~dp0site\index.html"
