---
title: Install offline voice dictation on macOS — YazSes setup guide
description: "Install YazSes on macOS for private, on-device dictation: pipx install, microphone and accessibility permissions, hotkey setup, and first-run calibration. No cloud account needed."
---

# YazSes on macOS — install & first-run guide

> **Version:** Applies to the current YazSes release (v2.x). Install the latest with `pipx install yazses`.

> **Developer preview.** macOS builds are **unsigned** and **not notarized**.
> macOS will warn you on first launch; the steps below show how to bypass
> Gatekeeper safely. Signing and notarization land before public beta.

## Requirements

- macOS 11 (Big Sur) or later
- **Either architecture** — releases carry an Apple Silicon `.dmg` and an Intel
  one; only the *Homebrew cask* is Apple Silicon only (see the note below)
- ~250 MB free disk for the app + the Whisper model on first download
- A microphone

### Which Mac do I have?

Apple menu → **About This Mac**. If *Chip* says **Apple M1/M2/M3/M4**, take the
`…-macos-arm64.dmg`. If *Processor* says **Intel**, take the `…-macos-x86_64.dmg`
(or use pipx — see below).

Or from a terminal:

```sh
uname -m      # arm64 → Apple Silicon;  x86_64 → Intel
```

## Install

### Apple Silicon — Homebrew (recommended)

```sh
brew tap MSKazemi/yazses
brew trust MSKazemi/yazses
brew install --cask yazses
```

Upgrades then come with `brew upgrade --cask yazses`.

> **The `brew trust` line is not optional.** Homebrew now refuses to load a cask
> from a third-party tap until you trust it, so without it the install stops with
>
> ```
> Error: Refusing to load cask mskazemi/yazses/yazses from untrusted tap mskazemi/yazses.
> ```
>
> This is Homebrew's own anti-supply-chain hardening, not a fault in the tap — it
> applies to every third-party tap. Reported and verified end to end on an Apple M4
> by [@slegarraga](https://github.com/slegarraga)
> ([#182](https://github.com/MSKazemi/yazses/issues/182)); the install completes
> cleanly once the tap is trusted.

### Apple Silicon — direct download

1. Download `YazSes-<version>.dmg` from the
   [Releases](https://github.com/MSKazemi/yazses/releases) page.
2. Open the `.dmg`. Drag **YazSes.app** into the **Applications** folder shown
   in the Finder window.
3. Eject the `.dmg`.

### Intel Macs — take the x86_64 `.dmg`, or install from PyPI

**Since v2.22.0 there is an Intel build.** The `.dmg` is produced as a
per-architecture matrix, so every release carries both
`YazSes-<version>-macos-arm64.dmg` and `YazSes-<version>-macos-x86_64.dmg`. Take the
`x86_64` one.

The **Homebrew cask** is still Apple Silicon only: it declares
`depends_on arch: :arm64`, so `brew install --cask yazses` refuses cleanly on Intel
rather than installing something that cannot start.

⚠ The Intel leg is `continue-on-error` in CI, so a release *can* ship without it. If
you do not see an `x86_64` asset on a given release, install from PyPI instead — but
**check your Python version first**:

```sh
python3 --version     # must be 3.11, 3.12 or 3.13 on an Intel Mac
pipx install yazses
yazses quickstart
```

You get the same daemon and CLI; what you do not get is the `.app` bundle and
its tray icon. Everything below about Accessibility and Microphone permissions
still applies — grant them to your **terminal** app instead of to YazSes.app.

#### The Intel Python ceiling — upstream's, not ours

This page used to say PyPI "is architecture independent and always works". That is
no longer true, and the way it fails is misleading, so it is worth the paragraph.

| What you install | Python versions that work on Intel macOS |
|---|---|
| `pipx install yazses` (base) | **3.11 – 3.13** |
| `yazses[all]` | **3.11 – 3.12** |
| Anything, on Apple Silicon | 3.11 and up — unaffected |

The cause is upstream wheel publishing, not YazSes packaging:

- **`onnxruntime`** published no `x86_64` macOS wheel after **1.23.2**, and 1.23.2
  was built for CPython 3.10–3.13 only. `faster-whisper` requires `onnxruntime` and
  is not optional here, so on Python 3.14 the **base** install cannot resolve.
- **`torch`** published no Intel macOS wheel after **2.4.1** (CPython 3.12), so the
  `voiceprint` extra — and therefore `[all]` — already cannot resolve on 3.13.

On Python 3.14 you will see a long resolver backtrace ending in something like
*"onnxruntime>=1.14.0,<=1.23.2 has no wheels with a matching Python ABI tag
(cp314)"*. It names `onnxruntime` and reads like a YazSes bug. It is not: pin your
interpreter to 3.13 (`pipx install --python python3.13 yazses`) and it installs.

**Already installed and working?** Nothing breaks today — but a Python upgrade will
break your *next* install rather than your current one, which is the worst possible
time to find out. `yazses doctor` prints an **Intel macOS** row showing where you
sit against this ceiling, so you can see it while things still work.

> This page previously said an Intel `.dmg` "would need a second CI job" that had not
> been paid for. That job exists now (`macos-15-intel` in the build matrix) and has
> shipped Intel bundles since v2.22.0. Note that `macos-15-intel` is the **last**
> x86_64 image GitHub Actions will offer, available until **August 2027**; when it
> goes, pipx becomes the only Intel path.

## First launch — Gatekeeper bypass

Because the app is unsigned, macOS shows
*"YazSes can’t be opened because Apple cannot check it for malicious software"*
the first time you double-click the app. To get past this:

1. Open Finder → Applications.
2. **Right-click** (or Control-click) **YazSes.app** → **Open**.
3. In the dialog that appears, click **Open** again.

You only need to do this once. After that, double-clicking works normally.

> If you prefer, do the same from a terminal:
> ```sh
> xattr -dr com.apple.quarantine /Applications/YazSes.app
> open /Applications/YazSes.app
> ```

## Grant Accessibility access

YazSes listens for the dictation key (Right Option by default) using the
macOS Accessibility API. The OS gates this with a privacy prompt:

1. On first launch, YazSes triggers macOS to show an **Accessibility** prompt.
   Click **Open System Settings**.
2. In **System Settings → Privacy & Security → Accessibility**, find
   **YazSes** and **enable the toggle**.
3. Quit and reopen YazSes (the daemon picks up the new permission on next
   launch).

If the prompt didn't appear, open the pane directly:

```sh
open 'x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility'
```

## Grant Input Monitoring access — the second switch

**Accessibility on its own is not enough.** Since macOS 10.15 an app that
*watches* for a key without consuming it needs **Input Monitoring** as well, and
it is a separate service granted in a separate pane. YazSes needs both: without
Input Monitoring the dictation key does nothing at all, in every application,
while the Accessibility toggle sits there enabled.

1. Launch YazSes and **hold the dictation key once**. macOS shows an
   **Input Monitoring** prompt the first time.
2. In **System Settings → Privacy & Security → Input Monitoring**, enable
   **YazSes**.
3. **Quit and relaunch YazSes.** The grant is read when the event tap is
   created, so a running daemon will not pick it up.

Or open the pane directly:

```sh
open 'x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent'
```

> **YazSes is not in the list?** An app only appears in Input Monitoring once it
> has asked for it. Launch YazSes, hold the key once, then look again — you
> cannot add it with the `+` button before it has asked.

`yazses doctor` reports **Accessibility** and **Input monitoring** as two rows,
because they are two switches and either one being off produces the same dead
key.

## Grant Microphone access

Hold the dictation key once. The first time, macOS prompts:
*"YazSes would like to access the microphone."* Click **OK**.

> **No microphone prompt ever appeared, and YazSes is not in the Microphone
> list?** That is almost always this same problem one step upstream. macOS shows
> the microphone prompt at the moment an app first records, and YazSes only
> records while the dictation key is held — so if the key is dead for want of
> **Input Monitoring**, nothing ever records, no prompt is ever shown, and the
> app never appears in the Microphone pane. Fix Input Monitoring first, then
> hold the key again.

If you accidentally clicked **Don't Allow**, re-enable in
**System Settings → Privacy & Security → Microphone → YazSes**.

## Use it

By default, **hold Right Option** anywhere on the desktop, speak, then release.
The transcribed text appears in whatever app is focused.

The default hotkey is configurable in `~/Library/Application Support/yazses/config.toml`:

```toml
[hotkey]
# "auto" → Right Option on macOS. Other options: "right_ctrl", "left_option",
# "space", "right_shift", ...
key = "auto"
hold_threshold_ms = 500

[stt]
model = "tiny.en"   # try "base.en" for better accuracy at the cost of CPU
```

The first transcription downloads the Whisper model (~80 MB for `tiny.en`)
into `~/Library/Caches/huggingface/hub/`. Subsequent dictations are fully offline.

## Verify with the CLI

The `.app` ships a CLI alongside the tray:

```sh
/Applications/YazSes.app/Contents/MacOS/YazSes --cli doctor
/Applications/YazSes.app/Contents/MacOS/YazSes --cli status
```

(For convenience, you can symlink it: `sudo ln -s /Applications/YazSes.app/Contents/MacOS/YazSes /usr/local/bin/yazses` and then run `yazses --cli doctor`.)

## Troubleshooting

**"Accessibility is on and the hotkey does nothing."** Check **Input
Monitoring**, not Accessibility. A keyboard event tap needs both since macOS
10.15, they are granted in different panes, and Accessibility being enabled says
nothing about the other one. See
[Grant Input Monitoring access](#grant-input-monitoring-access--the-second-switch)
above, and run `yazses doctor` — it reports the two separately.

**"YazSes keeps asking for Accessibility."** macOS treats unsigned apps as
new identities each time their hash changes. After every YazSes update you
may need to re-enable the toggle. Signing (planned) will fix this.

**"Accessibility is enabled and YazSes still says it is denied."** Same cause,
worse symptom: the grant is bound to an identity the binary no longer has, so the
old entry keeps rendering as an enabled toggle while the check answers *denied*.
Turning it off and on again does not always clear it, because the stale row is not
the one the toggle edits. Remove YazSes from the list, add it back, and relaunch —
or reset the decision for this app only:

```sh
tccutil reset Accessibility com.yazses.app
```

Keep the bundle id. Without it, `tccutil` clears the Accessibility grant for
**every** application on the Mac, not just this one.

**Which YazSes is being asked about?** The Accessibility answer is about the
program that is running, not about every copy on the disk — so a grant given to
`/Applications/YazSes.app` is not automatically the thing being checked when you
run a `yazses` binary from somewhere else. `doctor` now prints the executable it
asked about; if that path is not the one you granted access to, that mismatch is
the thing to fix first.

**"The hotkey doesn't fire."** Check Accessibility is granted. Also check
that no other tool is intercepting Right Option (e.g., Karabiner-Elements,
some IME apps). Try a different hotkey by editing `config.toml`.

**"Microphone is silent."** Confirm in
*System Settings → Privacy & Security → Microphone* that YazSes is enabled.
Run `--cli doctor` to see what YazSes is detecting — the **Microphone** row now
carries the fix, not just the word `denied`.

**"Microphone says denied and I never saw a prompt."** macOS only asks the first
time an app actually records, so before your first dictation there is nothing in
the Microphone list to enable. Hold the hotkey once and answer the prompt.

**"Microphone is enabled in Settings and YazSes still says denied."** Same trap as
Accessibility above: these builds are unsigned, so macOS treats a changed binary as
a new identity and the old approval stops applying while the entry still looks on.
Reset this app's microphone decision and relaunch:

```sh
tccutil reset Microphone com.yazses.app
```

Keep the bundle id. Without it, `tccutil reset Microphone` clears the microphone
grant for **every** app on the Mac. Microphone and Accessibility are separate
services — one being granted says nothing about the other.

**"Antivirus flags YazSes."** These builds are unsigned, which trips conservative AV
heuristics. Build from source (`scripts/build-macos.sh`) if you prefer.

## Uninstall

If you installed with Homebrew, that route also removes the app, stops the
launchd agent, and (with `--zap`) clears the support files:

```sh
brew uninstall --zap --cask yazses
```

Installed from PyPI? `pipx uninstall yazses`.

For a manual `.dmg` install:

```sh
launchctl bootout gui/$(id -u)/com.yazses.daemon 2>/dev/null || true
rm -rf /Applications/YazSes.app
rm -rf ~/Library/Application\ Support/yazses
rm -rf ~/Library/Caches/yazses
rm -rf ~/Library/Logs/yazses
rm -f  ~/Library/LaunchAgents/com.yazses.daemon.plist
```

Also remove the toggle entry in
*System Settings → Privacy & Security → Accessibility*.
