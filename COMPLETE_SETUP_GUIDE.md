# Complete Setup Guide — Edge Scanner Suite on Windows
### Every step, start to finish. Budget 60–90 minutes.

This takes the mini PC from a blank Windows install to: live signal board,
real-time Tradier data, daily logged scans, and a Prometheus + Grafana
monitoring stack — all self-contained, nothing touching your other machines.

---

## Part 0 — Get the files onto the mini PC (5 min)

1. Download `edge_scanners_windows.zip` from this chat onto any machine.
2. Move it to the mini PC (USB stick, network share, or re-download there).
3. Right-click the zip → **Extract All…** → set the destination to `C:\`
   → Extract. You should now have `C:\edge_scanners\` containing the `.py`,
   `.bat`, `.md`, `.yml`, and `.json` files.
   - If extraction created a nested folder (`C:\edge_scanners\edge_scanners\`),
     move the inner folder's contents up so the files sit directly in
     `C:\edge_scanners\`.

## Part 1 — Install Python (10 min)

1. In a browser on the mini PC, go to **python.org → Downloads** and download
   the latest Python 3.12+ Windows installer (64-bit).
   - Do NOT use the Microsoft Store version — it sandboxes file paths.
2. Run the installer. On the FIRST screen, check the box
   **“Add python.exe to PATH”** at the bottom. This matters; everything else
   assumes it.
3. Click **Install Now**. Finish and close.
4. Verify: press **Win+X → Terminal** (or search "PowerShell"), then type:
   ```powershell
   python --version
   ```
   You should see `Python 3.12.x` or newer. If you get
   `'python' is not recognized`, the PATH box was missed — re-run the
   installer → Modify → check the PATH option.

## Part 2 — Create the environment and install packages (10 min)

All in PowerShell:

```powershell
cd C:\edge_scanners
python -m venv .venv
```

This creates a private Python environment in `C:\edge_scanners\.venv` so
nothing here interferes with the rest of the system.

Activate it:

```powershell
.\.venv\Scripts\Activate.ps1
```

If you get a red error about "running scripts is disabled", run this once,
answer Y, then retry the activate command:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Your prompt should now start with `(.venv)`. Install everything:

```powershell
pip install fastapi uvicorn requests pandas numpy yfinance prometheus_client
```

Wait for it to finish (a few minutes). Errors about "could not find a
version" usually mean no internet or a typo.

## Part 3 — Tradier account and token (15 min)

The scanners run without this (yfinance fallback, delayed data), so you can
skip to Part 4 and come back. For real-time quotes and real greeks:

1. Go to **tradier.com** and open a brokerage account (you don't have to fund
   trades through them — the account is the gateway to the market data API;
   check their current terms for data entitlement requirements).
2. Once approved, log in → API Access (in account settings) → create/copy
   your **production access token**. There's also a **sandbox** token —
   useful for testing, but its data is delayed.
3. Store the token as a user-level environment variable. In PowerShell
   (replace YOUR_TOKEN, keep the quotes):
   ```powershell
   [Environment]::SetEnvironmentVariable("TRADIER_TOKEN", "YOUR_TOKEN", "User")
   [Environment]::SetEnvironmentVariable("TRADIER_ENV", "prod", "User")
   ```
4. **Close PowerShell completely and open a new one.** Env vars only apply to
   processes started after they're set.
5. Verify:
   ```powershell
   echo $env:TRADIER_TOKEN
   ```
   Should print your token.

Why an env var and not a config file: the token never sits in a file that
could get copied, zipped, or committed somewhere by accident.

## Part 4 — First manual run (10 min)

Never schedule something you haven't watched work once.

```powershell
cd C:\edge_scanners
.\start_dashboard.bat
```

You should see uvicorn start: `Uvicorn running on http://0.0.0.0:8787`.
Leave that window open — closing it stops the server.

1. On the mini PC, open a browser → **http://localhost:8787**
2. Within ~1–2 minutes the first scan completes: the regime rail at the top
   fills in (RISK-ON / STANDING DOWN), the quote tape appears if Tradier is
   configured, and signals (or the "no signals" message — equally valid)
   populate the feed.
3. Check metrics: **http://localhost:8787/metrics** should show plain text
   beginning with lines like `scanner_signals{scanner="PREMIUM"} ...`
4. Test the daily batch too. In a SECOND PowerShell window:
   ```powershell
   cd C:\edge_scanners
   .\run_daily_scan.bat
   type scans\*.log
   ```
   You should see scan output written to a dated log file.

If anything fails here, fix it now — see Troubleshooting at the bottom.
Press Ctrl+C in the server window to stop it when you're done testing.

## Part 5 — Firewall rule for LAN access (5 min, optional)

Only needed to open the board from your phone/workstation. Skip if you'll
only use the mini PC's own screen.

1. Open PowerShell **as Administrator** (Win+X → Terminal (Admin)).
2. ```powershell
   New-NetFirewallRule -DisplayName "Edge Scanner Dashboard" `
     -Direction Inbound -LocalPort 8787 -Protocol TCP -Action Allow `
     -Profile Private
   ```
3. Find the mini PC's LAN address: `ipconfig` → look for **IPv4 Address**
   under your active adapter (e.g. `192.168.1.50`).
4. Make sure Windows considers your network **Private**: Settings → Network &
   internet → your connection → Network profile type → Private. (The rule is
   scoped to Private so the port is never open on untrusted networks.)
5. From your phone on the same Wi-Fi: `http://192.168.1.50:8787`.

Never port-forward 8787 (or 3000) on your router. These tools have no
authentication — they're LAN-only by design.

## Part 6 — Auto-start the dashboard at boot (10 min)

In an **Administrator** PowerShell:

```powershell
$action  = New-ScheduledTaskAction -Execute "C:\edge_scanners\start_dashboard.bat" `
           -WorkingDirectory "C:\edge_scanners"
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -RestartCount 3 `
            -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit 0
Register-ScheduledTask -TaskName "EdgeScannerDashboard" -Action $action `
  -Trigger $trigger -Settings $settings -RunLevel Limited
```

Then the daily 5:30 PM scan:

```powershell
$action  = New-ScheduledTaskAction -Execute "C:\edge_scanners\run_daily_scan.bat" `
           -WorkingDirectory "C:\edge_scanners"
$trigger = New-ScheduledTaskTrigger -Daily -At 5:30PM
Register-ScheduledTask -TaskName "EdgeScannerDaily" -Action $action -Trigger $trigger
```

Test without rebooting: open **Task Scheduler** (search in Start menu) →
Task Scheduler Library → right-click **EdgeScannerDashboard** → **Run** →
confirm http://localhost:8787 loads. Stop it (right-click → End) and let the
boot trigger own it from now on, or just leave it running.

## Part 7 — Keep the box awake (2 min)

Settings → System → Power (& battery) → Screen and sleep:
- "When plugged in, put my device to sleep after" → **Never**

Screen sleep is fine; machine sleep kills the server. Optional but smart on a
trading appliance: in the old Control Panel → Power Options → choose what the
power button does → enable "Restart automatically" behaviors are defaults;
also consider BIOS "Restore AC Power Loss → Power On" so the box self-recovers
after an outage.

## Part 8 — Prometheus (15 min)

1. Browser → **prometheus.io/download** → under the *prometheus* section
   download `prometheus-X.Y.Z.windows-amd64.zip`.
2. Extract it, and rename/move the extracted folder so the binary lives at
   `C:\prometheus\prometheus.exe`.
3. Replace the default config: copy `C:\edge_scanners\prometheus.yml` over
   `C:\prometheus\prometheus.yml` (overwrite when asked).
4. Test run in PowerShell:
   ```powershell
   C:\prometheus\prometheus.exe --config.file=C:\prometheus\prometheus.yml
   ```
5. Browser → **http://localhost:9090/targets** — you should see
   `edge_scanners` and `prometheus` both **UP** (edge_scanners requires the
   dashboard to be running).
6. Ctrl+C to stop, then register it to auto-start (Admin PowerShell):
   ```powershell
   $action = New-ScheduledTaskAction -Execute "C:\prometheus\prometheus.exe" `
     -Argument "--config.file=C:\prometheus\prometheus.yml --storage.tsdb.retention.time=90d" `
     -WorkingDirectory "C:\prometheus"
   $trigger = New-ScheduledTaskTrigger -AtStartup
   $settings = New-ScheduledTaskSettingsSet -RestartCount 3 `
     -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit 0
   Register-ScheduledTask -TaskName "Prometheus" -Action $action `
     -Trigger $trigger -Settings $settings
   ```
7. Task Scheduler → right-click **Prometheus** → Run → re-check
   http://localhost:9090/targets.

## Part 9 — Grafana (15 min)

1. Browser → **grafana.com/grafana/download?platform=windows** → choose the
   **OSS** edition → download the **.msi installer**.
2. Run it, accept defaults. The installer registers Grafana as a **Windows
   service** — it starts now and on every boot with zero extra work.
3. Browser → **http://localhost:3000** → log in `admin` / `admin` → set a new
   password when prompted.
4. Add the data source: left menu → **Connections → Data sources → Add data
   source → Prometheus** → set URL to `http://localhost:9090` → scroll down →
   **Save & test** → should say it's working.
5. Import the dashboard: left menu → **Dashboards → New → Import → Upload
   dashboard JSON file** → pick `C:\edge_scanners\grafana_dashboard.json` →
   select your Prometheus data source in the dropdown → **Import**.
6. You should see: two regime stats, "Minutes Since Last Scan", an error
   counter, signals-per-scan over time, and scan duration p50/p95. Panels need
   a scan or two of history before they show lines — give it 10 minutes.

Optional LAN access for Grafana, same pattern as Part 5 (Admin PowerShell):
```powershell
New-NetFirewallRule -DisplayName "Grafana" -Direction Inbound `
  -LocalPort 3000 -Protocol TCP -Action Allow -Profile Private
```

## Part 10 — Final verification checklist (5 min)

Reboot the mini PC, wait two minutes, then from the mini PC's browser:

- [ ] http://localhost:8787 — signal board loads, regime rail populated
- [ ] http://localhost:8787/metrics — text metrics render
- [ ] http://localhost:9090/targets — both targets UP
- [ ] http://localhost:3000 — Grafana loads, panels filling in
- [ ] From your phone (if Part 5 done): http://<mini-pc-ip>:8787 loads
- [ ] Tomorrow after 5:30 PM: `C:\edge_scanners\scans\` has today's log

All checked → the appliance is done. From here your daily loop is: glance at
the board, verify any signal against news/earnings, and place chosen trades
yourself in Fidelity.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `'python' is not recognized` | Re-run installer → Modify → check "Add to PATH", or use `py` instead of `python` |
| `Activate.ps1 cannot be loaded` | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, retry |
| Dashboard starts then exits instantly | Run `start_dashboard.bat` from a PowerShell window (not double-click) to see the error text |
| `TRADIER_TOKEN not set` in logs | Set the env var (Part 3), then fully restart the process/task — old processes don't see new vars |
| Board empty, no quote tape | Tradier token missing/invalid → falls back to yfinance (no tape, delayed bars). Check token, restart |
| 401 errors from Tradier | Wrong token, or sandbox token with `TRADIER_ENV=prod`. Match token to environment |
| Unreachable from phone | Firewall rule missing, network profile set to Public, or wrong IP — recheck Part 5 |
| Prometheus target DOWN | Dashboard not running, or scan loop crashed — check the dashboard task in Task Scheduler |
| Grafana panels say "No data" | Data source URL wrong (must be `http://localhost:9090`), or Prometheus has <2 scrapes of history — wait a minute |
| yfinance exceptions | `pip install --upgrade yfinance` inside the venv — their endpoints shift occasionally |
| Everything dead after reboot | Task Scheduler → check Last Run Result of each task; run each manually to see errors |
