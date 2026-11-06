[CmdletBinding()]
param([switch]$DemoOnly, [switch]$Dev)
$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot

function Check-Exit([string]$Step) {
    if ($LASTEXITCODE -ne 0) { throw "$Step failed (exit $LASTEXITCODE)." }
}

Push-Location $ProjectRoot
try {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        $PythonCommand = 'py'
        $PythonArguments = @('-3')
    } elseif (Get-Command python -ErrorAction SilentlyContinue) {
        $PythonCommand = 'python'
        $PythonArguments = @()
    } else {
        throw 'Install 64-bit Python 3.11+ from python.org, then reopen your terminal.'
    }
    & $PythonCommand @PythonArguments -c "import sys,struct; assert sys.version_info >= (3,11) and struct.calcsize('P') == 8, 'Python 3.11+ 64-bit required'"
    Check-Exit 'Python check'
    & $PythonCommand @PythonArguments -m venv .venv
    Check-Exit 'Virtual environment'
    $VenvPython = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
    $Target = if ($Dev) { '.[dev]' } else { '.' }
    & $VenvPython -m pip install -e $Target
    Check-Exit 'Dependencies'

    if (-not $DemoOnly) {
        if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw 'Git for Windows is required.' }
        $EngineLock = Get-Content -Raw 'engine.lock.json' | ConvertFrom-Json
        $EnginePath = Join-Path $ProjectRoot '.engine\nichirin'
        if (-not (Test-Path $EnginePath)) {
            New-Item -ItemType Directory -Force (Split-Path -Parent $EnginePath) | Out-Null
            git clone --depth 1 $EngineLock.repository $EnginePath
            Check-Exit 'Engine clone'
        }
        $Origin = git -C $EnginePath remote get-url origin
        Check-Exit 'Engine origin'
        if ($Origin.Trim() -ne $EngineLock.repository) { throw 'Unexpected engine remote; existing checkout left untouched.' }
        $Dirty = git -C $EnginePath status --porcelain
        Check-Exit 'Engine working tree'
        if ($Dirty) { throw 'Engine has local changes; preserve them before rerunning setup.' }
        git -C $EnginePath fetch --depth 1 origin $EngineLock.revision
        Check-Exit 'Engine fetch'
        git -C $EnginePath checkout --detach $EngineLock.revision
        Check-Exit 'Engine checkout'
        $Head = git -C $EnginePath rev-parse HEAD
        Check-Exit 'Engine revision'
        if ($Head.Trim() -ne $EngineLock.revision) { throw 'Engine revision verification failed.' }
    }
    Write-Host 'Ready. Demo: .\start.ps1 -Demo | Live: .\start.ps1 | Check: .\start.ps1 -Doctor'
} finally {
    Pop-Location
}
