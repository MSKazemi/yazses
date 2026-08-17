$ErrorActionPreference = 'Stop'

# The checksum below is the SHA256 of the published release asset, verified against
# the byte count GitHub reports for it. Chocolatey refuses the install on a mismatch,
# which is the behaviour we want: a wrong hash must fail loudly, never silently.
$packageArgs = @{
  packageName    = 'yazses'
  fileType       = 'exe'
  url64bit       = 'https://github.com/MSKazemi/yazses/releases/download/v2.27.0/YazSes-2.27.0-windows-x64.exe'
  checksum64     = '28a2d86c79e8cfe7bfaa290d341b0777061f377ab1ea7b55e896faa80ce9fbfc'
  checksumType64 = 'sha256'
  # Inno Setup: /VERYSILENT so unattended installs do not stall on the wizard.
  silentArgs     = '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP-'
  validExitCodes = @(0)
}

Install-ChocolateyPackage @packageArgs
