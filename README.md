# Edge Scanner Appliance — Operating Manual

This mini PC is a self-contained, **read-only** market scanning appliance. It
runs four scanners against a small universe of liquid tickers, shows the
results on a live signal board, logs a daily end-of-day scan to disk, and
monitors its own health with Prometheus + Grafana. **No component places
trades, and none should ever be given broker write access.** You review
signals here and place any orders yourself in Fidelity.

> Deployed 2026-06-10 on TEJA-MINIPC: Python 3.13.14 (venv), Prometheus
> 3.12.0, Grafana OSS 13.0.2. Setup history: `COMPLETE_SETUP_GUIDE.md`,
> `WINDOWS_SETUP.md`, `MONITORING_SETUP.md`. The elevated installer that
> created the firewall rules and scheduled tasks is `setup_admin.ps1` (its run
> log is `setup_admin.log`).

---

## Table of contents

1. [Quick reference card](#1-quick-reference-card)
2. [What's installed where](#2-whats-installed-where)
3. [Daily operation — the workflow](#3-daily-operation--the-workflow)
4. [The Signal Board (port 8787)](#4-the-signal-board-port-8787)
5. [Grafana (port 3000)](#5-grafana-port-3000)
6. [Prometheus (port 9090)](#6-prometheus-port-9090)
7. [Starting and stopping everything manually](#7-starting-and-stopping-everything-manually)
8. [Configuration — where to change things](#8-configuration--where-to-change-things)
9. [Logs and data locations](#9-logs-and-data-locations)
10. [Maintenance](#10-maintenance)
11. [Troubleshooting](#11-troubleshooting)
12. [Security](#12-security)

---

## 1. Quick reference card

| Thing | Where |
|---|---|
| Signal board | http://localhost:8787 (LAN: http://192.168.1.246:8787) |
| Raw metrics | http://localhost:8787/metrics |
| Prometheus UI | http://localhost:9090 (localhost only — not opened to LAN) |
| Grafana | http://localhost:3000 (LAN: http://192.168.1.246:3000) |
| Grafana dashboard | "Edge Scanner Suite" → http://localhost:3000/d/edge-scanners |
| Grafana login | `admin` / `admin` ⚠️ **change this — see [Security](#12-security)** |
| App folder | `C:\edge_scanners` (venv in `.venv\`) |
| Prometheus folder | `C:\prometheus` (data in `C:\prometheus\data`) |
| Grafana folder | `C:\Program Files\GrafanaLabs\grafana` (runs as Windows service "Grafana") |
| Daily scan logs | `C:\edge_scanners\scans\YYYY-MM-DD.log` |
| Scheduled tasks | `EdgeScannerDashboard` (login), `Prometheus` (login), `EdgeScannerDaily` (5:30 PM daily) |
| Tradier token | User env vars `TRADIER_TOKEN` + `TRADIER_ENV` — **not set yet**, see [§8.1](#81-tradier-token-real-time-data) |

The LAN IP `192.168.1.246` is DHCP-assigned and can change. If the board stops
loading from your phone, check the current IP with `ipconfig` (IPv4 Address
under Wi-Fi) — or give this machine a DHCP reservation in your router so it
never moves.

---

## 2. What's installed where

Five moving parts:

1. **Signal board (dashboard.py)** — FastAPI + uvicorn server on port 8787.
   Re-runs all scanners every 5 minutes, pushes results to the browser over a
   WebSocket, and exposes Prometheus metrics at `/metrics`. Started by the
   `EdgeScannerDashboard` scheduled task.
2. **Daily batch scan (run_daily_scan.bat → run_all.py)** — one full scan run
   every day at **5:30 PM** by the `EdgeScannerDaily` task, output appended to
   `scans\YYYY-MM-DD.log`. This is the one you review with coffee — signals in
   writing, after the close.
3. **Prometheus** — scrapes the board's `/metrics` every 30s, keeps 90 days
   of history at `C:\prometheus\data`. Started by the `Prometheus` task.
4. **Grafana** — graphs what Prometheus stored. Installed as a real Windows
   service ("Grafana", start type Automatic), so it runs even before login.
5. **Scanners + data layer** (`scanner_*.py`, `common.py`, `tradier_data.py`)
   — imported by both the board and the daily scan. Data comes from Tradier
   when `TRADIER_TOKEN` is set (real-time quotes, real greeks), otherwise
   falls back to yfinance (free, delayed, approximate options IV).

**Boot behavior — read this once.** The `EdgeScannerDashboard` and
`Prometheus` tasks are registered with an *Interactive* logon, which means
Windows starts them **when you log in**, not at power-on. Grafana (a service)
starts at power-on regardless. So after a reboot: log in once, and within a
minute everything is up — the tasks also auto-restart their process up to 3
times if it crashes. If you ever want the box fully headless (scans running
with nobody logged in), you'd enable Windows auto-login — see the trade-off
note in [Security](#12-security).

---

## 3. Daily operation — the workflow

The code finds candidates; the discipline below is the actual strategy.

1. **Scan** — glance at the board during the day; read
   `scans\<today>.log` after 5:30 PM. Signals are **candidates, never
   orders**.
2. **Verify** — check news on every MEANREV name (a stock down 20% on fraud
   allegations is not "mean reverting"); check the `earnings_in_window` flag
   on every PREMIUM signal (if `True`, you'd be selling a binary event).
3. **Size** — premium selling: collateral ≤ 10% of account per name.
   Directional (momentum/meanrev): risk-per-trade ≤ 1% of account to the stop.
4. **Log every trade** with the signal that generated it. After 30+ trades per
   scanner, compare live results to expectations. Cut what underperforms.
5. **Re-backtest before changing any parameter.** Tuning parameters to match
   last month's tape is curve-fitting with extra steps.

**What this will and won't do.** It will surface a handful of decent setups
per week and keep you out of the worst ones. It will not produce daily
profits, and on many days it will correctly produce nothing — "no signals" is
a valid output, and forcing trades on no-signal days is where edges go to die.
Realistic outcome with discipline: single-digit to low-double-digit annual
returns above buy-and-hold, with real drawdowns. Anything promising more is
curve-fit or fraudulent.

---

## 4. The Signal Board (port 8787)

Open http://localhost:8787 (or from your phone on the same Wi-Fi,
http://192.168.1.246:8787). The page has four zones, top to bottom:

### 4.1 Regime rail (top)

Two big status cells — the board's spine. When a regime is OFF, ignore that
scanner's absence of signals; it's standing down on purpose.

| Cell | Green | Red | Meaning |
|---|---|---|---|
| MOMENTUM REGIME | `RISK-ON` | `STANDING DOWN` | SPY above/below its 200-day SMA. Momentum's worst drawdowns cluster below the 200SMA, so the scanner takes **zero** signals when red. |
| MEANREV CRASH GUARD | `CLEAR` | `GUARD ACTIVE` | SPY 14-day RSI above/below 25. In a genuine crash everything looks "oversold" all the way down — red means stand down. |

### 4.2 Quote tape

Real-time last price and day % for every ticker in the universe, refreshed
every 15 seconds. **The tape only appears when `TRADIER_TOKEN` is set** —
until then it's simply absent (this is the quickest visual check that Tradier
is wired up and working).

### 4.3 Signal feed

One row per signal from the most recent scan (full scan every 5 minutes).
Color-coded by scanner. What each one means and which detail fields matter:

**PREMIUM (gold) — cash-secured put / wheel candidates.** Edge: implied vol
systematically trades above subsequently-realized vol, so disciplined OTM put
sellers get paid more than fair price. Headline reads like
`CSP 40P 2026-06-12 @ 0.85` — strike, expiry, mid premium.
- `iv_rv` — 30d IV vs 20d realized vol; only shown when ≥ 1.20 (you're being
  overpaid relative to actual movement).
- `delta` — between −0.30 and −0.15 (roughly 15–30% chance of assignment).
- `ann_yield` — annualized premium on the cash collateral; floor is 15%.
- `earnings_in_window` — **if `True`, IV is inflated by an event, not edge.
  Respect this flag.**
- With Tradier configured, signals carry the OCC contract symbol (e.g.
  `ASTS260612P00040000`) — it identifies the exact contract in Fidelity's
  chain.
- Filters already applied for you: stock above 200SMA (no falling knives),
  open interest ≥ 200, bid-ask spread ≤ 8% of mid.

**MOMENTUM (green) — trend-following entries.** Edge: 3–12 month winners keep
winning over the next 1–3 months (most robust anomaly in the academic
literature). Pays over weeks/months, not intraday.
- Already filtered for: close > 50SMA > 200SMA (stage-2 uptrend), 12-1
  momentum ≥ +20%, ADX ≥ 20 (trending, not chopping), within 10% of the
  52-week high, ≥ $20M/day dollar volume.
- `suggested_trail_stop` — 3×ATR below current price. **Entries matter less
  than exits: define your stop before opening the position.** Exit on the
  trail or on a close below the 50SMA.

**MEANREV (purple) — short-term washouts in uptrends.** Edge: sharp 2–5 day
selloffs in stocks that remain in healthy long-term uptrends tend to snap
back (classic RSI(2)/Connors setup). Small edge per trade, decays fast.
- Already filtered for: above 200SMA (non-negotiable), RSI(2) ≤ 10, 20-day
  z-score ≤ −1.5, ≥ $50M/day dollar volume (large caps only).
- `plan` field states the exit discipline: **time-stop 5 trading days max,
  win or lose, or exit when RSI(2) > 60.** Reversion entries get worse before
  they get better — size smaller rather than stopping tighter.
- `check_news_first=True` appears on every signal because it's always true.

A scanner error shows up as a row with ticker `—` and the exception text in
the headline (and increments the error counter in Grafana).

### 4.4 Footer / behavior notes

- "last scan HH:MM:SS UTC" in the header tells you freshness; the page
  reconnects its WebSocket automatically if the server restarts.
- A full chain scan is heavy (one request per ticker per expiry). The 5-minute
  default interval is deliberate; faster mostly buys rate-limit errors, not
  edge.

---

## 5. Grafana (port 3000)

Health-of-the-pipeline view. The signal board tells you what the market is
doing; Grafana tells you whether **the appliance itself** is working.

- URL: http://localhost:3000 → log in (`admin`/`admin` until you change it —
  do that today, see [Security](#12-security)).
- The dashboard is already imported: **Dashboards → Edge Scanner Suite** (or
  directly http://localhost:3000/d/edge-scanners). Data source "Prometheus"
  (http://localhost:9090) is already configured as the default.

### Panels and how to read them

| Panel | What it shows | What to do about it |
|---|---|---|
| **Momentum Regime** | RISK-ON / STANDING DOWN | Mirrors the board's rail; same meaning. |
| **MeanRev Crash Guard** | CLEAR / GUARD ACTIVE | Mirrors the board's rail. |
| **Minutes Since Last Scan** | Freshness of the scan loop. Green < 10, yellow 10–30, red > 30. | **This is the canary.** If it climbs past ~10 during market hours, the scan loop is stuck (rate limits, network, exception). Restart the dashboard task (§7.1). |
| **Scanner Errors (24h)** | Sum of scanner exceptions in 24h. Green at 0, red ≥ 1. | One-off errors happen (flaky network). A climbing count means a data-source problem — check yfinance upgrade / Tradier token (§11). |
| **Signals per Scan by Scanner** | Time series per scanner. | Establishes your baseline. If PREMIUM goes from ~3/day to 0 for a week, either vol collapsed (real) or the data adapter broke — cross-check the errors panel to tell which. |
| **Scan Duration (p50 / p95)** | How long full scans take. | If p95 approaches the scan interval (300s), scans start overlapping their schedule — trim the universe or raise `SCAN_INTERVAL` (§8.2). |

Panels need a couple of scans of history before lines appear — give a fresh
boot ~10 minutes. Time range / refresh are in the top-right (defaults:
last 24h, refresh 30s).

---

## 6. Prometheus (port 9090)

You'll rarely open it directly — Grafana fronts it — but for digging:

- **http://localhost:9090/targets** — both `edge_scanners` and `prometheus`
  must show **UP**. `edge_scanners` DOWN = the dashboard isn't running.
- **http://localhost:9090/graph** — ad-hoc queries. Useful ones:
  - `scanner_signals` — current signals per scanner
  - `scanner_regime_on` — regime flags (1 = on)
  - `(time() - scanner_last_scan_timestamp) / 60` — minutes since last scan
  - `increase(scanner_errors_total[24h])` — errors per scanner, last 24h
  - `histogram_quantile(0.95, rate(scanner_scan_duration_seconds_bucket[1h]))` — p95 scan time
- Retention is 90 days (set via the scheduled task's command line). At 30s
  scrape on a handful of series that's well under 1 GB.
- Prometheus is deliberately **not** reachable from the LAN (no firewall
  rule). Grafana queries it locally. Leave it that way.

---

## 7. Starting and stopping everything manually

Everything below is plain PowerShell — no admin needed except where marked.
**Rule of one:** each port can only have one owner. Don't start a component
manually while its scheduled task already has it running (you'll get a
port-in-use error; see §11).

### 7.0 Status of everything, one command

```powershell
Get-ScheduledTask -TaskName EdgeScannerDashboard,EdgeScannerDaily,Prometheus | Format-Table TaskName,State
Get-Service Grafana
Get-NetTCPConnection -LocalPort 8787,9090,3000 -State Listen -ErrorAction SilentlyContinue | Format-Table LocalPort,OwningProcess
```

Healthy: Dashboard + Prometheus tasks `Running`, Daily `Ready`, Grafana
`Running`, and all three ports listed.

### 7.1 Signal board (dashboard)

```powershell
Start-ScheduledTask -TaskName EdgeScannerDashboard      # start
```

**Stopping takes two commands.** The task launches `start_dashboard.bat`
through a `cmd.exe` wrapper, and `Stop-ScheduledTask` only kills the wrapper —
the python/uvicorn server underneath survives as an orphan and keeps holding
port 8787. A subsequent start then dies with `[WinError 10048] only one usage
of each socket address`. Always stop like this:

```powershell
Stop-ScheduledTask -TaskName EdgeScannerDashboard
Get-NetTCPConnection -LocalPort 8787 -State Listen -ErrorAction SilentlyContinue |
  ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
# restart = the two lines above, then Start-ScheduledTask
```

Run it by hand instead (to watch the console output, e.g. while debugging):

```powershell
# stop the managed copy first (two commands above), then:
cd C:\edge_scanners
.\start_dashboard.bat                                    # Ctrl+C to stop
```

### 7.2 Daily batch scan

It fires on its own at 5:30 PM, but you can run one any time — output appends
to today's log:

```powershell
cd C:\edge_scanners
.\run_daily_scan.bat
Get-Content scans\(Get-Date -Format yyyy-MM-dd).log
# or trigger the scheduled version: Start-ScheduledTask -TaskName EdgeScannerDaily
```

### 7.3 Prometheus

```powershell
Start-ScheduledTask -TaskName Prometheus
Stop-ScheduledTask  -TaskName Prometheus
```

By hand (debugging — note the task's version adds 90d retention):

```powershell
Stop-ScheduledTask -TaskName Prometheus
C:\prometheus\prometheus.exe --config.file=C:\prometheus\prometheus.yml --storage.tsdb.retention.time=90d
```

### 7.4 Grafana (Windows service)

```powershell
Get-Service Grafana                  # status
Restart-Service Grafana              # admin PowerShell
Stop-Service Grafana                 # admin PowerShell
Start-Service Grafana                # admin PowerShell
```

(Or `services.msc` → "Grafana" → right-click.)

### 7.5 Stop everything / start everything

```powershell
# stop all
Stop-ScheduledTask -TaskName EdgeScannerDashboard,Prometheus
Get-NetTCPConnection -LocalPort 8787 -State Listen -ErrorAction SilentlyContinue |
  ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }    # orphaned server, see §7.1
Stop-Service Grafana            # admin

# start all
Start-ScheduledTask -TaskName EdgeScannerDashboard
Start-ScheduledTask -TaskName Prometheus
Start-Service Grafana           # admin
```

### 7.6 Disabling auto-start (e.g. taking the box offline for a while)

```powershell
Disable-ScheduledTask -TaskName EdgeScannerDashboard,EdgeScannerDaily,Prometheus   # admin
Set-Service Grafana -StartupType Manual                                            # admin
# re-enable: Enable-ScheduledTask ... / Set-Service Grafana -StartupType Automatic
```

---

## 8. Configuration — where to change things

### 8.1 Tradier token (real-time data) — **currently NOT set**

Right now the suite runs on the yfinance fallback: delayed daily bars,
approximate options IV, **no quote tape**, Black-Scholes-approximated deltas.
It works, but the PREMIUM scanner is materially better with real greeks. To
upgrade:

1. Open a brokerage account at tradier.com (the account is the gateway to the
   market-data API; check their current terms for data entitlements).
2. Log in → account settings → **API Access** → copy your **production**
   access token (the sandbox token returns delayed data).
3. In PowerShell (keep the quotes, paste your token):
   ```powershell
   [Environment]::SetEnvironmentVariable("TRADIER_TOKEN", "YOUR_TOKEN", "User")
   [Environment]::SetEnvironmentVariable("TRADIER_ENV", "prod", "User")
   ```
4. Restart the processes that read it (new processes only see env vars set
   before they started):
   ```powershell
   Stop-ScheduledTask -TaskName EdgeScannerDashboard
   Start-ScheduledTask -TaskName EdgeScannerDashboard
   ```
   If the quote tape still doesn't appear in ~30s, reboot once — Task
   Scheduler occasionally holds a stale environment.
5. Verify: tape visible on the board, and `echo $env:TRADIER_TOKEN` prints the
   token in a **new** PowerShell window.

Why an env var and not a config file: the token never sits in a file that
could get copied, zipped, or committed somewhere by accident. See
[Security](#12-security) for handling and revocation.

### 8.2 Scan cadence

`SCAN_INTERVAL` (full scan, default 300s) and `QUOTE_INTERVAL` (tape, default
15s) are env-var overrides read by `dashboard.py`. Set them in
`start_dashboard.bat` — the commented `rem set SCAN_INTERVAL=300` lines show
exactly where. Don't go below ~120s: chain scans are one request per ticker
per expiry, so faster intervals mostly buy rate-limit errors, and none of
these edges decay on a seconds timescale. Restart the dashboard task after
editing.

### 8.3 Ticker universe

`UNIVERSE` list at the top of `run_all.py` — used by both the board and the
daily scan. Keep it small and liquid; a 500-name universe mostly adds noise
and rate limits. Restart the dashboard task after editing (the daily scan
picks it up automatically on its next run).

### 8.4 Scanner parameters

Each scanner's thresholds sit in a clearly marked block at the top of its
file, with docstrings explaining the edge and its failure modes:

| File | Knobs |
|---|---|
| `scanner_premium.py` | `MIN_IV_RV_RATIO` (1.20), `DELTA_RANGE` (−0.30…−0.15), `DTE_RANGE` (21–45), `MIN_OI` (200), `MAX_SPREAD_PCT` (0.08), `MIN_ANN_YIELD` (0.15), `REQUIRE_ABOVE_200SMA` |
| `scanner_momentum.py` | `MIN_MOM_12_1` (0.20), `MIN_ADX` (20), `MAX_PCT_OFF_HIGH` (0.10), `MIN_AVG_DOLLAR_VOL` ($20M), `REGIME_TICKER` (SPY) |
| `scanner_meanreversion.py` | `MAX_RSI2` (10), `MAX_ZSCORE` (−1.5), `MIN_AVG_DOLLAR_VOL` ($50M), `SPY_CRASH_GUARD_RSI` (25) |

House rule worth repeating: **re-backtest before any parameter change touches
live decisions.** Restart the dashboard task after editing.

### 8.5 Daily scan time

Registered for 5:30 PM local. To move it (admin PowerShell):

```powershell
Set-ScheduledTask -TaskName EdgeScannerDaily -Trigger (New-ScheduledTaskTrigger -Daily -At 6:00PM)
```

### 8.6 Optional Discord push for the daily scan

`run_all.py` posts the daily signals to a Discord webhook if
`SCANNER_DISCORD_WEBHOOK` is set (same user-env-var pattern as the token):

```powershell
[Environment]::SetEnvironmentVariable("SCANNER_DISCORD_WEBHOOK", "https://discord.com/api/webhooks/...", "User")
```

Treat the webhook URL as a secret — anyone holding it can post to your
channel.

### 8.7 Prometheus scrape config and retention

- Scrape targets/interval: `C:\prometheus\prometheus.yml` (a commented
  `windows` job is ready if you ever install windows_exporter for host
  CPU/RAM/disk metrics — see `MONITORING_SETUP.md` §4).
- Retention (90d): lives in the scheduled task's command-line argument, not
  the yml. Change it by re-registering the task (admin) or via Task Scheduler
  GUI → Prometheus → Actions tab.
- Restart the Prometheus task after either change.

### 8.8 Grafana settings

- Password/users: gear icon → Administration → Users (or see §12 for the
  do-it-now password change).
- Datasource: Connections → Data sources → Prometheus
  (`http://localhost:9090`).
- The dashboard is provisioned via API from `grafana_dashboard.json`; if you
  edit panels in the UI, Grafana stores its own copy — keep the json as the
  source of truth by re-exporting (dashboard → Share → Export) over the file.

---

## 9. Logs and data locations

| What | Where |
|---|---|
| Daily scan output | `C:\edge_scanners\scans\YYYY-MM-DD.log` (plain text, accumulates; a year is a few MB — prune whenever) |
| Dashboard console | No file — it logs to its console window. Run it by hand (§7.1) to watch; uvicorn access lines + scanner prints. |
| Prometheus TSDB + logs | `C:\prometheus\data\` (auto-pruned at 90d); console output in its window |
| Grafana logs | `C:\Program Files\GrafanaLabs\grafana\data\log\grafana.log` |
| Grafana DB (dashboards, users) | `C:\Program Files\GrafanaLabs\grafana\data\grafana.db` |
| Grafana MSI install log | `C:\edge_scanners\grafana_install.log` (from setup; safe to delete) |
| Elevated setup transcript | `C:\edge_scanners\setup_admin.log` |
| Task history / last results | Task Scheduler app → Task Scheduler Library → each task → History / Last Run Result |

---

## 10. Maintenance

- **yfinance breaks occasionally** (their endpoints shift). Symptom: errors
  panel climbing, empty scans, exceptions mentioning yfinance. Fix:
  ```powershell
  C:\edge_scanners\.venv\Scripts\python.exe -m pip install --upgrade yfinance
  ```
  then restart the dashboard task. Same pattern for other packages.
- **Prometheus upgrade:** download the new `windows-amd64.zip`, stop the task,
  replace the exes in `C:\prometheus` (keep `prometheus.yml` and `data\`),
  start the task.
- **Grafana upgrade:** download the new MSI, run it (admin), it upgrades the
  service in place; dashboards/users survive in `grafana.db`.
- **Windows Updates:** leave them on. The box reboots; after you log back in,
  the tasks bring everything up — re-glance at §7.0.
- **Disk:** everything here is tiny (logs a few MB/year, TSDB < 1 GB). No
  action needed.

---

## 11. Troubleshooting

First diagnostic, always: run the three status commands in §7.0, then open
Grafana's "Minutes Since Last Scan."

| Symptom | Cause → fix |
|---|---|
| Board not loading at :8787 | Task not running → `Start-ScheduledTask EdgeScannerDashboard`. Still down? Run `.\start_dashboard.bat` by hand (§7.1) and read the error it prints. |
| Dashboard starts then exits instantly | Run it by hand from PowerShell (not double-click) to see the traceback — usually a missing package (reinstall: §Part 2 of `COMPLETE_SETUP_GUIDE.md`) or a syntax error from a recent edit. |
| "address already in use" / `[WinError 10048]` on start | An earlier copy still holds the port — usually because `Stop-ScheduledTask` alone orphans the dashboard's python (see §7.1). Kill it: `Get-NetTCPConnection -LocalPort 8787 -State Listen \| ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }`, then start via the task. |
| Board loads, **no quote tape** | Expected when `TRADIER_TOKEN` isn't set (current state). If you've set it: token invalid, or process started before the var existed → restart task; reboot if stubborn. |
| `TRADIER_TOKEN not set` in scan logs | Set it (§8.1) and **fully restart** the task/process — running processes never see new env vars. |
| 401 errors from Tradier | Wrong token, or sandbox token with `TRADIER_ENV=prod`. Match token to environment. |
| Board empty / "scanner error" rows | Read the headline text — it contains the exception. yfinance breakage → upgrade it (§10). Rate limiting → universe too big or interval too low. |
| Signals look stale | Grafana "Minutes Since Last Scan" > 10 → scan loop stuck → restart dashboard task. |
| Daily log missing after 5:30 PM | Task Scheduler → EdgeScannerDaily → Last Run Result. `0x0` is success. Was the box asleep/off at 5:30? Run it manually (§7.2). Note: the task only fires if you're logged in (Interactive logon). |
| Prometheus target `edge_scanners` DOWN | Dashboard not running, or it crashed mid-scan — restart its task; the Prometheus side is fine. |
| Both Prometheus targets DOWN / :9090 dead | Prometheus task stopped → start it. If it dies instantly: another copy holds the port or the data dir lock — `Get-Process prometheus`, stop strays, start the task. |
| Grafana "No data" on all panels | Data source URL must be exactly `http://localhost:9090` (Connections → Data sources → test). Or Prometheus has < 2 scrapes of history — wait a minute. |
| Grafana login lost | Reset from admin PowerShell: `& 'C:\Program Files\GrafanaLabs\grafana\bin\grafana.exe' cli --homepath 'C:\Program Files\GrafanaLabs\grafana' admin reset-admin-password NEWPASSWORD` then restart the service. |
| Unreachable from phone | Wrong/changed IP (`ipconfig`), network profile flipped to Public (§12 audit), or firewall rule disabled. Re-check each. |
| Everything dead after reboot | Did you log in? Tasks are Interactive-logon. Then Task Scheduler → each task → Last Run Result; run each manually to surface errors. |
| `Activate.ps1 cannot be loaded` | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, retry. |

---

## 12. Security

### Threat model in one paragraph

Everything here is **read-only toward your money** (the code only ever calls
Tradier's `/v1/markets/*` market-data endpoints — no account, no orders, no
write scope) and **LAN-only toward the world** (no port is reachable from the
internet). The services themselves have little or no authentication — that is
a deliberate design for a private appliance, and it stays safe only as long
as the perimeter assumptions below keep holding. Anyone on your home Wi-Fi
can see the signal board; that's the intended trust boundary.

### Do these now (one-time hardening)

1. **Change the Grafana password.** It is still `admin`/`admin`. Open
   http://localhost:3000 → log in → it prompts for a new password (or: avatar
   → Change password). Grafana is LAN-reachable, and a default admin password
   on the LAN is the single weakest point of this whole setup.
2. **Confirm the firewall posture** (what's open and to whom):
   ```powershell
   Get-NetFirewallRule -DisplayName 'Edge Scanner Dashboard','Grafana' | Format-Table DisplayName,Enabled,Profile,Action
   Get-NetConnectionProfile | Format-Table Name,InterfaceAlias,NetworkCategory
   ```
   Expected: both rules `Enabled=True, Profile=Private`, and your Wi-Fi
   (`ThePerfectStorm 3`) showing `NetworkCategory=Private`. The rules are
   scoped to Private on purpose: if Windows ever reclassifies the network as
   Public, the ports silently close — which is the correct failure mode.
3. **Router check:** make sure there is **no port-forward** to this machine
   (8787, 3000, 9090 or anything else), and UPnP isn't exposing it. The
   dashboard and Grafana have no/weak auth — internet exposure would hand the
   board, and Grafana, to anyone who scans your IP. While you're in the
   router: admin password not default, Wi-Fi WPA2/WPA3 with a strong
   passphrase — the LAN is this appliance's security boundary, so the Wi-Fi
   password effectively *is* the dashboard's password.

### Ports — what's open and why

| Port | Service | Auth | Exposure |
|---|---|---|---|
| 8787 | Signal board + /metrics | none (by design) | LAN (Private profile only) |
| 3000 | Grafana | password login | LAN (Private profile only) |
| 9090 | Prometheus | none | **localhost only** — no firewall rule exists; keep it that way (Grafana reaches it locally) |

Never port-forward any of these on the router. If you ever want to check the
board from outside the house, the right tools are a VPN into your LAN
(WireGuard/Tailscale-style), never an opened port.

### Keys and secrets

- **`TRADIER_TOKEN`** (when you set it) lives only in your user-level
  environment — never in a file, script, or backup zip. Two consequences to
  understand: (a) nothing here will accidentally leak it into a copied
  folder, and (b) **any program running as your Windows user can read it** —
  so don't run untrusted software on this box; it's an appliance, keep it
  boring. The code treats it read-only, but scope is decided by Tradier's
  side — treat the token as if it could do anything your Tradier login can.
- **If the token ever leaks** (pasted in a chat, zipped into a backup,
  machine compromised): log in to tradier.com → API Access → revoke/rotate
  the token, then update the env var (§8.1) and restart the dashboard task.
- **`SCANNER_DISCORD_WEBHOOK`** (if you use it) is also a write-capable
  secret — same env-var handling, rotate it in Discord if exposed.
- **Never give any automated component broker write access.** No order
  endpoints, no Fidelity credentials on this box, ever. The wall between
  "scanner suggests" and "human places the order" is a security control, not
  just a philosophy.

### Ongoing hygiene

- **Windows Update stays on.** This box is exactly the kind of forgotten
  always-on machine that ages into a liability.
- **Don't install other software** on the appliance — every extra program is
  something that can read your token and your LAN.
- **Auto-login trade-off:** the scheduled tasks start at login (§2). Enabling
  Windows auto-login makes the box truly hands-off after power loss, but it
  means anyone with physical access gets a logged-in session (and token
  access) just by power-cycling. In a home, auto-login is usually an
  acceptable trade — decide consciously. If you enable it, lock the screen
  (Win+L) rather than logging out.
- **Periodic 60-second audit** (monthly, or whenever something feels off):
  ```powershell
  # 1. What's listening, and is it only the expected trio (+ nothing public)?
  Get-NetTCPConnection -State Listen | Where-Object LocalPort -in 8787,9090,3000 | Format-Table LocalAddress,LocalPort,OwningProcess
  # 2. Network still Private? Rules still scoped to Private?
  Get-NetConnectionProfile | Format-Table Name,NetworkCategory
  Get-NetFirewallRule -DisplayName 'Edge Scanner Dashboard','Grafana' | Format-Table DisplayName,Enabled,Profile
  # 3. Anything else listening that you don't recognize?
  Get-NetTCPConnection -State Listen | Where-Object {$_.LocalAddress -notin '127.0.0.1','::1'} | Sort-Object LocalPort | Format-Table LocalAddress,LocalPort,OwningProcess
  ```
- **`setup_admin.log` / `grafana_install.log`** contain no secrets (verified),
  but they do describe your setup — fine to keep, fine to delete.

---

## Appendix — file inventory

| File | Role |
|---|---|
| `dashboard.py` | Live signal board server (FastAPI/uvicorn, port 8787, /metrics) |
| `run_all.py` | Daily driver; defines `UNIVERSE`; optional Discord push |
| `scanner_premium.py` | Variance-risk-premium CSP/wheel scanner |
| `scanner_momentum.py` | 12-1 cross-sectional momentum scanner + SPY regime filter |
| `scanner_meanreversion.py` | RSI(2)/z-score washout scanner + SPY crash guard |
| `research_inefficiencies.py` | Hypothesis-testing research harness (process, not scanner) |
| `common.py` | Shared data layer (Tradier/yfinance switch) + indicators + Signal/emit |
| `tradier_data.py` | Tradier market-data adapter (read-only, `/v1/markets/*` only) |
| `start_dashboard.bat` | Launches the board (used by the EdgeScannerDashboard task) |
| `run_daily_scan.bat` | Runs `run_all.py` → `scans\YYYY-MM-DD.log` (used by EdgeScannerDaily task) |
| `prometheus.yml` | Source of truth for the Prometheus config (copied to `C:\prometheus`) |
| `grafana_dashboard.json` | Source of truth for the Grafana dashboard |
| `setup_admin.ps1` / `setup_admin.log` | One-shot elevated installer + its transcript |
| `COMPLETE_SETUP_GUIDE.md` | The full from-scratch setup walkthrough |
| `WINDOWS_SETUP.md`, `MONITORING_SETUP.md` | Component-level setup references |
| `.venv\` | Private Python environment (Python 3.13, all packages) |
| `scans\` | Daily scan logs |
