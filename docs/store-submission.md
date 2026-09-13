---
title: Microsoft Store submission — MSIX, and why no certificate is needed
description: "How YazSes is packaged for the Microsoft Store as a full-trust MSIX, why that needs no purchased code-signing certificate, and the runFullTrust justification for certification."
---

# Microsoft Store submission

This page documents the Store route and, in particular, the two things a reviewer asks
about: why the package requests `runFullTrust`, and what it does with a global keyboard
hook.

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
- **Nothing leaves the machine.** This is enforced mechanically, not promised: a test
  enumerates every module permitted to open an outbound connection and fails the build if
  any module gains an unregistered one (see [ADR-019](https://github.com/MSKazemi/yazses)).
  Of the modules that touch the network, all but two only fetch model weights or a version
  string; the two that can transmit speech are confined to localhost and to a host the user
  names on the command line.
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

**`webcam` is deliberately not declared.** The gaze (Glance-Type) and Face-Gesture features
depend on `mediapipe`, an optional extra the PyInstaller bundle does not ship, so those
code paths cannot run in the Store package. Asking for camera access for code that is not
present would be a certification question with no benefit to the user.

## Building the package

```bash
make msix VERSION=2.36.0 \
  IDENTITY_NAME=<from Partner Center> \
  PUBLISHER=<from Partner Center> \
  PUBLISHER_DISPLAY_NAME=<from Partner Center>
```

or directly:

```powershell
./scripts/build-windows.ps1              # produces dist/YazSes (PyInstaller COLLECT)
./scripts/build-msix.ps1 -Version 2.36.0 `
    -IdentityName "..." -Publisher "CN=..." -PublisherDisplayName "..."
```

Requires the Windows 10/11 SDK for `makeappx.exe`. The output is **unsigned on purpose**.

### Identity values are not guessable

`Name`, `Publisher` and `PublisherDisplayName` must match what Partner Center shows for the
product **exactly**, or the upload is rejected. They are placeholders in the committed
manifest, and `build-msix.ps1` aborts if any survives substitution — a package built with a
placeholder identity would otherwise fail at submission, long after the build looked fine.

Find them in Partner Center under the product's **Product identity** page.

## ⚠ Product type in Partner Center

The reserved `YazSes` product is typed **"EXE or MSI app"**. That product type takes a
download URL to a signed installer; it does not accept an MSIX package. Publishing this
package needs a product of type **"MSIX or PWA app"**, and a Store name can only be held by
one product — so using the reserved name for MSIX means releasing it from the EXE product
first.

That is a deliberate choice, not a formality: keeping the EXE product reserves the option of
a signed direct-download submission later, if a certificate ever becomes available.
