$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

function Write-Step([string]$message) {
    Write-Host "[setup] $message"
}

function New-BootstrapCandidate([string]$name, [string]$command, [string[]]$arguments) {
    return [PSCustomObject]@{
        Name      = $name
        Command   = $command
        Arguments = $arguments
    }
}

function Get-CommonPythonExecutablePaths {
    $patterns = @()
    if ($env:LocalAppData) {
        $patterns += (Join-Path $env:LocalAppData "Programs\Python\Python*\python.exe")
    }
    if ($env:ProgramFiles) {
        $patterns += (Join-Path $env:ProgramFiles "Python*\python.exe")
        $patterns += (Join-Path $env:ProgramFiles "Python Software Foundation\Python*\python.exe")
    }
    if ($env:ProgramFiles -and ${env:ProgramFiles(x86)}) {
        $patterns += (Join-Path ${env:ProgramFiles(x86)} "Python*\python.exe")
    }

    $paths = @()
    foreach ($pattern in $patterns) {
        $paths += Get-ChildItem -Path $pattern -File -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName
    }
    return $paths | Where-Object { $_ -and ($_ -notmatch '\\WindowsApps\\') } | Sort-Object -Unique
}

function Get-BootstrapPythonCandidates {
    $candidates = New-Object System.Collections.Generic.List[object]
    if (Get-Command py -ErrorAction SilentlyContinue) {
        $candidates.Add((New-BootstrapCandidate "py -3" "py" @("-3")))
    }
    if (Get-Command python -ErrorAction SilentlyContinue) {
        $candidates.Add((New-BootstrapCandidate "python" "python" @()))
    }
    if (Get-Command python3 -ErrorAction SilentlyContinue) {
        $candidates.Add((New-BootstrapCandidate "python3" "python3" @()))
    }
    foreach ($pythonPath in Get-CommonPythonExecutablePaths) {
        $candidateName = "python.exe ($pythonPath)"
        $candidates.Add((New-BootstrapCandidate $candidateName $pythonPath @()))
    }
    if ($candidates.Count -eq 0) {
        throw "Python 3.10+ was not found. Install Python first, then rerun Install_ChipSeeker.bat."
    }
    return $candidates
}

function Invoke-ExternalCommand([string]$command, [string[]]$arguments, [string]$failureMessage) {
    & $command @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$failureMessage (exit code $LASTEXITCODE)."
    }
}

function Resolve-VenvPythonPath([string]$projectRoot) {
    $windowsPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $windowsPath) {
        return $windowsPath
    }
    $unixPath = Join-Path $projectRoot ".venv\bin\python"
    if (Test-Path -LiteralPath $unixPath) {
        return $unixPath
    }
    return $windowsPath
}

function Test-BootstrapCandidate($candidate) {
    try {
        Invoke-ExternalCommand $candidate.Command ($candidate.Arguments + @("--version")) "Failed to query Python version with $($candidate.Name)"
        return $true
    } catch {
        Write-Warning "[setup] bootstrap candidate failed: $($candidate.Name) :: $($_.Exception.Message)"
        return $false
    }
}

function Install-PythonWithWinget {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Write-Warning "[setup] winget was not found, so Python cannot be auto-installed."
        return $false
    }

    Write-Step "no usable Python launcher found; attempting to install Python 3.11 via winget"
    try {
        Invoke-ExternalCommand "winget" @(
            "install",
            "--id", "Python.Python.3.11",
            "-e",
            "--accept-package-agreements",
            "--accept-source-agreements"
        ) "Failed to install Python with winget"
        return $true
    } catch {
        Write-Warning "[setup] automatic Python installation failed :: $($_.Exception.Message)"
        return $false
    }
}

function Get-WorkingBootstrapPythonCandidates {
    $working = New-Object System.Collections.Generic.List[object]
    foreach ($candidate in Get-BootstrapPythonCandidates) {
        if (Test-BootstrapCandidate $candidate) {
            $working.Add($candidate)
        }
    }

    if ($working.Count -gt 0) {
        return $working
    }

    if (Install-PythonWithWinget) {
        foreach ($candidate in Get-BootstrapPythonCandidates) {
            if (Test-BootstrapCandidate $candidate) {
                $working.Add($candidate)
            }
        }
    }

    return $working
}

function New-ProjectVenv([string]$projectRoot) {
    $venvPath = Join-Path $projectRoot ".venv"
    $lastError = $null
    $workingCandidates = Get-WorkingBootstrapPythonCandidates
    if ($workingCandidates.Count -eq 0) {
        throw "Virtual environment creation failed because no usable Python 3 launcher was found. Install Python 3.10+ manually, then rerun Install_ChipSeeker.bat."
    }

    foreach ($candidate in $workingCandidates) {
        Write-Step "trying bootstrap python: $($candidate.Name)"
        try {
            Invoke-ExternalCommand $candidate.Command ($candidate.Arguments + @("-m", "venv", $venvPath)) "Failed to create virtual environment with $($candidate.Name)"
            $resolvedPython = Resolve-VenvPythonPath $projectRoot
            if (Test-Path -LiteralPath $resolvedPython) {
                Write-Step "virtual environment created with $($candidate.Name)"
                return
            }
            throw "Virtual environment command finished but Python executable was not created at $resolvedPython"
        } catch {
            $lastError = $_
            Write-Warning "[setup] venv creation failed: $($candidate.Name) :: $($_.Exception.Message)"
        }
    }
    throw "Virtual environment creation failed after trying all detected Python launchers. Last error: $($lastError.Exception.Message)"
}

Write-Step "project root: $projectRoot"

$venvPython = Resolve-VenvPythonPath $projectRoot
if (-not (Test-Path -LiteralPath $venvPython)) {
    Write-Step "creating virtual environment at .venv"
    New-ProjectVenv $projectRoot
    $venvPython = Resolve-VenvPythonPath $projectRoot
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
