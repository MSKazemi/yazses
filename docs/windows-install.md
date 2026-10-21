---
title: Install offline voice dictation on Windows — YazSes setup guide
description: "Install YazSes on Windows for offline speech-to-text: winget install, microphone permissions, hold-to-talk hotkey, and first-run calibration. A local alternative to Windows Speech Recognition."
---

# YazSes on Windows — install & first-run guide

> **Version:** Applies to the current YazSes release (v2.x). `winget install MSKazemi.YazSes`
> is the shortest install, but the winget catalogue trails the newest tag — see
> [which version winget gives you](#the-one-line-way--winget-recommended) before you pick a route.

> **Developer preview.** Windows builds are **unsigned**. Windows SmartScreen
> warns on first launch; the steps below show how to bypass it safely. Code
> signing lands before public beta.

## Requirements

- Windows 10 21H2 or later, 64-bit (Windows 11 also fine)
- ~500 MB free disk for the app (about 190 MB) and the default Whisper model (about 150 MB), downloaded on first use
- A microphone

## Install

### The one-line way — winget (recommended)

YazSes is in the Windows Package Manager, which ships with Windows 10 21H2 and
Windows 11. Open Terminal or PowerShell and run:

```powershell
winget install MSKazemi.YazSes
```

It installs the x64 build (an ARM PC runs it under Windows' x64 emulation; there is no
native ARM64 build), verifies the installer's SHA256
against the published manifest, and installs per-user with no administrator
rights. `winget upgrade MSKazemi.YazSes` moves you to a new release later.

!!! note "Which version winget gives you"

    Every version bump is submitted to Microsoft's catalogue by hand and has to clear a
    community moderator, so winget can trail the newest tag by **weeks and several
    releases** — not hours. Run `winget show MSKazemi.YazSes` and compare what it offers
    with the [latest release](https://github.com/MSKazemi/yazses/releases/latest) before
    you commit to this route. Whatever winget gives you is a working, checksum-verified
    build, but if you want the newest one the day it ships, use the installer below or
    Scoop — both track every release.

### Manual installer

1. Download the installer for your machine from the
   [Releases](https://github.com/MSKazemi/yazses/releases) page:
   `YazSes-<version>-windows-x64.exe`. It is the installer for an Intel or AMD PC and,
   through Windows' emulation, for an ARM one (Snapdragon, Surface Pro X): there is no
   native ARM build because the speech engine has no ARM Windows wheel yet.

    !!! tip "On an ARM PC?"

        **Settings → System → About → System type** says which you have. Use the same
        x64 installer either way. See [platform support](platform-support.md#windows)
        for what is proven on each.
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
# Chocolatey — from an administrator PowerShell
choco install yazses

# Scoop — add the bucket once, then install and update like anything else
scoop bucket add yazses https://github.com/MSKazemi/yazses
scoop install yazses
```

`scoop update yazses` picks up new releases on its own: the manifest reads the
`SHA256SUMS.txt` that every release publishes, so the version and its checksum move
together rather than the checksum going stale.

**Status, honestly.** **Scoop works** — the bucket is served straight from this repo
([`bucket/yazses.json`](https://github.com/MSKazemi/yazses/blob/main/bucket/yazses.json)),
carries the x64 installer (ARM PCs run it under emulation), and has been installed end-to-end on a clean Windows
host: `yazses update --check` correctly reports the install as `via scoop` and
offers `scoop update yazses`. The direct installer above is verified the same way
(`via windows-installer`).

**winget works.** The submission to `microsoft/winget-pkgs` was
moderator-approved and merged on 2026-09-10, so `winget install MSKazemi.YazSes`
resolves against Microsoft's own catalogue. The manifests are authored here in
([`packaging/winget/`](https://github.com/MSKazemi/yazses/tree/main/packaging/winget))
and their checksums are derived from the real release assets rather than copied by
hand. Notes go in [issue #78](https://github.com/MSKazemi/yazses/issues/78); Scoop
notes go in [#79](https://github.com/MSKazemi/yazses/issues/79).

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
> `%LOCALAPPDATA%\yazses\config.toml`:
>
> ```toml
> [hotkey]
> # "auto" → Right Ctrl on Windows. Other options: "right_alt", "right_shift",
> # "left_alt", "space", "right_meta", ...
> key = "auto"
> hold_threshold_ms = 500
>
> [stt]
> model = "base.en"   # the default; "tiny.en" is faster and less accurate
> ```

The first transcription downloads the Whisper model (about 150 MB for the default `base.en`)
into `%USERPROFILE%\.cache\huggingface\hub\`. Subsequent dictations are fully
offline.

> **Behind a firewall?** That one download is the only time YazSes needs the
> network, and a personal firewall will block it. Fetch it deliberately instead —
> `yazses model download base.en` — or see
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

**One click.** Tray → **Check for updates…**, or the Settings window → **About and
updates** → **Check for updates**, then **Install update…**. If a newer release is out,
YazSes asks once whether to install it. Say yes and YazSes:

1. downloads `YazSes-<version>-windows-<arch>.exe` from the GitHub release (only from
   `github.com/MSKazemi/yazses/releases/download/`);
2. checks its SHA-256 against the release's `SHA256SUMS.txt`, and refuses (and deletes
   the file) if they differ;
3. closes itself, runs the installer silently over your existing install (no uninstall,
   settings and models kept), and
4. starts again by itself. On the next start a notification says whether the version
   actually changed.

The same from a terminal:

```powershell
yazses update --check    # what's available, and what the update would do
yazses update            # asks, then updates
yazses update --yes      # updates without asking
```

It knows which of the four Windows channels you used and checks the GitHub release.
That is where the `.exe` lives; PyPI carries no `.exe` at all. Chocolatey, winget and
Scoop installs update through their own package manager in the same one-click way:

| How you installed | What the one-click update runs |
|---|---|
| The `.exe` installer, for you only (the default) | the verified installer, silently, in place |
| The `.exe` installer, for all users | the same, after one administrator prompt (see below) |
| winget | the same as the `.exe` installer: a winget install cannot be told apart from it |
| Chocolatey | `choco upgrade yazses -y` — Windows asks for administrator rights |
| Scoop | `scoop update yazses` |

What to expect:

- **Per-user installs need no administrator rights.** A normal install is per-user, and
  the update runs as you.
- **All-users installs ask once.** If YazSes was installed *for all users* (in
  `C:\Program Files`), updating needs administrator rights, so Windows shows **one**
  permission prompt. The prompt names **Windows PowerShell** from Microsoft, not YazSes:
  that is the small helper that does the privileged part. It copies the checked
  installer into a new folder that only administrators can change, checks its SHA-256
  again there, runs it from that folder, and deletes the folder. The installer is never
  run with administrator rights from your own temp folder, where any program you run
  could have swapped it. On a standard (non-administrator) account, the prompt asks for
  an administrator's password.
- **Saying No at that prompt is safe.** Nothing is installed, YazSes starts again on the
  version you had, and the next start says the permission was declined.
- **If YazSes cannot tell how it was installed** (for example, you copied the folder
  somewhere else), no one-click update is offered. YazSes says so and opens the releases
  page; run the installer yourself. It upgrades in place, with no uninstall needed.
- **Chocolatey, winget and Scoop** are offered the update only once their own package
  has caught up with the GitHub release. That usually takes a few days. Until then YazSes
  says which version the manager still offers. Chocolatey asks for administrator rights.
- **Nothing is force-closed.** If YazSes has not closed within 5 minutes (for example,
  a meeting still being saved), nothing is installed and the next start tells you why.
- **From a terminal**, `yazses update` works with the tray running: the tray sees the
  update starting, closes itself and stops YazSes, and both come back on the new version.
- **From the Settings window**, the same: the check runs in the background, so the window
  keeps responding. After you confirm, the Settings window closes, the tray closes itself
  and stops YazSes, and the update installs. Changes you staged in the window but did not
  apply are lost, and the question says so first. If one-click is not possible (an
  all-users install, a package manager that has not caught up), the window shows why and
  the manual steps, and **Open download page** opens the releases page. The Settings
  button uses the same code as the tray and `yazses update`, but it has not yet been
  tried on a real Windows machine.
- **Microsoft Store / MSIX package:** it updates through the Store (Library → Get
  updates), or by opening the newer `.msix`. Never run the `.exe` over it; that installs
  a second copy.
- **Not code-signed yet.** The checksum proves the file is exactly the one the release
  published. It does not prove who built it; signing is the remaining step. SmartScreen
  may warn for the same reason.
- **If anything fails**, nothing is half-installed. YazSes keeps running (or starts again
  on the version you had), tells you what went wrong, and opens the
  [releases page](https://github.com/MSKazemi/yazses/releases/latest) so you can update by
  hand. Logs: `%TEMP%\yazses-update\update.log` and `installer.log`. An all-users update
  keeps no `installer.log`: the privileged helper writes nothing into your folders, and
  `update.log` records how it ended.

- **Add-ons are downloaded again for the new version.** An add-on (see below) is built
  for one exact build of YazSes, so after an update the old copy is not loaded. If you
  have add-ons installed, the update question in the tray and the Settings window names
  them and their download sizes, for example *"Your add-on (Diarization, 15 MB) will be
  downloaded again for the new version."* Saying yes covers that download too: on its
  first start the new version fetches its own copy of each add-on in the background,
  checks it against the checksum built into the new version, tests it, and then tells
  you once (**Add-ons ready** — restart YazSes to switch them on). The old version's
  add-on files are deleted only after every new copy has checked out, so a failed
  update can still go back to them; if there is nothing to download, they are deleted
  once the new version has started. If a download fails, or you updated with
  `yazses update` from a terminal (which does not ask about add-ons), nothing is
  retried on its own: the feature shows *waiting for add-on*, and **Install now** in
  the Settings window (or `yazses packs install <name>`) downloads it with one click.
  This path is covered by offline tests; it has not yet been tried on a real Windows
  machine with a published add-on.

By hand, if you prefer: download the newest installer from the releases page and run it.
It upgrades in place too.

### Features that need extra libraries

The installer build's files are fixed when it is built, so it cannot install Python
packages the way a `pipx` install can. A feature that needs them is listed in the
Settings window's **About and updates** box. When the build you run publishes an
**add-on** for that feature (ADR-028), its **Install now** button downloads, checks and
installs the add-on, the same as `yazses packs install <name>`, and then asks to restart
YazSes. When it does not, the button is greyed out and says why: install YazSes with
`pipx install yazses` to use that feature. `yazses packs` lists the add-ons your build
has.

Two such features need no add-on, because their libraries are inside the installer
from the release after v2.43.2: the Parakeet speech engine (`stt-parakeet`; its ~600 MB
model still downloads on first use) and Chinese script conversion (`chinese-script`).
They add about 4.5 MB to the installer (a wheel-size figure, not yet measured on a
built installer). Speaker diarization (`diarize`, `meeting`, `recimport`) is the first
add-on; a release publishes it only after it passes its checks inside the frozen app.
Its pack does not carry its own copy of ONNX Runtime: it uses the one the installer
already has, so two different copies are never loaded into one process.

**No internet on this PC, or a firewall that blocks github.com?** Download the add-on file
on another computer, from the release of the version you run, copy it over, and run the
command below. The file name has this shape (an illustration: no add-on has been published
yet): `YazSes-2.44.0-windows-x64-pack-diarization.yazpack`.

```powershell
yazses packs install --from D:\YazSes-2.44.0-windows-x64-pack-diarization.yazpack
```

This makes no network request. The file is accepted only if its name is one of this
build's add-on files and its SHA-256 matches the checksum built into your copy of YazSes,
so a file that was changed, cut short, or made for another version or build is refused
and nothing is installed. It is then unpacked, tested and installed exactly as a
download would be. Keep the file name as the release gives it.

#### Licences of add-on packs

Every add-on carries the licence text of each library inside it, in its `LICENSES\`
folder (under `%LOCALAPPDATA%\yazses\packs\` once installed). The release build checks
those licences before it publishes an add-on:

- **Permissive** licences (MIT, Apache-2.0, BSD, ISC and similar) pass.
- **LGPL** and **MPL-2.0** pass, and the add-on then also carries `LICENSES\SOURCE.md`,
  which names each of those libraries, its exact version and where its source code is.
- **GPL** passes only when the maintainer has recorded an approval for that library, at
  that version, in that add-on. `SOURCE.md` lists those too.
- A library whose licence the build cannot identify, or that ships no licence file, holds
  the whole add-on back. The feature then works the same way as one with no add-on:
  install YazSes with `pipx install yazses` to use it.

The check reads the licence each library *declares*. It does not scan the compiled files
inside a library for code under another licence.

### Being told when a new version lands

Off by default, because it is the only thing in YazSes that opens an outbound
connection on its own:

```powershell
yazses features enable update-check
yazses restart
```

Once on, YazSes checks daily and shows **one** notification per release. It points you
at the tray's **Check for updates…**, which installs it in one click. It sends a plain "what is the latest version"
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

**"Nothing is ever typed, and the log names a `.dll`."** If dictation records but
produces no text and you see something like

```
FileNotFoundError: Could not find module '...\ctranslate2\ctranslate2.dll'
(or one of its dependencies).
```

the speech-to-text engine cannot load. YazSes decodes through CTranslate2, which is a
compiled library, and on Windows it needs the **Microsoft Visual C++ Redistributable
(x64)** — see [CTranslate2's installation
notes](https://opennmt.net/CTranslate2/installation.html). Most machines already have
it; a fresh Windows install or a Windows Server image often does not. Run `yazses setup` — it installs the runtime with winget — or download it from
<https://aka.ms/vs/17/release/vc_redist.x64.exe>, then restart the daemon.

Note the wording: Windows says *"or one of its dependencies"* even when the file it
names is present, which is why this reads like a missing file when it is a missing
runtime. If the redistributable is already installed, the package itself is incomplete —
`pip install --force-reinstall ctranslate2`.

`yazses doctor` checks this directly and prints the fix:

```
  [FAIL] STT engine: ctranslate2 is installed but will not load (FileNotFoundError: ...)
         - dictation cannot transcribe anything. Fix: install the Microsoft Visual C++
         Redistributable (x64) from https://aka.ms/vs/17/release/vc_redist.x64.exe ...
```

Mostly relevant to `pip`/`uv`/from-source installs; the `.exe` installer ships its own
copies of the libraries it needs.

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
bug. Windows does not report the block: the keystrokes simply never arrive.
So YazSes checks before typing. When the window in front runs as
administrator, your dictation goes to the clipboard instead, with a
notification saying so; paste it with Ctrl+V. (That needs the default
`[injection] target_guard = "clipboard"`; with `"warn"` you only get the
notification.) Run YazSes elevated too if you need to dictate into elevated
windows directly; otherwise leave it unelevated, which is the safer default.

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

**Add-ons.** For a normal install (just for you), the uninstaller also deletes your
add-ons folder, `%LOCALAPPDATA%\yazses\packs`. Only that folder: your config, logs and
models stay, as below. An update never deletes add-ons; it installs over the old copy
without running the uninstaller.

If YazSes was installed **for all users**, Windows runs the uninstaller as the
administrator, so it cannot reach anyone's add-ons and deletes none. Each user who
installed add-ons should run this **before** the uninstall:

```powershell
yazses packs remove --all
```

`yazses doctor` shows an **Add-ons** row in that case, with how much the command frees.
It shows the same row on any install where add-ons from an older build are left over
that this copy no longer loads. Add-ons left behind are inert: nothing loads them without
YazSes, and a later version ignores them because they belong to another build. You can
also delete the folder by hand.

To clear user data (config, logs, model cache) after uninstalling, also run:

```powershell
Remove-Item -Recurse -Force "$env:LOCALAPPDATA\yazses"
# the Whisper models, shared with other faster-whisper apps — skip this if you use one
Remove-Item -Recurse -Force "$env:USERPROFILE\.cache\huggingface\hub\models--Systran--faster-whisper-*"
```
