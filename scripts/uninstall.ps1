$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

function Write-Step([string]$message) {
    Write-Host "[uninstall] $message"
}

$targets = @(
    ".venv",
    "local_data",
    "config.local.json",
    ".pytest_cache"
)

Write-Step "project root: $projectRoot"
Write-Step "This will remove the local virtual environment and generated runtime data for this ChipSeeker workspace."

foreach ($relativePath in $targets) {
    $fullPath = Join-Path $projectRoot $relativePath
    if (-not (Test-Path -LiteralPath $fullPath)) {
        continue
    }

    Write-Step "removing $relativePath"
    $item = Get-Item -LiteralPath $fullPath -Force
    if ($item.PSIsContainer) {
        Remove-Item -LiteralPath $fullPath -Recurse -Force
    } else {
        Remove-Item -LiteralPath $fullPath -Force
    }
}

Write-Step "uninstall complete"
Write-Step "Removed: .venv, local_data, config.local.json, .pytest_cache (if they existed)."
