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

1. Download the installer for your machine from the
   [Releases](https://github.com/MSKazemi/yazses/releases) page:
   `YazSes-<version>-windows-x64.exe` for an Intel or AMD PC, or
   `YazSes-<version>-windows-arm64.exe` for an ARM one (Snapdragon, Surface Pro X).

    !!! tip "Not sure which?"

        **Settings → System → About → System type.** The x64 installer also runs on
        ARM under Windows' emulation, so it is the safe choice if you are unsure —
        the native ARM build is simply faster. See
        [platform support](platform-support.md#windows) for what is proven on each.
2. Double-click the installer.
3. **SmartScreen warning:** Windows shows
   *"Microsoft Defender SmartScreen prevented an unrecognized app from starting."*
   Click **More info** → **Run anyway**.
   You only need to do this once per version.
4. The installer puts YazSes into your per-user programs folder
   (`%LOCALAPPDATA%\Programs\YazSes`) and adds it to your PATH, so you don't
   need administrator rights. Pick the optional tasks:
   - **Start YazSes automatically when I sign in** — enables the autostart
     toggle (recommended).
   - **Create a desktop shortcut** — off by default; tick if you want one.
5. Click **Install**, then **Finish** (leave the *"Launch YazSes now"* box
   checked).

### From a package manager

Prefer the terminal? The manifests live in this repo and track each release.

```powershell
# Scoop — add the bucket once, then install and update like anything else
scoop bucket add yazses https://github.com/MSKazemi/yazses
scoop install yazses
```

`scoop update yazses` picks up new releases on its own: the manifest reads the
`SHA256SUMS.txt` that every release publishes, so the version and its checksum move
together rather than the checksum going stale.

**Status, honestly.** The Scoop bucket is served from this repo
([`bucket/yazses.json`](https://github.com/MSKazemi/yazses/blob/main/bucket/yazses.json))
and the winget manifests
([`packaging/winget/`](https://github.com/MSKazemi/yazses/tree/main/packaging/winget))
are written and versioned here, but neither has been installed end-to-end on a
clean Windows machine yet, and the winget submission to
`microsoft/winget-pkgs` is still open. Until someone confirms them, the installer
above is the path we can vouch for. If you have a Windows box and try one,
[issue #79](https://github.com/MSKazemi/yazses/issues/79) (Scoop) and
[#78](https://github.com/MSKazemi/yazses/issues/78) (winget) are where to say what
happened — that report is the only thing standing between these and being
recommended here.

The `.exe` is not code-signed yet, so SmartScreen warns on first launch whichever
route you take.

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
into `%USERPROFILE%\.cache\huggingface\hub\`. Subsequent dictations are fully
offline.

> **Behind a firewall?** That one download is the only time YazSes needs the
> network, and a personal firewall will block it. Fetch it deliberately instead —
> `yazses model download tiny.en` — or see
> [Choosing a model → Installing a model without network access](models.md#installing-a-model-without-network-access).

## Microphone access

The first time YazSes records, Windows shows a privacy prompt. Allow
microphone access for **Desktop apps**. If you missed the prompt or
accidentally denied it, re-enable in:

```
Settings → Privacy & Security → Microphone → "Let desktop apps access your microphone"
```

(or run `start ms-settings:privacy-microphone`.)

## Verify with the CLI

The installer puts `yazses` on your PATH, so the CLI works from any shell:

```powershell
yazses doctor     # check prerequisites, config, model, daemon state
yazses status     # query the running daemon
yazses verify     # run the real capture → transcribe → inject chain
```

Open a **new** terminal after installing — an already-open one still has the
old PATH.

The bundle contains two executables, and the difference matters:

| Binary | Subsystem | Use |
|---|---|---|
| `YazSesApp.exe` | windowed | tray and daemon; no console window flashes |
| `yazses-cli.exe` | console | the CLI — `yazses` on PATH is a shim to this |

A windowed binary has no console attached, so `YazSesApp.exe --cli doctor` has
nowhere to print. Use `yazses` (or `yazses-cli.exe` directly); that is what
these docs mean everywhere they say `yazses`.

Both live in `%LOCALAPPDATA%\Programs\YazSes`.

> **Upgrading from 2.18.2 or earlier?** The windowed binary used to be called
> `YazSes.exe`, which — because Windows resolves `.exe` before `.cmd` and
> filenames are case-insensitive — answered to a bare `yazses` and shadowed the
> shim. That is why `yazses doctor` printed nothing and then failed with
> *"'NoneType' object has no attribute 'isatty'"*. The installer deletes the old
> binary on upgrade; if you ever see a stray `YazSes.exe` in the install folder
> after a manual copy, delete it.

## Updating

Ask YazSes and it will tell you what applies to *your* install:

```powershell
yazses update --check    # what's available, and how to get it
```

It knows which of the four Windows channels you used, and checks the GitHub
release — that is where the `.exe` lives, and PyPI carries no `.exe` at all.

| How you installed | How to update |
|---|---|
| The `.exe` installer | Download the newest one from the [releases page](https://github.com/MSKazemi/yazses/releases/latest) and run it — it upgrades in place and keeps your settings and models |
| winget | `winget upgrade --id MSKazemi.YazSes -e` |
| Chocolatey | `choco upgrade yazses -y` |
| Scoop | `scoop update yazses` |

Restart YazSes afterwards (tray → **Restart daemon**, or `yazses restart`): the
new code is on disk, but the process doing your dictation is still the old one.

There is no one-command upgrade for the `.exe` installer — the upgrade *is* a
downloaded installer, and there is nothing YazSes could safely run for you. It
prints the steps instead of pretending otherwise.

### Being told when a new version lands

Off by default, because it is the only thing in YazSes that opens an outbound
connection on its own:

```powershell
yazses features enable update-check
yazses restart
```

Once on, YazSes checks daily and shows **one** notification per release, with the
steps for your install method. It sends a plain "what is the latest version"
request to github.com — no voice, no text, no config, no identifier — and nothing
else about your machine ever leaves it.

**Behind a firewall?** Nothing breaks. Dictation is entirely local and never needs
the network, and a blocked update check is a silent no-op that retries later —
it will not pop errors at you or stop the daemon. Run `yazses update` whenever you
want and it will tell you it could not reach github.com, then print the steps to
update by hand. (If your firewall also blocks the *first-run model download*, that
is the one thing YazSes genuinely needs the network for once; see
[#310](https://github.com/MSKazemi/yazses/issues/310) — it now explains itself
instead of dying, and `yazses model download base.en` fetches it when you unblock.)

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

**"`doctor` says the microphone is denied."** Allow it in *Settings → Privacy &
Security → Microphone*, and check **"Let desktop apps access your microphone"** is
on as well — that second switch is separate and gates YazSes even when the first
one is on. The pane opens directly with:

```
start ms-settings:privacy-microphone
```

If it is already allowed, Windows is reporting no input device at all: check it is
plugged in and enabled in Sound settings, then run `yazses audio devices`. The
**Microphone** row of `yazses doctor` prints this fix itself.

**"Dictation works everywhere except in one app."** If that app runs as
administrator (Task Manager, an elevated PowerShell, some installers and
enterprise tools), Windows blocks input sent to it from a non-elevated
process — User Interface Privilege Isolation, a security boundary, not a
bug. The daemon logs `SendInput sent 0/N events (lastError=5)` when this
happens. Run YazSes elevated too if you need to dictate into elevated
windows; otherwise leave it unelevated, which is the safer default.

To see which side of that boundary you are on, run `yazses doctor` and look
for the **Elevated windows** row:

```
  [OK] Elevated windows: not elevated (the safer default) - Windows will
       silently block dictation into windows that run as administrator ...
```

It is informational, never a failure — unelevated is the correct default. (The
row is Windows-only. It was absent from `doctor` in every release up to and
including v2.29.0 — the check was keyed to a platform name Windows never
reports, so it could not render on the one OS it exists for.)

**"Dictation stopped working part-way through the day."** If the daemon crashes,
Windows will not restart it on its own — the autostart entry only fires at login,
and there is no Windows Service supervising it. The **tray** is the safety net: it
notices the daemon has gone, restarts it (up to five times, then it stops and says
so), and turns red meanwhile. So keep the tray running. If you quit the tray, start
it again with `yazses tray`; to recover by hand, run `yazses start`.

**"Where do the mic warnings go?"** Windows has no libnotify, so the daemon cannot
show a toast itself. It hands them to the tray instead, which shows them as balloon
notifications — a microphone that changed, a silence threshold that was re-tuned,
several silent clips in a row. With the tray closed those only reach
`yazses logs`.

**"Tray icon is missing."** Windows may be hiding it under the chevron
(`^`) at the left of the tray. Drag it out, or right-click the taskbar →
**Taskbar settings** → **Other system tray icons** → flip on.

**"The icons are generic or blank."** Releases before this fix shipped without
their icon file, so shortcuts showed PyInstaller's default artwork and the tray
showed a plain coloured disc. Upgrade; if a stale shortcut keeps the old icon,
Windows is serving it from its icon cache — sign out and back in, or delete
`%LOCALAPPDATA%\IconCache.db` and restart Explorer.

**What the tray colour means.** The badge is the YazSes "Y" in a state colour:
🔵 blue ready/idle, 🟢 green dictating into a text field, 🟡 yellow dictating with
**no text field focused** (the words would go nowhere, so they are copied to the
clipboard instead), 🟣 purple command mode (the command key is held), 🔴 red a
problem — an error, or several silent clips in a row. Hover for the details.

## Uninstall

Use *Settings → Apps → Installed apps → YazSes → Uninstall*, or run the
uninstaller from `%LOCALAPPDATA%\Programs\YazSes\unins000.exe`. The uninstaller
stops a running daemon, removes the autostart registry entry, and takes its own
entry back out of your PATH (leaving the rest of PATH untouched).

To clear user data (config, logs, model cache) after uninstalling, also run:

```powershell
Remove-Item -Recurse -Force "$env:APPDATA\yazses"
Remove-Item -Recurse -Force "$env:LOCALAPPDATA\yazses"
```
