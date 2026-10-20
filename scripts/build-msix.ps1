<#
.SYNOPSIS
    Build an unsigned MSIX package of YazSes for Microsoft Store submission.

.DESCRIPTION
    The Store signs MSIX packages itself during certification, so this produces an
    UNSIGNED .msix on purpose. That is not an oversight and must not be "fixed" by
    adding a self-signed certificate: a self-signed package is installable only on a
    machine that already trusts the certificate, and the Store re-signs anyway.

    Packages the PyInstaller COLLECT output (dist/YazSes) directly. Inno Setup is not
    involved -- MSIX carries its own install, uninstall and update semantics, so the
    .iss installer stays the artifact for the direct-download and winget/Chocolatey/
    Scoop channels while this one serves the Store.

    Identity values come from Partner Center and are NOT guessed here. The script
    refuses to emit a package whose manifest still contains a placeholder, because that
    failure would otherwise surface only at submission, long after the build looked fine.

.PARAMETER Version
    Three-part product version, e.g. 2.36.0. A fourth component of .0 is appended: the
    Store reserves the revision field and rejects a package that sets it.

.PARAMETER IdentityName
    Package/Identity/Name exactly as Partner Center shows it (e.g. 12345MSKazemi.YazSes).

.PARAMETER Publisher
    Package/Identity/Publisher exactly as Partner Center shows it (a CN=... string).

.PARAMETER PublisherDisplayName
    The publisher display name from Partner Center.

.PARAMETER Architecture
    x64 or arm64. Must match the PyInstaller output being packaged.

.EXAMPLE
    ./scripts/build-msix.ps1 -Version 2.36.0 -IdentityName 1234MSKazemi.YazSes `
        -Publisher "CN=ABCD1234-..." -PublisherDisplayName "Mohsen Seyedkazemi Ardebili"
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Version,
    [Parameter(Mandatory = $true)][string]$IdentityName,
    [Parameter(Mandatory = $true)][string]$Publisher,
    [Parameter(Mandatory = $true)][string]$PublisherDisplayName,
    [ValidateSet('x64', 'arm64')][string]$Architecture = 'x64'
)

$ErrorActionPreference = 'Stop'

$repo = Split-Path -Parent $PSScriptRoot
$payload = Join-Path $repo 'dist/YazSes'
$msixSrc = Join-Path $repo 'packaging/windows/msix'
$staging = Join-Path $repo 'build/msix'
$outDir = Join-Path $repo 'dist'
$outFile = Join-Path $outDir "YazSes-$Version-windows-$Architecture.msix"

# --- Preconditions, each naming its own fix -------------------------------------------

if (-not (Test-Path $payload)) {
    throw "PyInstaller output not found at $payload. Run ./scripts/build-windows.ps1 first."
}
$appExe = Join-Path $payload 'YazSesApp.exe'
if (-not (Test-Path $appExe)) {
    # The manifest's Application/@Executable must exist inside the package or makeappx
    # succeeds and the Store rejects it. Check here, where the message can be useful.
    throw "YazSesApp.exe is missing from $payload. The manifest's Executable attribute names it."
}

if ($Version -notmatch '^\d+\.\d+\.\d+$') {
    throw "Version must be three-part, e.g. 2.36.0 (got '$Version'). The .0 revision is appended."
}
$msixVersion = "$Version.0"

# makeappx.exe ships with the Windows SDK and is not on PATH by default.
$makeappx = Get-Command makeappx.exe -ErrorAction SilentlyContinue
if (-not $makeappx) {
    $sdkRoot = 'C:/Program Files (x86)/Windows Kits/10/bin'
    if (Test-Path $sdkRoot) {
        $found = Get-ChildItem -Path $sdkRoot -Recurse -Filter 'makeappx.exe' -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -match [regex]::Escape($Architecture) -or $_.FullName -match 'x64' } |
            Select-Object -First 1
        if ($found) { $makeappx = $found.FullName }
    }
} else {
    $makeappx = $makeappx.Source
}
if (-not $makeappx) {
    throw "makeappx.exe not found. Install the Windows 10/11 SDK, or add it to PATH."
}
Write-Host "Using makeappx: $makeappx"

# --- Stage the payload beside the manifest and assets ---------------------------------

if (Test-Path $staging) { Remove-Item -Recurse -Force $staging }
New-Item -ItemType Directory -Force -Path $staging | Out-Null

Copy-Item -Path (Join-Path $payload '*') -Destination $staging -Recurse -Force
Copy-Item -Path (Join-Path $msixSrc 'Assets') -Destination $staging -Recurse -Force

# --- Substitute identity, then prove nothing was left behind --------------------------

$manifest = Get-Content (Join-Path $msixSrc 'AppxManifest.xml') -Raw
$manifest = $manifest.Replace('__IDENTITY_NAME__', $IdentityName)
$manifest = $manifest.Replace('__PUBLISHER__', $Publisher)
$manifest = $manifest.Replace('__PUBLISHER_DISPLAY_NAME__', $PublisherDisplayName)
$manifest = $manifest.Replace('__VERSION__', $msixVersion)
$manifest = $manifest.Replace('__ARCHITECTURE__', $Architecture)

# The whole point of the placeholder scheme: a miss must stop the build, not ship.
$leftover = [regex]::Matches($manifest, '__[A-Z_]+__') | ForEach-Object { $_.Value } | Sort-Object -Unique
if ($leftover) {
    throw "Manifest still contains placeholders after substitution: $($leftover -join ', '). " +
          "These come from Partner Center and cannot be guessed; a package built with them " +
          "would be rejected at submission."
}

$manifestPath = Join-Path $staging 'AppxManifest.xml'
# UTF-8 without BOM. A BOM before the XML declaration makes makeappx reject the manifest.
[System.IO.File]::WriteAllText($manifestPath, $manifest, (New-Object System.Text.UTF8Encoding($false)))

# Every logo the manifest names must be present, or the package fails certification
# rather than the build. Checking here keeps the failure close to the cause.
$missing = @()
foreach ($m in [regex]::Matches($manifest, 'Assets\\([A-Za-z0-9]+\.png)')) {
    $logo = Join-Path $staging ('Assets/' + $m.Groups[1].Value)
    if (-not (Test-Path $logo)) { $missing += $m.Groups[1].Value }
}
if ($missing) {
    throw "Manifest names logos that are not in Assets/: $($missing -join ', '). Run 'make icons'."
}

# --- Pack ------------------------------------------------------------------------------

New-Item -ItemType Directory -Force -Path $outDir | Out-Null
if (Test-Path $outFile) { Remove-Item -Force $outFile }

& $makeappx pack /d $staging /p $outFile /o
if ($LASTEXITCODE -ne 0) { throw "makeappx pack failed with exit code $LASTEXITCODE" }

$size = (Get-Item $outFile).Length
Write-Host ""
Write-Host "Built $outFile ($('{0:N0}' -f $size) bytes)"
Write-Host "UNSIGNED by design - the Microsoft Store signs it during certification."
