$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

function Write-Step([string]$message) {
    Write-Host "[setup] $message"
}

function Get-BootstrapPython {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        return @("py", "-3")
    }
    if (Get-Command python -ErrorAction SilentlyContinue) {
        return @("python")
    }
    throw "Python 3.10+ was not found. Install Python first, then rerun Install_ChipSeeker.bat."
}

Write-Step "project root: $projectRoot"

$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPython)) {
    $bootstrapPython = Get-BootstrapPython
    Write-Step "creating virtual environment at .venv"
    if ($bootstrapPython.Length -gt 1) {
        & $bootstrapPython[0] $bootstrapPython[1] -m venv .venv
    } else {
        & $bootstrapPython[0] -m venv .venv
    }
} else {
    Write-Step "reusing existing virtual environment"
}

if (-not (Test-Path -LiteralPath $venvPython)) {
    throw "Virtual environment creation failed. Expected .venv\\Scripts\\python.exe to exist."
}

Write-Step "upgrading pip / setuptools / wheel"
& $venvPython -m pip install --upgrade pip setuptools wheel

Write-Step "installing runtime requirements"
& $venvPython -m pip install -r requirements.txt

if (Test-Path -LiteralPath "requirements-optional.txt") {
    Write-Step "installing optional quality-of-life requirements"
    & $venvPython -m pip install -r requirements-optional.txt
}

Write-Step "installing Playwright Chromium runtime"
& $venvPython -m playwright install chromium

if (-not (Test-Path -LiteralPath "config.local.json")) {
    Copy-Item -LiteralPath "config.example.json" -Destination "config.local.json"
    Write-Step "created config.local.json from template"
}

foreach ($path in @(
    "demo_data",
    "local_data",
    "local_data\\sources",
    "local_data\\sources\\manual",
    "local_data\\sources\\generated_exports",
    "local_data\\cache",
    "local_data\\exports",
    "local_data\\exports\\content_packs",
    "local_data\\downloads",
    "local_data\\backups"
)) {
    if (-not (Test-Path -LiteralPath $path)) {
        New-Item -ItemType Directory -Path $path | Out-Null
    }
}

Write-Step "installation complete"
Write-Step "launch with Start_ChipSeeker.bat or .venv\\Scripts\\python.exe -m streamlit run app.py"
