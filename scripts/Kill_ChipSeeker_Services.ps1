$ErrorActionPreference = "Continue"
Set-StrictMode -Version Latest

# ── Kill All ChipSeeker / Related Services ─────────────────────────
# Kills any process listening on ChipSeeker ports and any streamlit/uvicorn orphans.
# Useful for cleaning up after an unclean shutdown.

$ports = @(8501, 8010, 3000)
$killed = @()

Write-Host "ChipSeeker Service Cleanup" -ForegroundColor Cyan
Write-Host "=========================="
Write-Host ""

# 1. Kill by port
foreach ($port in $ports) {
    try {
        $conns = Get-NetTCPConnection -LocalPort $port -State Listen,Established -ErrorAction SilentlyContinue
        foreach ($conn in $conns) {
            $proc = Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue
            if ($proc) {
                Write-Host "  Port $port -> $($proc.ProcessName) PID=$($proc.Id)" -ForegroundColor Yellow
                Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
                $killed += "PID $($proc.Id) ($($proc.ProcessName)) on port $port"
            }
        }
    } catch {}
}

# 2. Kill streamlit processes
$streamlitProcs = Get-Process -Name "streamlit" -ErrorAction SilentlyContinue
foreach ($proc in $streamlitProcs) {
    Write-Host "  Streamlit orphan -> PID=$($proc.Id)" -ForegroundColor Yellow
    Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    $killed += "PID $($proc.Id) (streamlit orphan)"
}

# 3. Kill python processes with streamlit/uvicorn in command line
$pythonProcs = Get-CimInstance Win32_Process -Filter "Name LIKE '%python%'" -ErrorAction SilentlyContinue
foreach ($proc in $pythonProcs) {
    try {
        $cmd = $proc.CommandLine
        if ($cmd -and ($cmd -like "*streamlit*" -or $cmd -like "*uvicorn*" -or $cmd -like "*chipseeker*")) {
            Write-Host "  ChipSeeker Python -> PID=$($proc.ProcessId) Command=$cmd" -ForegroundColor Yellow
            Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
            $killed += "PID $($proc.ProcessId) (python: $($cmd.Substring(0, [Math]::Min(80, $cmd.Length))))"
        }
    } catch {}
}

# 4. Kill hidden PowerShell windows that were launched for background services
$psProcs = Get-CimInstance Win32_Process -Filter "Name = 'powershell.exe'" -ErrorAction SilentlyContinue
foreach ($proc in $psProcs) {
    try {
        $cmd = $proc.CommandLine
        if ($cmd -and ($cmd -like "*uvicorn*" -or $cmd -like "*demo_service*")) {
            Write-Host "  Hidden PowerShell (demo svc) -> PID=$($proc.ProcessId)" -ForegroundColor Yellow
            Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
            $killed += "PID $($proc.ProcessId) (hidden powershell demo svc)"
        }
    } catch {}
}

# 5. Clean up PID files (relative to this script's location)
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $projectRoot   # scripts/ -> project root
$demoRoot = Join-Path (Split-Path -Parent $projectRoot) "ChipSeeker-demo-private"

$pidFiles = @(
    (Join-Path $demoRoot "private_data\runtime\demo_app.pid"),
    (Join-Path $demoRoot "private_data\runtime\cloudflared.pid")
)
foreach ($pidFile in $pidFiles) {
    if (Test-Path $pidFile) {
        Write-Host "  Cleaning PID file: $pidFile"
        Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
    }
}

Write-Host ""
if ($killed.Count -eq 0) {
    Write-Host "No ChipSeeker services found running. All clean!" -ForegroundColor Green
} else {
    Write-Host "Cleaned up $($killed.Count) service(s):" -ForegroundColor Green
    foreach ($item in $killed) {
        Write-Host "  [OK] $item"
    }
}
Write-Host ""
Write-Host "Verification:" -ForegroundColor Cyan
foreach ($port in $ports) {
    try {
        $check = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($check) {
            Write-Host "  [!!] Port $port STILL in use (PID=$($check.OwningProcess))" -ForegroundColor Red
        } else {
            Write-Host "  [OK] Port $port is free" -ForegroundColor Green
        }
    } catch {
        Write-Host "  [OK] Port $port is free" -ForegroundColor Green
    }
}

pause
