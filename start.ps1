[CmdletBinding()]
param([switch]$Demo, [switch]$Doctor, [string]$Room)
$ErrorActionPreference = 'Stop'
$VenvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $VenvPython)) { throw 'Run .\scripts\setup.ps1 first.' }
$Arguments = @('-X', 'utf8', '-m', 'kaka')
if ($Demo) { $Arguments += '--demo' }
if ($Doctor) { $Arguments += '--doctor' }
if ($Room) { $Arguments += @('--room', $Room) }
Push-Location $PSScriptRoot
try {
    & $VenvPython @Arguments
    $Result = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $Result
