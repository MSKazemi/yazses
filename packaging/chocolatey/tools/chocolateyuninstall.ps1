$ErrorActionPreference = 'Stop'

# Inno Setup registers itself as "<AppId>_is1"; the AppId is fixed in
# packaging/windows/installer.iss and must not change between versions.
$packageArgs = @{
  packageName    = 'yazses'
  fileType       = 'exe'
  softwareName   = 'YazSes*'
  silentArgs     = '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART'
  validExitCodes = @(0)
}

$uninstalled = $false
[array]$key = Get-UninstallRegistryKey -SoftwareName $packageArgs['softwareName']

if ($key.Count -eq 1) {
  $key | ForEach-Object {
    $packageArgs['file'] = "$($_.UninstallString)"
    Uninstall-ChocolateyPackage @packageArgs
  }
} elseif ($key.Count -eq 0) {
  Write-Warning "$packageName has already been uninstalled by other means."
} elseif ($key.Count -gt 1) {
  Write-Warning "$($key.Count) matches found!"
  Write-Warning "Please alert package maintainer the following packages were matched:"
  $key | ForEach-Object { Write-Warning "- $($_.DisplayName)" }
}
