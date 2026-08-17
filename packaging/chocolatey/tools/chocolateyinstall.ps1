$ErrorActionPreference = 'Stop'

# The checksum below is the SHA256 of the published release asset, verified against
# the byte count GitHub reports for it. Chocolatey refuses the install on a mismatch,
# which is the behaviour we want: a wrong hash must fail loudly, never silently.
$packageArgs = @{
  packageName    = 'yazses'
  fileType       = 'exe'
  url64bit       = 'https://github.com/MSKazemi/yazses/releases/download/v2.24.0/YazSes-2.24.0-windows-x64.exe'
  checksum64     = '795d6a48668a4bdfcc7f4ed3f4358b8b096745a20825be524911e6764bcc8351'
  checksumType64 = 'sha256'
  # Inno Setup: /VERYSILENT so unattended installs do not stall on the wizard.
  silentArgs     = '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP-'
  validExitCodes = @(0)
}

Install-ChocolateyPackage @packageArgs
