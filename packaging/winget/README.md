# winget manifest

`winget install MSKazemi.YazSes` is the cheapest reach we have on Windows: the
package manager ships in Windows 11 and Windows 10 1809+, so it needs no
download, no SmartScreen click-through in the flow, and no account.

Manifests are **generated, never hand-written** — winget validates the SHA256 of
the exact asset it will download, and a hand-copied hash fails in a way no
reviewer catches:

```bash
python scripts/winget-manifest.py 2.19.0        # hashes the published asset
```

That writes `packaging/winget/<version>/` with the three files winget expects
(version, installer, defaultLocale) against schema 1.12.0.

## Before submitting

**Do not submit a version built before the Windows fixes landed.** `2.18.0` and
earlier ship a bundle whose daemon never starts: the tray spawned it with argv
the bundle rejects, and because the binary is windowed the failure is silent.
The manifest checked in here for `2.18.0` exists to show the shape and to prove
the generator works — publishing it would put a non-functioning app in front of
every Windows user who runs `winget install`.

**Sign the release first.** winget does not require code signing, but SmartScreen
reputation accrues per signing certificate, so an unsigned installer still shows
the "unrecognized app" dialog even when it arrives via winget. `build-windows.yml`
already has the complete SignPath path wired; it is dormant only because the four
`SIGNPATH_*` repository secrets are unset. SignPath Foundation issues free
certificates to open-source projects, and approval takes days to weeks — start it
before you need it.

## Submitting

1. Fork <https://github.com/microsoft/winget-pkgs>.
2. Copy the version directory to
   `manifests/m/MSKazemi/YazSes/<version>/` in the fork.
3. Validate on a Windows machine (this is the part CI cannot do):
   ```powershell
   winget validate --manifest manifests\m\MSKazemi\YazSes\<version>
   winget install  --manifest manifests\m\MSKazemi\YazSes\<version>
   ```
4. Open one PR per version — winget-pkgs allows only one package version per PR.

Automated validation then installs the package unattended in a sandbox. Our
`/VERYSILENT /SUPPRESSMSGBOXES /NORESTART` switches are the same ones the
`Smoke-test the installer` step in `build-windows.yml` exercises on every build,
so an unattended-install regression fails at home rather than in Microsoft's
queue.

## Keeping it current

winget does not track releases; each new version needs its own PR. Regenerate
with the script and repeat. `ProductCode` is pinned to the Inno Setup `AppId`
from `packaging/windows/installer.iss` plus Inno's `_is1` suffix — if that AppId
ever changes, `winget upgrade` stops recognising existing installs, so change
both together or neither.
