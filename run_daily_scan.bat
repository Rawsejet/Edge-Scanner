@echo off
rem run_daily_scan.bat — end-of-day batch scan, logs to scans\YYYY-MM-DD.log.
rem Schedule via Task Scheduler (see WINDOWS_SETUP.md). Complements the live
rem dashboard: this is the one you review with coffee, signals in writing.

cd /d "%~dp0"
call .venv\Scripts\activate.bat

if not exist scans mkdir scans
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd"') do set TODAY=%%i

.venv\Scripts\python.exe run_all.py >> "scans\%TODAY%.log" 2>&1
