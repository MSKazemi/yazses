$ErrorActionPreference = 'Stop'

# The checksum below is the SHA256 of the published release asset, verified against
# the byte count GitHub reports for it. Chocolatey refuses the install on a mismatch,
# which is the behaviour we want: a wrong hash must fail loudly, never silently.
$packageArgs = @{
  packageName    = 'yazses'
  fileType       = 'exe'
  url64bit       = 'https://github.com/MSKazemi/yazses/releases/download/v2.37.2/YazSes-2.37.2-windows-x64.exe'
  checksum64     = '2fd0eba3bef85eb3ecc2b0be5a8860aeaf109006d0b65c40556b3a0fc8983c47'
  checksumType64 = 'sha256'
  # Inno Setup: /VERYSILENT so unattended installs do not stall on the wizard.
  silentArgs     = '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP-'
  validExitCodes = @(0)
}

Install-ChocolateyPackage @packageArgs
