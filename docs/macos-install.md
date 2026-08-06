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

- macOS 11 (Big Sur) or later, Apple Silicon or Intel
- ~250 MB free disk for the app + the Whisper model on first download
- A microphone

## Install

1. Download `YazSes-<version>.dmg` from the
   [Releases](https://github.com/MSKazemi/yazses/releases) page.
2. Open the `.dmg`. Drag **YazSes.app** into the **Applications** folder shown
   in the Finder window.
3. Eject the `.dmg`.

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

## Grant Microphone access

Hold the dictation key once. The first time, macOS prompts:
*"YazSes would like to access the microphone."* Click **OK**.

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

**"YazSes keeps asking for Accessibility."** macOS treats unsigned apps as
new identities each time their hash changes. After every YazSes update you
may need to re-enable the toggle. Signing (planned) will fix this.

**"The hotkey doesn't fire."** Check Accessibility is granted. Also check
that no other tool is intercepting Right Option (e.g., Karabiner-Elements,
some IME apps). Try a different hotkey by editing `config.toml`.

**"Microphone is silent."** Confirm in
*System Settings → Privacy & Security → Microphone* that YazSes is enabled.
Run `--cli doctor` to see what YazSes is detecting.

**"Antivirus flags YazSes."** These builds are unsigned, which trips conservative AV
heuristics. Build from source (`scripts/build-macos.sh`) if you prefer.

## Uninstall

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
