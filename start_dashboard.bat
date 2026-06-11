@echo off
rem start_dashboard.bat — launches the live signal board on Windows.
rem Assumes venv at .venv and TRADIER_TOKEN set as a user env var.

cd /d "%~dp0"
call .venv\Scripts\activate.bat

rem Optional overrides:
rem set SCAN_INTERVAL=300
rem set QUOTE_INTERVAL=15

.venv\Scripts\python.exe -m uvicorn dashboard:app --host 0.0.0.0 --port 8787
