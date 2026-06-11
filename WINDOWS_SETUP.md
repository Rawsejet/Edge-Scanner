# Windows Mini PC Setup

The scanner suite is pure Python — it runs identically on Windows. This guide
gets it running as an always-on service on the mini PC, with the dashboard
reachable from your phone/workstation on the LAN.

## 1. Install Python

Grab Python 3.12+ from python.org (not the Microsoft Store build — it
sandboxes paths in annoying ways). During install, check **"Add python.exe to
PATH"**.

## 2. Set up the project

Open PowerShell in the folder where you copied `edge_scanners\`:

```powershell
cd C:\edge_scanners
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install fastapi uvicorn requests pandas numpy yfinance
```

If activation is blocked: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`
once, then retry.

## 3. Set the Tradier token (persistent, user-level)

```powershell
[Environment]::SetEnvironmentVariable("TRADIER_TOKEN", "YOUR_TOKEN", "User")
[Environment]::SetEnvironmentVariable("TRADIER_ENV", "prod", "User")
```

Close and reopen PowerShell so new processes pick it up. Keep the token out of
files/scripts — it lives in your user environment only.

## 4. Run it

```powershell
.\start_dashboard.bat
```

Dashboard: http://localhost:8787 on the mini PC. From other devices use the
mini PC's LAN IP, e.g. http://192.168.1.50:8787 (find it with `ipconfig`).

## 5. Open the firewall for LAN access (admin PowerShell, once)

```powershell
New-NetFirewallRule -DisplayName "Edge Scanner Dashboard" `
  -Direction Inbound -LocalPort 8787 -Protocol TCP -Action Allow `
  -Profile Private
```

`-Profile Private` keeps it LAN-only — do not expose this port to the
internet; the dashboard has no auth by design because it's a private tool.

## 6. Auto-start with Task Scheduler

In an admin PowerShell:

```powershell
$action  = New-ScheduledTaskAction -Execute "C:\edge_scanners\start_dashboard.bat" `
           -WorkingDirectory "C:\edge_scanners"
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -RestartCount 3 `
            -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit 0
Register-ScheduledTask -TaskName "EdgeScannerDashboard" -Action $action `
  -Trigger $trigger -Settings $settings -RunLevel Limited
```

The daily end-of-day batch scan (optional, complements the live board):

```powershell
$action  = New-ScheduledTaskAction -Execute "C:\edge_scanners\run_daily_scan.bat" `
           -WorkingDirectory "C:\edge_scanners"
$trigger = New-ScheduledTaskTrigger -Daily -At 5:30PM   # after close, CT
Register-ScheduledTask -TaskName "EdgeScannerDaily" -Action $action -Trigger $trigger
```

## 7. Power settings (mini PC as appliance)

Settings → System → Power: set "When plugged in, put my device to sleep" to
**Never**. A sleeping PC serves no WebSockets. This is also exactly the
low-power always-on role you wanted to keep off the big dual-GPU box — a mini
PC idles at ~10W vs. the workstation's hundreds.

## Troubleshooting

- `'python' not recognized` → reinstall with Add-to-PATH checked, or use `py`.
- Dashboard unreachable from other devices → firewall rule missing, or the
  network is set to "Public" profile (change to Private in network settings).
- yfinance errors on first run → `pip install --upgrade yfinance`; their API
  shifts occasionally.
- Token not picked up by Task Scheduler → user-level env vars apply to tasks
  running as your user; confirm the task's "Run as" account is you.
