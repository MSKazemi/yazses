---
title: "Voice dictation on Wayland — GNOME, KDE Plasma, sway and Hyprland"
description: "Offline voice typing that actually works on Wayland. Why Wayland breaks most Linux dictation tools, which injection backend to use on each compositor, and how to fix it when text does not appear."
---

# Voice dictation on Wayland

**Short answer:** Wayland deliberately blocks one application from typing into
another, which is why most Linux dictation tools silently stop working after a
switch from X11. YazSes gets around it with `ydotool`, which injects at the
kernel `uinput` layer instead of through the display server — so dictated text
lands in GNOME, KDE Plasma, sway and Hyprland, terminals included.

```sh
bash <(curl -fsSL https://raw.githubusercontent.com/MSKazemi/yazses/main/install.sh)
yazses doctor                # reports your session type and which backend was picked
yazses start                 # hold the hotkey, speak, release
```

!!! warning "Do not use the Snap on Wayland"
    Strict confinement prevents the Snap from configuring or using the host
    `ydotoold` service required for reliable keystroke injection. The Snap is a
    supported dictation install on X11 only. Running `yazses setup` inside it
    cannot remove that limitation.

## Why does dictation break on Wayland?

Because X11 let any client synthesise input into any window, and Wayland closed
that hole on purpose. It is a security fix, not a bug. Every tool built on
`xdotool` inherited the assumption and breaks the moment the session becomes
Wayland — usually with no error message, because the injection call succeeds and
the keystrokes simply go nowhere.

Ubuntu has defaulted to Wayland since 22.04 and Fedora since 25, so this is now
the default case on Linux, not the exception.

Check which session you are in:

```sh
echo $XDG_SESSION_TYPE     # -> wayland  or  x11
```

## Which injection backend works on which compositor?

YazSes probes the session at runtime and picks a backend rather than assuming
one. `yazses doctor` prints the choice and whether it is functional.

| Backend | Mechanism | GNOME | KDE Plasma | sway / Hyprland | Types into terminals? |
|---|---|---|---|---|---|
| **`ydotool`** *(default on Wayland)* | Kernel `uinput` virtual keyboard — below the compositor | ✅ | ✅ | ✅ | ✅ |
| `wtype` | `virtual-keyboard-v1` Wayland protocol | ❌ *(GNOME does not implement the protocol)* | ✅ | ✅ | ✅ |
| `clipboard` | Copies text, sends paste | ✅ | ✅ | ✅ | ❌ *(terminals use a different paste binding)* |
| `xdotool` | X11 `XTEST` | X11 only | X11 only | X11 only | ✅ |

The practical consequence: **`ydotool` is the only backend that works on all
four compositors including GNOME**, which is why it is the default. `wtype` is
cleaner but GNOME has declined to implement `virtual-keyboard-v1`, so it is not
a general answer.

Pin a backend explicitly if the probe picks badly:

```toml
# ~/.config/yazses/config.toml
[injection]
backend = "wtype"     # auto | type | clipboard | wtype
```

## How do I set up ydotool?

`ydotool` needs a running daemon and access to `/dev/uinput`. `yazses setup`
provisions both:

```sh
yazses setup      # installs ydotool, enables ydotoold, fixes uinput permissions
yazses doctor     # confirms the backend is functional
```

If you prefer to do it by hand, the daemon must be running and your user needs
write access to `/dev/uinput` — typically via a `udev` rule and group membership,
followed by a re-login so the new group takes effect.

## Does the hotkey work on Wayland?

Yes. The hold-to-talk key is read from the kernel input layer (`evdev`), not from
the compositor, so a global hotkey works on Wayland without a per-desktop
shortcut extension. YazSes listens on **all** connected keyboards, so an external
keyboard works alongside the laptop one.

This does mean your user needs to be in the `input` group:

```sh
sudo usermod -aG input "$USER"   # then log out and back in
```

## What still does not work on Wayland?

Being straight about the limits, because they are real:

| Feature | Wayland | Why |
|---|---|---|
| Dictation into any app | ✅ | `ydotool` injects below the compositor |
| Global hold-to-talk hotkey | ✅ | Read from `evdev`, not the compositor |
| Voice commands / key sequences | ✅ | Same injection path |
| Meeting Mode, file transcription | ✅ | No injection involved |
| **Glance-Type (look-to-pane targeting)** | ❌ **X11 only** | Wayland gives no client the ability to focus another application's window |

Glance-Type stays dormant on Wayland rather than half-working. If gaze-directed
window targeting matters to you today, that specific feature needs an X11
session.

## Text still is not appearing — what now?

Work down this list; `yazses doctor` answers most of it for you.

1. **Confirm the session** — `echo $XDG_SESSION_TYPE` should say `wayland`.
2. **Confirm the backend** — `yazses doctor` reports which injector was selected
   and whether it passed its functional check.
3. **Is `ydotoold` running?** — `systemctl status ydotoold`. Without the daemon,
   `ydotool` fails silently.
4. **`/dev/uinput` permissions** — the daemon needs write access; `yazses setup`
   fixes this.
5. **Nothing recorded at all?** — that is a microphone problem, not a Wayland
   one. Run `yazses mic-level --set`, which measures your room and writes a
   working voice-activity threshold.
6. **Still stuck** — `yazses verify` runs the whole chain (capture → silence gate
   → transcription → injection) and names the *first* broken link rather than
   cascading errors.

See [troubleshooting](../troubleshooting.md) for the full matrix.

## How does this compare to other Wayland dictation tools?

| Tool | Wayland | Offline | Platforms | Notes |
|---|---|---|---|---|
| **YazSes** | ✅ `ydotool` | ✅ always | Linux, macOS, Windows | Also does file transcription and meeting capture in one install |
| Vocalinux | ✅ | ✅ | Linux only | Vulkan GPU acceleration; larger community |
| nerd-dictation | ⚠️ via `ydotool`/`wtype` | ✅ | Linux only | Single Python file, no background process — minimal by design |
| VOXD | ✅ | ✅ | Linux only | Wayland-focused |
| Hyprvoice | ✅ | mixed | Linux only | Hyprland-oriented; cloud and local models |

Where the others win: **nerd-dictation** is far smaller if you want a script
rather than a daemon, and **Vocalinux** has GPU acceleration and many more users.
YazSes's distinct claims are being **cross-platform** and covering dictation,
[file transcription](transcribe-audio-offline.md) and
[meeting capture](../meeting-notes-offline.md) from one install.

Full breakdown: [comparison and alternatives](../comparison.md).

## Accuracy and speed on CPU

Wayland changes nothing about recognition quality — the same on-device model
runs either way. Measured word error rate on LibriSpeech `test-clean`, int8 on a
laptop CPU with no GPU:

| Model | WER | Decode (median) |
|---|---|---|
| `tiny.en` | 4.82 % | 0.89 s |
| `base.en` *(default)* | 4.07 % | 1.56 s |
| `small.en` | **2.59 %** | 5.05 s |

Method, hardware and reproduction commands: [benchmarks](../benchmarks.md).

## Next steps

- [Install on Linux](../install-linux.md) — distribution-by-distribution
- [Change the hotkey](../how-to/change-hotkey.md)
- [Troubleshooting](../troubleshooting.md)
- [Voice dictation on Linux](voice-dictation-linux.md) — the X11 side of the story
