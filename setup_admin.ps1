# setup_admin.ps1 — one-shot elevated setup for the Edge Scanner appliance.
# Covers guide Parts 5 (firewall), 6 (scheduled tasks), 7 (power), 8 step 6
# (Prometheus task), and 9 (Grafana install + firewall). Logs everything to
# setup_admin.log so the non-elevated session can verify results.

$ErrorActionPreference = 'Continue'
Start-Transcript -Path 'C:\edge_scanners\setup_admin.log' -Force

function Step($name, [scriptblock]$block) {
    Write-Host "=== $name ==="
    try { & $block; Write-Host "OK: $name" }
    catch { Write-Host "FAIL: $name -- $($_.Exception.Message)" }
}

Step 'Part 5: Firewall rule 8787 (dashboard, Private only)' {
    if (-not (Get-NetFirewallRule -DisplayName 'Edge Scanner Dashboard' -ErrorAction SilentlyContinue)) {
        New-NetFirewallRule -DisplayName 'Edge Scanner Dashboard' `
            -Direction Inbound -LocalPort 8787 -Protocol TCP -Action Allow `
            -Profile Private | Out-Null
    } else { Write-Host 'already exists' }
}

Step 'Part 9: Firewall rule 3000 (Grafana, Private only)' {
    if (-not (Get-NetFirewallRule -DisplayName 'Grafana' -ErrorAction SilentlyContinue)) {
        New-NetFirewallRule -DisplayName 'Grafana' -Direction Inbound `
            -LocalPort 3000 -Protocol TCP -Action Allow -Profile Private | Out-Null
    } else { Write-Host 'already exists' }
}

Step 'Part 6: EdgeScannerDashboard task (at startup)' {
    $action  = New-ScheduledTaskAction -Execute 'C:\edge_scanners\start_dashboard.bat' `
               -WorkingDirectory 'C:\edge_scanners'
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $settings = New-ScheduledTaskSettingsSet -RestartCount 3 `
                -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit 0
    Register-ScheduledTask -TaskName 'EdgeScannerDashboard' -Action $action `
        -Trigger $trigger -Settings $settings -RunLevel Limited -Force | Out-Null
}

Step 'Part 6: EdgeScannerDaily task (5:30 PM)' {
    $action  = New-ScheduledTaskAction -Execute 'C:\edge_scanners\run_daily_scan.bat' `
               -WorkingDirectory 'C:\edge_scanners'
    $trigger = New-ScheduledTaskTrigger -Daily -At 5:30PM
    Register-ScheduledTask -TaskName 'EdgeScannerDaily' -Action $action `
        -Trigger $trigger -Force | Out-Null
}

Step 'Part 8: Prometheus task (at startup, 90d retention)' {
    $action = New-ScheduledTaskAction -Execute 'C:\prometheus\prometheus.exe' `
        -Argument '--config.file=C:\prometheus\prometheus.yml --storage.tsdb.retention.time=90d' `
        -WorkingDirectory 'C:\prometheus'
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $settings = New-ScheduledTaskSettingsSet -RestartCount 3 `
        -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit 0
    Register-ScheduledTask -TaskName 'Prometheus' -Action $action `
        -Trigger $trigger -Settings $settings -Force | Out-Null
}

Step 'Part 7: Never sleep when plugged in' {
    powercfg /change standby-timeout-ac 0
    powercfg /change hibernate-timeout-ac 0
}

Step 'Part 9: Install Grafana MSI (silent, several minutes)' {
    $msi = 'C:\Users\Teja\AppData\Local\Temp\grafana.msi'
    $p = Start-Process msiexec.exe -ArgumentList "/i `"$msi`" /qn /norestart /l*v C:\edge_scanners\grafana_install.log" -Wait -PassThru
    Write-Host "msiexec exit code: $($p.ExitCode)"
    if ($p.ExitCode -ne 0) { throw "msiexec exited $($p.ExitCode)" }
}

Step 'Start tasks now (test without reboot)' {
    Start-ScheduledTask -TaskName 'EdgeScannerDashboard'
    Start-ScheduledTask -TaskName 'Prometheus'
}

Write-Host '=== Final state ==='
Get-ScheduledTask -TaskName 'EdgeScannerDashboard','EdgeScannerDaily','Prometheus' |
    Format-Table TaskName, State -AutoSize
Get-Service grafana* | Format-Table Name, Status, StartType -AutoSize
Stop-Transcript
