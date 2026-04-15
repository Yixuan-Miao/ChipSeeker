$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

Write-Host "[setup] project root: $projectRoot"

python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m playwright install chromium

if (-not (Test-Path -LiteralPath "config.local.json")) {
    Copy-Item -LiteralPath "config.example.json" -Destination "config.local.json"
    Write-Host "[setup] created config.local.json from template"
}

foreach ($path in @(
    "local_data",
    "local_data\\sources",
    "local_data\\sources\\manual",
    "local_data\\sources\\generated_exports",
    "local_data\\cache",
    "local_data\\exports",
    "local_data\\downloads",
    "local_data\\backups"
)) {
    if (-not (Test-Path -LiteralPath $path)) {
        New-Item -ItemType Directory -Path $path | Out-Null
    }
}

Write-Host "[setup] done"
Write-Host "[setup] next: streamlit run app.py"
