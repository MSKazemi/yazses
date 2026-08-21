---
title: Offline voice dictation on Linux — speech to text on X11 and Wayland
description: How to get working voice typing on Linux without the cloud. Offline speech-to-text that types into any application on both X11 and Wayland, with a hold-to-talk hotkey, running locally on CPU.
---

# Offline voice dictation on Linux

**Short answer:** Linux has no built-in dictation comparable to Windows Speech
Recognition or macOS Dictation. YazSes fills that gap with hold-to-talk voice
typing that runs entirely on your own CPU, works on **both X11 and Wayland**, and
types into any focused application — editor, browser, terminal or chat.

```sh
sudo snap install yazses    # or: pipx install yazses
yazses doctor               # check mic, keyboard access and text injection
yazses enroll               # calibrate to your voice and room (~30 s)
yazses start                # hold the hotkey, speak, release
```

## Why Linux dictation is usually hard

Three separate problems have to be solved, and most tools only solve one:

| Problem | What it means | How YazSes handles it |
|---|---|---|
| **Recognition** | Turning audio into text without a cloud API | On-device [faster-whisper](https://github.com/SYSTRAN/faster-whisper), CPU int8 — no GPU, no network |
| **Triggering** | Detecting a held key globally, across every window | Reads keyboard events directly, and listens on **all** connected keyboards (laptop + external) |
| **Injection** | Getting text *into* the focused app — the part Wayland broke | Runtime probe picks `ydotool`, `wtype`, `xdotool` or clipboard paste |

That third row is the one that trips up most Linux dictation projects. Wayland
deliberately prevents one application from synthesising input into another, so
tools built for X11's `xdotool` simply stop working.

## X11 and Wayland

YazSes probes your session at runtime and selects a working injection backend
rather than assuming one:

- **X11** — `xdotool`. Works out of the box on most distributions.
- **Wayland (GNOME, KDE, sway)** — `ydotool` (via the `ydotoold` daemon) or
  `wtype`. `yazses setup` provisions these for you; `yazses doctor` tells you
  which backend was selected and whether it is functional.

You can pin the choice explicitly if the automatic probe picks badly:

```toml
[injection]
backend = "auto"   # auto | type | clipboard | wtype
```

On Wayland, typing (rather than clipboard pasting) is the default because it also
works inside terminal emulators, where clipboard paste is frequently a no-op.

!!! note "Terminals"
    If text appears in your editor but not in your terminal, you are almost
    certainly on a clipboard backend. Switch to `type`. See
    [troubleshooting](../troubleshooting.md).

## Distributions

Installation is covered in detail in the [Linux install guide](../install-linux.md).
In brief:

=== "Ubuntu / Debian"

    ```sh
    bash <(curl -fsSL https://raw.githubusercontent.com/MSKazemi/yazses/main/install-apt.sh)
    ```

=== "Any distro (snap)"

    ```sh
    sudo snap install yazses
    ```

=== "Any distro (pipx)"

    ```sh
    pipx install yazses
    ```

!!! warning "Two Linux-specific gotchas"
    - `libportaudio2` is required for microphone capture and is **not** pulled in
      by pipx. Install it from your package manager if `yazses start` fails
      immediately.
    - Reading the keyboard needs membership of the `input` group. After
      `sudo usermod -aG input $USER` you must **log out and back in** for it to
      take effect.

    `yazses doctor` checks both and tells you exactly which one is missing.

## What "offline" actually means here

The model is downloaded once at install time. After that, dictation works with
the network cable unplugged. No audio, no transcript, and no telemetry leave the
machine — see the [privacy statement](../privacy-statement.md) for the specifics
of what is stored and where.

This matters beyond privacy preference: it means dictation keeps working on a
train, on a plane, on a locked-down corporate network, and on air-gapped
machines. See [private offline dictation](private-offline-dictation.md).

## Beyond typing

Once dictation works, the same daemon also recognises voice commands — *"undo
that"*, *"save file"*, *"go to line 42"* — mapped to real key sequences by a fast
regex grammar. Browse everything available with:

```sh
yazses features            # 139 capabilities, what's on, what's recommended
yazses features info code  # what one capability does, with an example
```

## Where it falls short on Linux

- **Wayland window control is limited.** Anything that needs to *focus* another
  window (such as the experimental Glance-Type gaze targeting) works on X11 only,
  because Wayland does not permit it.
- **No GPU acceleration path** is configured by default — YazSes targets CPU int8
  so it runs on modest hardware. If you have a strong GPU and want maximum speed,
  a `whisper.cpp`-based tool may transcribe faster.
- **Voice scripting is not the goal.** If you want to program your desktop with a
  deep voice-scripting ecosystem, see Talon in the
  [comparison](../comparison.md).

## Related

- [Install on Linux](../install-linux.md) — full step-by-step guide
- [Change the hotkey](../how-to/change-hotkey.md)
- [Troubleshooting](../troubleshooting.md) — no text appearing, mic issues
- [Comparison with Dragon, Talon, nerd-dictation and others](../comparison.md)
- [YazSes vs nerd-dictation](../compare/yazses-vs-nerd-dictation.md) — with a migration guide
- [Accessibility & RSI use](accessibility-rsi-hands-free.md)
