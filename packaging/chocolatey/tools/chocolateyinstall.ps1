$ErrorActionPreference = 'Stop'

# The checksum below is the SHA256 of the published release asset, verified against
# the byte count GitHub reports for it. Chocolatey refuses the install on a mismatch,
# which is the behaviour we want: a wrong hash must fail loudly, never silently.
$packageArgs = @{
  packageName    = 'yazses'
  fileType       = 'exe'
  url64bit       = 'https://github.com/MSKazemi/yazses/releases/download/v2.20.0/YazSes-2.20.0-windows-x64.exe'
  checksum64     = 'da4562ccd7b349242901f602c894c7771f466d43b926787723b97487291eda78'
  checksumType64 = 'sha256'
  # Inno Setup: /VERYSILENT so unattended installs do not stall on the wizard.
  silentArgs     = '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP-'
  validExitCodes = @(0)
}

Install-ChocolateyPackage @packageArgs
