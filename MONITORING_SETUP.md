# Monitoring Setup — Prometheus + Grafana on the Mini PC

Self-contained observability for the scanner box. Nothing here talks to
darth-rawsejet; this stack monitors only the mini PC itself. Native Windows
binaries, no Docker — fewer moving parts on an appliance.

## 1. Update the scanner app

```powershell
cd C:\edge_scanners
.\.venv\Scripts\Activate.ps1
pip install prometheus_client
```

Restart the dashboard. Verify http://localhost:8787/metrics shows
`scanner_signals`, `scanner_regime_on`, etc.

## 2. Prometheus

1. Download the latest `prometheus-X.Y.Z.windows-amd64.zip` from
   https://prometheus.io/download/ and extract to `C:\prometheus`.
2. Replace `C:\prometheus\prometheus.yml` with the `prometheus.yml` from this
   folder (it scrapes the scanner app on :8787 and itself on :9090).
3. Test run: `C:\prometheus\prometheus.exe --config.file=C:\prometheus\prometheus.yml`
   then open http://localhost:9090/targets — both targets should be UP.
4. Auto-start (admin PowerShell):

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

90-day retention at 30s scrape on a handful of series is trivially small —
well under 1 GB.

## 3. Grafana

1. Download the Grafana OSS **Windows installer** (.msi) from
   https://grafana.com/grafana/download?platform=windows — the installer
   registers Grafana as a Windows service automatically, so it survives
   reboots with no Task Scheduler work.
2. Open http://localhost:3000 (default admin/admin, change on first login).
3. Connections → Data sources → Add → Prometheus → URL `http://localhost:9090`
   → Save & test.
4. Dashboards → New → Import → upload `grafana_dashboard.json` from this
   folder. Pick the Prometheus data source when prompted.

You get: regime status stats (mirrors the signal board's rail), minutes since
last scan (alerts you when the pipeline silently dies — the most common
failure mode of homelab cron-style jobs), error counters, signals-per-scan
time series, and scan duration p50/p95.

## 4. Optional: host metrics

For CPU/RAM/disk/temps of the mini PC itself, install windows_exporter
(https://github.com/prometheus-community/windows_exporter, .msi runs as a
service on :9182), then uncomment the `windows` job in prometheus.yml and
restart Prometheus.

## 5. LAN access (optional)

Same pattern as the signal board — Grafana from your phone needs an inbound
rule, scoped to Private profile:

```powershell
New-NetFirewallRule -DisplayName "Grafana" -Direction Inbound `
  -LocalPort 3000 -Protocol TCP -Action Allow -Profile Private
```

Prometheus (:9090) generally doesn't need LAN exposure — Grafana queries it
locally. Leave it closed.

## What to watch in week one

- **Minutes Since Last Scan** is the canary. If it climbs past ~10 during
  market hours, the scan loop is stuck (rate limits, network, exception).
- **Signals per Scan** establishes your baseline. If PREMIUM goes from ~3/day
  to 0 for a week, either vol collapsed (real) or the data adapter broke
  (check errors panel) — the dashboard makes those distinguishable.
- **Scan duration p95** tells you if the universe is too big for the
  interval. If p95 approaches SCAN_INTERVAL, scans start overlapping their
  schedule — trim the universe or raise the interval.
