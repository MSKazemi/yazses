#requires -Version 5.1
# Build an unsigned YazSes installer on Windows.
#
# Steps:
#   1. uv sync (env-markered deps pull pywin32, pystray, Pillow)
#   2. Install PyInstaller (build-only)
#   3. Run PyInstaller against packaging/windows/yazses.spec → dist/YazSes/
#   4. Run Inno Setup against packaging/windows/installer.iss → dist/YazSes-<v>-windows-x64.exe
#
# Outputs:
#   dist/YazSes-<version>-windows-x64.exe
#
# Requires: Windows, uv, Inno Setup 6 (preinstalled on GitHub windows-latest).

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepoRoot = (Resolve-Path "$PSScriptRoot/..").Path
Set-Location $RepoRoot

if (-not $IsWindows) {
    if ($env:OS -ne "Windows_NT") {
        Write-Error "build-windows.ps1 must run on Windows; detected $env:OS"
    }
}

# --- version from pyproject.toml ----------------------------------------
$pyproject = Get-Content -Raw -Path "pyproject.toml"
if ($pyproject -match '(?m)^version\s*=\s*"([^"]+)"') {
    $Version = $Matches[1]
} else {
    Write-Error "Could not locate version in pyproject.toml"
}
$env:YAZSES_VERSION = $Version
Write-Host "==> Building YazSes $Version"

# --- preflight ----------------------------------------------------------
function Require-Cmd($name) {
    if (-not (Get-Command $name -ErrorAction SilentlyContinue)) {
        Write-Error "$name not found on PATH."
    }
}
Require-Cmd uv

$IsccCandidates = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles}\Inno Setup 6\ISCC.exe"
)
$Iscc = $IsccCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Iscc) {
    Write-Error "Inno Setup 6 (ISCC.exe) not found. Install from https://jrsoftware.org/isinfo.php or `choco install innosetup`."
}
Write-Host "Using ISCC: $Iscc"

# --- sync runtime deps + add PyInstaller --------------------------------
Write-Host "==> Syncing runtime dependencies"
uv sync

Write-Host "==> Installing PyInstaller"
uv pip install "pyinstaller>=6.10"

# --- clean previous build ----------------------------------------------
Write-Host "==> Cleaning previous build"
Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue

# --- PyInstaller --------------------------------------------------------
Write-Host "==> Running PyInstaller"
uv run pyinstaller packaging\windows\yazses.spec --clean --noconfirm

if (-not (Test-Path "dist\YazSes\YazSes.exe")) {
    Write-Error "PyInstaller did not produce dist\YazSes\YazSes.exe"
}
# The console binary is what makes `yazses doctor` able to print at all; a spec
# edit that drops it would otherwise surface only as silent CLI output on a
# user's machine.
if (-not (Test-Path "dist\YazSes\yazses-cli.exe")) {
    Write-Error "PyInstaller did not produce dist\YazSes\yazses-cli.exe (console CLI)"
}

# --- Inno Setup ---------------------------------------------------------
Write-Host "==> Running Inno Setup"
& $Iscc "/Qp" "packaging\windows\installer.iss"

$Out = "dist\YazSes-$Version-windows-x64.exe"
if (-not (Test-Path $Out)) {
    Write-Error "Inno Setup did not produce $Out"
}

Write-Host "==> Done: $Out"
Get-Item $Out | Format-Table Name, Length, LastWriteTime
