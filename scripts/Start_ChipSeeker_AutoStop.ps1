param(
    [int]$Port = 8501,
    [string]$BrowserUrl = "http://localhost:8501",
    [string]$ServiceLabel = "ChipSeeker",
    [int]$IdleTimeoutSec = 8
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $projectRoot   # scripts/ -> project root
Set-Location $projectRoot

$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    Write-Host "[$ServiceLabel] ERROR: .venv not found. Run Install_ChipSeeker.bat first."
    exit 1
}

# ── 1. Check port is free ──────────────────────────────────────────
try {
    $occupied = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop | Select-Object -First 1
} catch {
    $occupied = $null
}

if ($occupied) {
    Write-Host "[$ServiceLabel] WARNING: Port $Port is already in use."
    Write-Host "[$ServiceLabel] It may be a leftover service. Attempting to kill..."
    Stop-Process -Id $occupied.OwningProcess -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
    try {
        $occupied = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop | Select-Object -First 1
    } catch { $occupied = $null }
    if ($occupied) {
        Write-Host "[$ServiceLabel] ERROR: Could not free port $Port. Stop manually (PID=$($occupied.OwningProcess)) and retry."
        pause
        exit 1
    }
}

# ── 2. Launch the service ──────────────────────────────────────────
Write-Host "[$ServiceLabel] Starting Streamlit on port $Port..."

$procInfo = New-Object System.Diagnostics.ProcessStartInfo
$procInfo.FileName = $venvPython
$procInfo.Arguments = "-m streamlit run app.py --server.port $Port --server.headless true"
$procInfo.WorkingDirectory = $projectRoot
$procInfo.UseShellExecute = $false
$procInfo.RedirectStandardOutput = $true
$procInfo.RedirectStandardError = $true
$procInfo.CreateNoWindow = $false

$serviceProc = New-Object System.Diagnostics.Process
$serviceProc.StartInfo = $procInfo

$cleanupDone = $false
function Invoke-Cleanup {
    if ($cleanupDone) { return }
    $cleanupDone = $true

    Write-Host ""
    Write-Host "[$ServiceLabel] Shutting down..." -ForegroundColor Yellow

    # 1. Kill the service process
    if ($serviceProc -and -not $serviceProc.HasExited) {
        Write-Host "[$ServiceLabel] Stopping service PID=$($serviceProc.Id)..."
        Stop-Process -Id $serviceProc.Id -Force -ErrorAction SilentlyContinue
        try { $serviceProc.WaitForExit(3000) } catch {}
    }

    # 2. Kill child processes
    if ($serviceProc) {
        $children = Get-CimInstance Win32_Process -Filter "ParentProcessId=$($serviceProc.Id)" -ErrorAction SilentlyContinue
        foreach ($child in $children) {
            Stop-Process -Id $child.ProcessId -Force -ErrorAction SilentlyContinue
        }
    }

    # 3. Kill anything still listening on the port
    try {
        $lingering = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
        foreach ($conn in $lingering) {
            Write-Host "[$ServiceLabel] Killing lingering listener on port $Port (PID=$($conn.OwningProcess))"
            Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue
        }
    } catch {}

    # 4. Kill streamlit orphans
    $orphans = Get-Process -Name "streamlit", "python" -ErrorAction SilentlyContinue |
        Where-Object { $_.MainWindowTitle -like "*Streamlit*" -or $_.MainWindowTitle -like "*ChipSeeker*" }
    foreach ($orphan in $orphans) {
        if ($orphan.Id -ne $serviceProc.Id) {
            Write-Host "[$ServiceLabel] Killing orphan: $($orphan.ProcessName) PID=$($orphan.Id)"
            Stop-Process -Id $orphan.Id -Force -ErrorAction SilentlyContinue
        }
    }

    Write-Host "[$ServiceLabel] All services stopped." -ForegroundColor Green
}

$null = $serviceProc.Start()

# ── 3. Wait for service ready ─────────────────────────────────────
$maxWait = 30
$waited = 0
do {
    Start-Sleep -Seconds 1
    $waited++
    if ($serviceProc.HasExited) {
        Write-Host "[$ServiceLabel] ERROR: Service exited prematurely (code $($serviceProc.ExitCode))"
        $errOutput = $serviceProc.StandardError.ReadToEnd()
        if ($errOutput) { Write-Host $errOutput }
        exit 1
    }
    try {
        $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop | Select-Object -First 1
    } catch { $listener = $null }
} while ((-not $listener) -and ($waited -lt $maxWait))

if (-not $listener) {
    Write-Host "[$ServiceLabel] ERROR: Service did not start within ${maxWait}s."
    Invoke-Cleanup
    exit 1
}

# ── 4. Open browser ───────────────────────────────────────────────
Start-Process $BrowserUrl

# ── 5. Monitor loop ───────────────────────────────────────────────
Write-Host "================================================================"
Write-Host "  $ServiceLabel is running at $BrowserUrl"
Write-Host "  Close browser -> auto-stop after ${IdleTimeoutSec}s idle"
Write-Host "  Press [Q] to stop manually, or close this window."
Write-Host "================================================================"

$idleSeconds = 0

try {
    while (-not $serviceProc.HasExited) {
        Start-Sleep -Seconds 1

        # Check for user key-press (Q to quit)
        if ([Console]::KeyAvailable) {
            $key = [Console]::ReadKey($true)
            if ($key.Key -eq 'Q') {
                Write-Host "Q pressed — shutting down by user request."
                break
            }
        }

        # Count active client TCP connections
        try {
            $totalClients = @(Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue |
                Where-Object { $_.State -eq 'Established' }).Count
        } catch { $totalClients = 0 }

        if ($totalClients -eq 0) {
            $idleSeconds++
            if ($idleSeconds -ge $IdleTimeoutSec) {
                Write-Host ""
                Write-Host "[$ServiceLabel] No browser connected for ${IdleTimeoutSec}s." -ForegroundColor Cyan
                Write-Host "[$ServiceLabel] Auto-stopping..." -ForegroundColor Cyan
                break
            }
        } else {
            $idleSeconds = 0
        }
    }
} finally {
    Invoke-Cleanup
}
