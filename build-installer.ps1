$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

$packagePython = ".\.venv-package\Scripts\python.exe"
if (-not (Test-Path $packagePython)) { $packagePython = ".\.venv\Scripts\python.exe" }
& $packagePython -m PyInstaller --noconfirm --clean "Marketor.spec"
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }

$isccCandidates = @(
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
)
$iscc = $isccCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup 6 was not found." }

& $iscc ".\installer\Marketor.iss"
if ($LASTEXITCODE -ne 0) { throw "Installer build failed." }

Write-Host "Installer created: installer-output\Marketor-Setup-0.13.0.exe"
