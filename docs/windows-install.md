---
title: Install offline voice dictation on Windows — YazSes setup guide
description: "Install YazSes on Windows for offline speech-to-text: pipx install, microphone permissions, hold-to-talk hotkey, and first-run calibration. A local alternative to Windows Speech Recognition."
---

# YazSes on Windows — install & first-run guide

> **Version:** Applies to the current YazSes release (v2.x). Install the latest with `pipx install yazses`.

> **Developer preview.** Windows builds are **unsigned**. Windows SmartScreen
> warns on first launch; the steps below show how to bypass it safely. Code
> signing lands before public beta.

## Requirements

- Windows 10 21H2 or later, 64-bit (Windows 11 also fine)
- ~250 MB free disk for the app + the Whisper model on first download
- A microphone

## Install

1. Download `YazSes-<version>-windows-x64.exe` from the
   [Releases](https://github.com/MSKazemi/yazses/releases) page.
2. Double-click the installer.
3. **SmartScreen warning:** Windows shows
   *"Microsoft Defender SmartScreen prevented an unrecognized app from starting."*
   Click **More info** → **Run anyway**.
   You only need to do this once per version.
4. The installer puts YazSes into your user folder (`%USERPROFILE%\YazSes`)
   so you don't need administrator rights. Pick the optional tasks:
   - **Start YazSes automatically when I sign in** — enables the autostart
     toggle (recommended).
   - **Create a desktop shortcut** — off by default; tick if you want one.
5. Click **Install**, then **Finish** (leave the *"Launch YazSes now"* box
   checked).

## First run

YazSes's tray icon appears in the system tray (next to the clock). The
default hotkey is **Right Ctrl** — hold it anywhere on the desktop, speak,
release, and the transcribed text appears in whatever window is focused.

> Why **not** Right Alt? On many international keyboards, Right Alt acts as
> AltGr — it's used to type `@`, `€`, `{`, `}`, `[`, `]`, `\`, `~`, etc.
> Hijacking it for dictation would break normal typing. Right Ctrl is rarely
> used for typing, so it's the safer default. You can change this in
> `%APPDATA%\yazses\config.toml`:
>
> ```toml
> [hotkey]
> # "auto" → Right Ctrl on Windows. Other options: "right_alt", "right_shift",
> # "left_alt", "space", "right_meta", ...
> key = "auto"
> hold_threshold_ms = 500
>
> [stt]
> model = "tiny.en"   # try "base.en" for better accuracy at the cost of CPU
> ```

The first transcription downloads the Whisper model (~80 MB for `tiny.en`)
into `%LOCALAPPDATA%\huggingface\hub\`. Subsequent dictations are fully
offline.

## Microphone access

The first time YazSes records, Windows shows a privacy prompt. Allow
microphone access for **Desktop apps**. If you missed the prompt or
accidentally denied it, re-enable in:

```
Settings → Privacy & Security → Microphone → "Let desktop apps access your microphone"
```

(or run `start ms-settings:privacy-microphone`.)

## Verify with the CLI

The installer also exposes the CLI:

```powershell
& "$env:USERPROFILE\YazSes\YazSes.exe" --cli doctor
& "$env:USERPROFILE\YazSes\YazSes.exe" --cli status
```

Add `$env:USERPROFILE\YazSes` to your PATH if you want plain `YazSes`
to work in any shell.

## Troubleshooting

**"My antivirus flagged YazSes."** These builds are unsigned, which trips
conservative AV heuristics — especially because the daemon installs a
low-level keyboard hook. Either build from source
(`scripts/build-windows.ps1`) or wait for signed builds (planned). The
artifacts uploaded by the build CI run are reproducible from this repo.

**"The hotkey doesn't fire."** Some keyboard remappers (e.g. PowerToys
Keyboard Manager, AutoHotkey scripts) intercept low-level hooks before
YazSes. Try a different key in `config.toml`, or temporarily disable
those remappers.

**"YazSes keeps re-prompting for microphone access."** Windows treats
unsigned apps as new identities each time their hash changes. After every
update you may need to re-allow.

**"Tray icon is missing."** Windows may be hiding it under the chevron
(`^`) at the left of the tray. Drag it out, or right-click the taskbar →
**Taskbar settings** → **Other system tray icons** → flip on.

## Uninstall

Use *Settings → Apps → Installed apps → YazSes → Uninstall*, or run the
uninstaller from `%USERPROFILE%\YazSes\unins000.exe`. The uninstaller
also removes the autostart registry entry.

To clear user data (config, logs, model cache) after uninstalling, also run:

```powershell
Remove-Item -Recurse -Force "$env:APPDATA\yazses"
Remove-Item -Recurse -Force "$env:LOCALAPPDATA\yazses"
```
