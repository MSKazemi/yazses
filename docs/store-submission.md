---
title: Microsoft Store submission — MSIX, and why no certificate is needed
description: "How YazSes is packaged for the Microsoft Store as a full-trust MSIX, why that needs no purchased code-signing certificate, and the runFullTrust justification for certification."
---

# Microsoft Store submission

This page documents the Store route and, in particular, the two things a reviewer asks
about: why the package requests `runFullTrust`, and what it does with a global keyboard
hook.

!!! note "Nothing is submitted yet"

    What exists is the *package*: the manifest, the tile assets and the build script are
    in the repository, and `make msix` produces an MSIX on a machine with the Windows
    SDK. YazSes is **not** on the Microsoft Store and no submission is in flight — on
    Windows, install from [winget, Scoop or the direct installer](windows-install.md).
    The last section of this page is what has to happen before a submission can be made.

## Why MSIX, and why it costs nothing

[Store policy 10.2.9](https://learn.microsoft.com/windows/apps/publish/store-policy) requires
an **EXE/MSI** submission to be *"digitally signed with a code signing certificate that
chains up to a certificate issued by a Certificate Authority that is part of the Microsoft
Trusted Root Program."* An OV certificate costs roughly $150–300 a year.

That policy applies to the direct-download path only. **An MSIX submitted to the Store is
signed by Microsoft during certification**, so the Store route needs no purchased
certificate. This is the only free path to the Store.

!!! warning "This does not make the `.exe` signed"

    Microsoft signs the Store package. The installer distributed through GitHub Releases,
    winget, Chocolatey and Scoop is the same unsigned `.exe` as before and still triggers
    SmartScreen on first run. Fixing *that* needs a certificate for the binary itself —
    see [code signing](code-signing.md).

## Full trust, not AppContainer

A packaged desktop app is **not** automatically sandboxed. AppContainer is opt-in
(`uap10:TrustLevel="appContainer"`). YazSes declares `uap10:TrustLevel="mediumIL"`, which
Microsoft documents as a *full trust* app that "runs with the same permissions as a
standard desktop app" and does not run in an AppContainer.

This matters because YazSes needs three things a sandbox would deny:

| Needs | Why |
|---|---|
| Global `SetWindowsHookExW` keyboard hook | to notice the hold-to-talk key anywhere on the desktop, not only inside its own window |
| Raw microphone capture | to record while the key is held |
| `SendInput` into other applications' windows | to type the transcript into whatever has focus |

`SendInput` is governed by UIPI, which permits injection into processes at **equal or
lesser** integrity. Medium IL is exactly what the current unpackaged `.exe` runs at, so
packaging as MSIX costs no capability.

## `runFullTrust` justification

`runFullTrust` is a restricted capability. Certification permits it but asks the publisher
to explain why. The explanation, stated plainly:

> YazSes is a voice dictation tool for people who cannot type comfortably — because of RSI,
> a motor impairment, or an injury. It works by watching for one held key anywhere on the
> desktop, recording speech while that key is down, transcribing it locally, and typing the
> result into whichever application has focus. Those three operations require a global
> keyboard hook, microphone access, and synthetic keyboard input to another process. None
> is available to an AppContainer app, so the package is declared full trust.

### Proactive disclosure: this is not a keylogger

A global keyboard hook combined with synthetic keystroke injection is, on its face, the
signature of a keylogger. Rather than let a reviewer discover that, here is what the code
does and where to check it:

- **The hook matches a single configured virtual-key code** and never records key content.
  It answers one question — "is the hold-to-talk key currently down?" It is not a log.
- **Nothing the user says leaves the machine by default.** This is enforced mechanically,
  not promised: a test enumerates every module permitted to open an outbound connection and
  fails the build if any module gains an unregistered one (see
  [ADR-019](https://github.com/MSKazemi/yazses/blob/main/design/adr/adr-019-egress-inventory-and-escalation.md)).
  Exactly two paths can transmit dictated text, never audio, and both are off by default:
  one is confined to localhost unless the user explicitly overrides it, and the other goes
  only to a host the user names on the command line. Apart from those, the network paths
  only fetch model weights, a version string, or (at the user's request) packages and
  updates, and carry no user content. The remaining two are user-initiated too: a dictated
  `git` command run with `--run`, which reaches the user's own remote, and the optional
  bug-report button, which opens github.com with a redacted diagnostic summary.
- **Transcription is local.** faster-whisper runs on the CPU. There is no account, no API
  key, and no telemetry.
- **The same two OS facilities** are used by Dragon NaturallySpeaking, Talon Voice and
  Windows' own Voice Access.
- **The source is public** and Apache-2.0 licensed.

## Capabilities declared

| Capability | Why |
|---|---|
| `runFullTrust` | above |
| `microphone` | recording while the hotkey is held |

**`webcam` is deliberately not declared.** The camera features are implemented and
reachable on a PyPI install, and all of them are off by default. Glance-Type gaze targeting
(`yazses features enable gaze`) routes dictation to the pane you look at. The
Face-Gesture Switch (`yazses features enable facegesture`) opens the mic while you hold
a facial movement, for someone who can speak but cannot press a key. The Head-Pointer
(`yazses features enable headpointer`) moves the cursor by head pose. Each command
installs the same two optional packages, `mediapipe` and `opencv-contrib-python`.

What differs here is the packaging, not the product. The Store package is a frozen
PyInstaller bundle — `scripts/build-windows.ps1` syncs no camera extra (only `desktop`,
`parakeet` and `chinese`), so neither camera package is inside it, and an MSIX has no pip to add them afterwards.
The camera code paths are therefore unreachable **in this package specifically**:
`yazses features enable gaze` inside the MSIX refuses before it writes any config, and
names the install that works. Requesting camera access a user could never benefit from
is a certification question with no upside.

The direct installer, winget, Scoop and Chocolatey do not help here. All four install
the same frozen `.exe`, which has the same payload and no pip either. Anyone who wants a
camera feature on Windows should install from PyPI (`pipx install 'yazses[gaze]'`); see
[the camera permission and packaging matrix](capability-matrix.md#camera-permission-and-packaging).

## Building the package

```bash
make msix VERSION=<version> \
  IDENTITY_NAME=<from Partner Center> \
  PUBLISHER=<from Partner Center> \
  PUBLISHER_DISPLAY_NAME=<from Partner Center>
```

or directly:

```powershell
./scripts/build-windows.ps1              # produces dist/YazSes (PyInstaller COLLECT)
./scripts/build-msix.ps1 -Version <version> `
    -IdentityName "..." -Publisher "CN=..." -PublisherDisplayName "..."
```

Requires the Windows 10/11 SDK for `makeappx.exe`. The output is **unsigned on purpose**.

The tiles in `packaging/windows/msix/Assets/` are generated by `make icons`, not drawn by
hand, so the next brand change reaches them. Two of their rules only bite at packaging
time: a logo the manifest names but the package lacks fails the pack, and declaring
`Square310x310Logo` obliges `Wide310x150Logo` as well. `tests/test_msix_manifest.py` pins
both off Windows; the `msix-validate` workflow runs the real `makeappx` on every change
here, because a manifest that parses is not yet a manifest that packs.

### Identity values are not guessable

`Name`, `Publisher` and `PublisherDisplayName` must match what Partner Center shows for the
product **exactly**, or the upload is rejected. They are placeholders in the committed
manifest, and `build-msix.ps1` aborts if any survives substitution — a package built with a
placeholder identity would otherwise fail at submission, long after the build looked fine.

Find them in Partner Center under the product's **Product identity** page.

## Updates on the Store build

The Store replaces the package, and the install folder under `C:\Program Files\WindowsApps\`
is read-only to the app ([MSIX containerization overview](https://learn.microsoft.com/windows/msix/msix-containerization-overview)),
so the in-app updater ([ADR-027](https://github.com/MSKazemi/yazses/blob/main/design/adr/adr-027-one-click-windows-update.md))
could not replace the files even if it tried. A packaged build therefore never updates itself:

- `yazses update` prints `via msix`, says updates are managed by the Microsoft Store (or App
  Installer for a sideloaded package), prints the Store steps and exits 0. It makes **no network
  call**.
- The tray and Settings messages say the same, with no "Update available" or install button.
- `yazses doctor` shows an `Update check` row, `managed by the Microsoft Store`.
- The optional background release watcher (`update-check`, off by default) has nothing to announce
  for a packaged build.

"Packaged" is decided in `platform/windows/host.py`, and only for a frozen executable: an
`AppxManifest.xml` beside the executable, **or** package identity from Windows itself
(`GetCurrentPackageFullName`; `ERROR_INSUFFICIENT_BUFFER` means the process has identity,
`APPMODEL_ERROR_NO_PACKAGE` means it has none, per
[Detect package identity](https://learn.microsoft.com/windows/msix/detect-package-identity)).
A pip install run by the Store's own Python has *Python's* package identity and is not
mistaken for the Store build.

**Untested:** all of this is covered by unit tests with fakes on Linux. Nobody has run it from a
real MSIX install. Part of the first Windows test pass is to confirm that `yazses update` there
prints the Store message, that `doctor` shows the row, and that a plain `.exe` install
still updates itself.

## Static review of the MSIX files (2026-11-12)

A read of `AppxManifest.xml`, `scripts/build-msix.ps1` and the workflow against this page and
Microsoft Learn. **Nothing below was run on Windows.**

Matches the documentation:

- `uap10:RuntimeBehavior="packagedClassicApp"` with `uap10:TrustLevel="mediumIL"` is a documented
  combination, and `MinVersion="10.0.19041.0"` is what the `uap10` namespace requires
  ([Application element](https://learn.microsoft.com/uwp/schemas/appxpackage/uapmanifestschema/element-f-application)).
- `runFullTrust` (restricted, needs the justification above) and `microphone` (a normal device
  capability) are declared in the right namespaces.
- The version is four-part with the fourth part 0; the other parts must be 0 to 65535 and the first
  not 0 ([package version numbering](https://learn.microsoft.com/windows/apps/publish/publish-your-app/msix/app-package-requirements#package-version-numbering)).
  `build-msix.ps1` takes `X.Y.Z` and appends `.0`.
- Identity `Name`, `Publisher` and `PublisherDisplayName` are placeholders that the build refuses
  to leave in place, and Partner Center's values must be used exactly.
- All six logos the manifest names exist in `Assets/`, and `Wide310x150Logo` is present beside
  `Square310x310Logo`.

Defects and doubts, most important first:

1. **Autostart is probably broken or at least unproven in the package.** YazSes starts at sign-in
   through an `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` value
   (`platform/windows/lifecycle.py`). Microsoft's pages disagree on whether HKCU writes from a
   packaged app are copied to a private per-app location (*"Writes under HKCU: Copied on write to a
   per-user, per-app private location"*, [behind the scenes](https://learn.microsoft.com/windows/msix/desktop/desktop-to-uwp-behind-the-scenes#registry))
   or persist ([troubleshooting guide](https://learn.microsoft.com/windows/msix/msix-troubleshooting-guide)).
   If they are private, Windows never reads the value at sign-in. The documented route for a packaged
   desktop app is a `desktop:StartupTask` in the manifest, which the manifest does not declare.
   Unknown until tested; either `yazses autostart enable` must be packaging-aware, or the Store
   listing must not promise start-at-sign-in.
2. **No `yazses` command on PATH.** The package ships `yazses-cli.exe` (the console binary), but the
   manifest declares no app execution alias, so a Store user has no terminal command, and
   `yazses doctor`, `yazses features enable ...` and the other commands quoted throughout these docs
   are not reachable. Whether the windowed `YazSesApp.exe --cli` route works from a package is also
   unverified. Not fixed here.
3. **Per-user data is redirected.** For a packaged app, new files under `%LOCALAPPDATA%` go to a
   private per-package location visible only to that app, and are deleted on uninstall
   (same Microsoft page as above). Downloaded models and config in a Store install are therefore
   not shared with a PyPI or `.exe` install on the same machine. Measure model download size and
   uninstall behaviour on a real install.
4. **`MaxVersionTested="10.0.22621.0"` is old** (Windows 11 22H2). Raise it to a current build
   when packaging for real. Learn gives no rule that makes this fail certification, so this is a
   hygiene point, not a known rejection.
5. **The build script does not XML-escape** the values it substitutes into the manifest. A
   `PublisherDisplayName` containing `&` or `<` produces malformed XML, which `makeappx` rejects
   loudly at pack time (not silently). Partner Center values for an individual account are not
   expected to contain them, but the check is cheap.
6. **The version check is looser than the rule.** `^\d+\.\d+\.\d+$` accepts `0.1.0` (first
   part 0 is forbidden) and numbers above 65535. Both fail only at upload.
7. **Only base-scale tile PNGs, no `resources.pri`.** The manifest points at plain files. That
   works, but Microsoft's icon guidance recommends scale variants and unplated target-size
   icons; without them taskbar and Start icons may look soft or plated. Cosmetic.
8. **Reviewer risk, not a defect:** a global hook plus synthetic input will be questioned during
   certification. The disclosure above is the answer; whether it is accepted is unknown.

## Privacy switches on the Store build

Windows gates the microphone behind *Settings → Privacy & Security → Microphone*. The
`.exe`, pip, winget, Scoop and Chocolatey installs are desktop apps, governed by **"Let
desktop apps access your microphone"**. The MSIX is a packaged app: Windows lists it by
name on the same page, and the desktop-apps switch does not govern it
([#653](https://github.com/MSKazemi/yazses/issues/653)). So on the Store build:

- `yazses doctor` and the start-up check do not read the desktop-apps switch. They still
  honour the device-wide and per-user switches, which apply to every app.
- The per-app YazSes entry is not read either, because Microsoft does not document where
  it is stored. If YazSes alone is switched off, `doctor` cannot see it, and the
  microphone advice points to the YazSes entry in the app list.
- The camera advice says the Store build cannot use the camera features at all (no
  `webcam` capability and no camera runtime, see above) instead of naming a switch.

All of this rests on Microsoft's documentation and unit tests with a simulated registry.
It has **not run on a real MSIX install**. Checking it on one (desktop-apps switch off,
YazSes on, `yazses doctor` shows the microphone as OK) is part of preparing a submission.

## ⚠ Product type in Partner Center

The reserved `YazSes` product is typed **"EXE or MSI app"**. That product type takes a
download URL to a signed installer; it does not accept an MSIX package. Publishing this
package needs a product of type **"MSIX or PWA app"**, and a Store name is held by one
product. Whether Partner Center lets a second, MSIX-typed product reserve the same name while the
EXE product holds it is **not verified**; if it does not, using the name for MSIX means releasing
it from the EXE product first.

That is a deliberate choice, not a formality: keeping the EXE product reserves the option of
a signed direct-download submission later, if a certificate ever becomes available.

A reserved name is also not held indefinitely — Partner Center releases one that no product
ships against. The `YazSes` reservation was made in September 2026; its expiry is on the
product's page in Partner Center, and that is the date to read rather than one repeated
here, because nothing in this repository can notice it passing.
