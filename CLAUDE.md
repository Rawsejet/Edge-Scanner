# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## This directory is a live deployment

`C:\edge_scanners` is not just a checkout — it is the production working copy
of a read-only market-scanning appliance (mini PC, Windows). The running
processes import these exact files, so edits take effect on the next restart
of the right component, and a syntax error will take the live signal board
down. `README.md` is the full operating manual; `COMPLETE_SETUP_GUIDE.md`
rebuilds the box from scratch.

Deployment map:

| Component | Run by | Port |
|---|---|---|
| `dashboard.py` (signal board, uvicorn) | Scheduled task `EdgeScannerDashboard` → `start_dashboard.bat` | 8787 |
| `run_all.py` (daily batch → `scans\*.log`) | Scheduled task `EdgeScannerDaily`, 5:30 PM | — |
| Prometheus (`C:\prometheus`, config copied from this repo) | Scheduled task `Prometheus` | 9090 |
| Grafana | Windows service `Grafana` | 3000 |

## Hard constraints (project rules, stated across the docstrings)

- **Never add broker write access, order placement, or brokerage credentials
  to any component.** The suite is read-only end to end by design;
  `tradier_data.py` touches only `/v1/markets/*` endpoints. The wall between
  "scanner suggests" and "human places the order in Fidelity" is a security
  control.
- **Re-backtest before changing any scanner parameter** (the threshold
  constants at the top of each `scanner_*.py`). Tuning to recent tape is
  curve-fitting; parameter changes should not touch live decisions untested.
- Secrets (`TRADIER_TOKEN`, `SCANNER_DISCORD_WEBHOOK`) live in user-level
  environment variables only — never introduce a config file for them.

## Commands

There is no build, linter, or test suite. The only interpreter with the
dependencies is the venv — system Python lacks them:

```powershell
# one-off scan of all three scanners (same code path as the daily task)
C:\edge_scanners\.venv\Scripts\python.exe run_all.py

# import/syntax check after editing (cheap smoke test)
C:\edge_scanners\.venv\Scripts\python.exe -c "import dashboard"

# run the board in the foreground to watch console output
.\start_dashboard.bat        # Ctrl+C to stop; port 8787 must be free first

# restart the live board after an edit — stopping the task alone is NOT
# enough: it kills the cmd wrapper but orphans the python holding the port
Stop-ScheduledTask -TaskName EdgeScannerDashboard
Get-NetTCPConnection -LocalPort 8787 -State Listen -ErrorAction SilentlyContinue |
  ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
Start-ScheduledTask -TaskName EdgeScannerDashboard

# health check of the whole stack
Get-ScheduledTask -TaskName EdgeScannerDashboard,EdgeScannerDaily,Prometheus | Format-Table TaskName,State
Invoke-WebRequest http://localhost:8787/metrics -UseBasicParsing | Select-Object StatusCode
```

Dependencies (no requirements.txt; install list lives in the setup guide):
`fastapi uvicorn requests pandas numpy yfinance prometheus_client`.

## Architecture

Two entry points share the same scanner modules:

- `dashboard.py` — FastAPI app; re-runs all scanners every `SCAN_INTERVAL`
  (default 300s, env override) in a background loop, broadcasts results over
  a WebSocket to an inline single-file HTML/JS frontend (the `PAGE` string at
  the bottom), and exposes Prometheus metrics at `/metrics`.
- `run_all.py` — batch driver; also owns `UNIVERSE`, the ticker list, which
  `dashboard.py` imports. Optional Discord push via `SCANNER_DISCORD_WEBHOOK`.

Data layer (`common.py`): provider is chosen **at import time** — if
`TRADIER_TOKEN` is set, `get_daily_bars`/`get_option_chain` delegate to
`tradier_data.py` (real-time, real greeks, plus `delta`/`occ_symbol` columns);
otherwise yfinance (delayed, approximate IV, no greeks). Two consequences:
changing the env var requires restarting the process, and scanner code must
tolerate both shapes — e.g. `scanner_premium.py` falls back to
`put_delta_approx()` when the `delta` column is absent. All data functions
return empty DataFrames on failure rather than raising; scanners check
`.empty` and bail per-ticker.

Each `scanner_*.py` exposes `scan(universe) -> list[Signal]` (the `Signal`
dataclass is in `common.py`) plus a market-level gate (`check_regime()` /
`crash_guard()`) that zeroes the whole scanner when off. Tunable thresholds
are module-level constants at the top of each file; the docstrings document
the edge and its failure modes — read them before touching the logic.

Monitoring flow: `dashboard.py` metrics → Prometheus scrape (30s) → Grafana.
Two files here are sources of truth for configs deployed elsewhere:
`prometheus.yml` (must be re-copied to `C:\prometheus\prometheus.yml` and the
Prometheus task restarted to take effect) and `grafana_dashboard.json`
(re-import via Grafana UI/API). Editing them in-repo alone changes nothing.
`setup_admin.ps1` is the one-shot elevated installer that created the
firewall rules and scheduled tasks — a record, not something to re-run
casually.
