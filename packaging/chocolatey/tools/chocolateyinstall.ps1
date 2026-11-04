$ErrorActionPreference = 'Stop'

# The checksum below is the SHA256 of the published release asset, verified against
# the byte count GitHub reports for it. Chocolatey refuses the install on a mismatch,
# which is the behaviour we want: a wrong hash must fail loudly, never silently.
$packageArgs = @{
  packageName    = 'yazses'
  fileType       = 'exe'
  url64bit       = 'https://github.com/MSKazemi/yazses/releases/download/v2.48.1/YazSes-2.48.1-windows-x64.exe'
  checksum64     = '5cb30839db5ae16f07ec6f044754c3bb14e0ae3235b3006e1161d80b42b2c530'
  checksumType64 = 'sha256'
  # Inno Setup: /VERYSILENT so unattended installs do not stall on the wizard.
  silentArgs     = '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP-'
  validExitCodes = @(0)
}

Install-ChocolateyPackage @packageArgs
