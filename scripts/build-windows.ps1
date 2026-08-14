#requires -Version 5.1
# Build an unsigned YazSes installer on Windows.
#
# Steps:
#   1. uv sync (env-markered deps pull pywin32, pystray, Pillow)
#   2. Install PyInstaller (build-only)
#   3. Run PyInstaller against packaging/windows/yazses.spec → dist/YazSes/
#   4. Run Inno Setup against packaging/windows/installer.iss → dist/YazSes-<v>-windows-<arch>.exe
#
# Outputs:
#   dist/YazSes-<version>-windows-<arch>.exe   (arch = x64 | arm64)
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

# --- target architecture -------------------------------------------------
# PyInstaller freezes for the machine it runs on -- it does not cross-compile --
# so the build host's architecture IS the target, and the runner label is what
# selects it. Derived rather than hardcoded so an arm64 runner produces an arm64
# installer with no second script. PROCESSOR_ARCHITECTURE is "ARM64" on native
# ARM; under x86 emulation Windows sets PROCESSOR_ARCHITEW6432 instead, so check
# both rather than silently mislabelling an emulated build.
$RawArch = if ($env:PROCESSOR_ARCHITEW6432) { $env:PROCESSOR_ARCHITEW6432 } else { $env:PROCESSOR_ARCHITECTURE }
$Arch = if ($RawArch -eq "ARM64") { "arm64" } else { "x64" }
$env:YAZSES_ARCH = $Arch
Write-Host "==> Building YazSes $Version for windows-$Arch (host reports $RawArch)"

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

# --- brand icon ---------------------------------------------------------
# Checked here, not after the ~10-minute PyInstaller run. The spec now refuses to
# build without it; this just makes the failure arrive in two seconds.
if (-not (Test-Path "assets\yazses.ico")) {
    Write-Error "assets\yazses.ico is missing. Run: uv run python scripts/gen-icons.py"
}

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

if (-not (Test-Path "dist\YazSes\YazSesApp.exe")) {
    Write-Error "PyInstaller did not produce dist\YazSes\YazSesApp.exe"
}
# The windowed binary must not case-fold onto `yazses`: PATHEXT resolves .EXE
# before .CMD, so a YazSes.exe here would shadow the yazses.cmd shim and every
# CLI command would reach a binary with no stdout.
if (Test-Path "dist\YazSes\yazses.exe") {
    Write-Error "dist\YazSes\yazses.exe shadows the yazses.cmd shim on PATH"
}
# The console binary is what makes `yazses doctor` able to print at all; a spec
# edit that drops it would otherwise surface only as silent CLI output on a
# user's machine.
if (-not (Test-Path "dist\YazSes\yazses-cli.exe")) {
    Write-Error "PyInstaller did not produce dist\YazSes\yazses-cli.exe (console CLI)"
}

# Prove the exe carries OUR icon, not PyInstaller's default. "An icon exists" is
# not the assertion that matters -- the generic one is an icon too, and shipping
# it is exactly the bug this check exists to prevent. Sample the badge at bottom
# centre (0.5w, 0.92h): that point is clear of the "Y" and falls in the gap
# between the two middle sound-wave bars, so it is brand purple in every frame.
Add-Type -AssemblyName System.Drawing -ErrorAction SilentlyContinue
try {
    $exe = (Resolve-Path "dist\YazSes\YazSesApp.exe").Path
    $bmp = [System.Drawing.Icon]::ExtractAssociatedIcon($exe).ToBitmap()
    $px  = $bmp.GetPixel([int]($bmp.Width * 0.5), [int]($bmp.Height * 0.92))
    if ($px.B -lt 120 -or ($px.B - $px.R) -lt 40 -or ($px.B - $px.G) -lt 40) {
        Write-Error ("YazSesApp.exe does not carry the YazSes mark (sampled R={0} G={1} B={2}). " -f $px.R, $px.G, $px.B)
    }
    Write-Host "  ok  brand icon resource present in YazSesApp.exe"
} catch [System.Management.Automation.RuntimeException] {
    # System.Drawing needs the Windows Desktop runtime, which the arm64 runner
    # may lack. A missing probe must not fail an otherwise good build.
    Write-Host "  --  icon probe unavailable on this host: $($_.Exception.Message)"
}

# --- Inno Setup ---------------------------------------------------------
Write-Host "==> Running Inno Setup"
& $Iscc "/Qp" "packaging\windows\installer.iss"

$Out = "dist\YazSes-$Version-windows-$Arch.exe"
if (-not (Test-Path $Out)) {
    Write-Error "Inno Setup did not produce $Out"
}

Write-Host "==> Done: $Out"
Get-Item $Out | Format-Table Name, Length, LastWriteTime
