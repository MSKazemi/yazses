---
title: Capability matrix — which features work on which platform
description: Hotkey capture, text injection, tray, overlay, gaze routing and voice window control across Linux X11, Linux Wayland, macOS and Windows — with the reason behind every gap.
---

# Capability matrix

Which **features** work where, taken from the backends that actually ship in
`src/yazses/platform/` and the checks `yazses doctor` runs.

!!! question "Looking for *whether it installs* on your machine?"

    This page assumes YazSes is installed and answers "does this feature work in my
    session". For operating systems, CPU architectures and install channels — including
    BSD and what happens on an OS with no backend — see
    [platform support](platform-support.md).

**Run `yazses doctor` before reading this.** It reports your machine rather than
the general case, and it names the fix for anything missing.

## The matrix

| Capability | Linux / X11 | Linux / Wayland | macOS | Windows |
|---|---|---|---|---|
| Hold-to-talk hotkey | ✅ evdev | ✅ evdev | ✅ | ✅ |
| Text injection | ✅ xdotool | ✅ ydotool¹ | ✅ | ✅ |
| Clipboard fallback | ✅ | ✅ | ✅ | ✅ |
| "No text target" guard | ✅ AT-SPI² | ✅ AT-SPI² | ⚠️ best-effort | ⚠️ best-effort |
| System tray | ✅ Qt | ✅ Qt | ✅ rumps | ✅ pystray |
| Tray input-level ring | ✅ | ✅ | ❌ see ³ | ❌ see ³ |
| Earcon state cues (eyes-free) | ✅ | ✅ | ✅ | ✅ |
| Command safety gate, check digits | ✅ | ✅ | ✅ | ✅ |
| Voice-activity overlay | ✅ | ✅ | ✅ | ✅ |
| Autostart at login | ✅ systemd | ✅ systemd | ✅ launchd | ✅ HKCU\\Run |
| Offline transcription (`transcribe`) | ✅ | ✅ | ✅ | ✅ |
| Meeting Mode, diarization | ✅ | ✅ | ✅ | ✅ |
| **Voice window focus** ("focus the browser") | ✅ xdotool | ❌ **not possible** | ❌ | ❌ |
| **Glance-Type gaze routing** | ✅ | ❌ **not possible** | ❌ | ❌ |
| EMG / BrainFlow activation | ✅ | ✅ | ✅ | ✅ |

³ The level ring is drawn by the Qt tray, which repaints on the 0.15 s recording poll.
The macOS and Windows trays render through `rumps`/`pystray` and repaint far less often,
so the ring would lag the thing it reports. The **earcons** carry the same information on
every platform, and audio is the channel that works when the tray is not being looked at
anyway.

¹ Wayland needs `ydotool` **and** a running `ydotoold`; `wtype` works only on
wlroots compositors and is blocked on GNOME and KDE. For a non-Snap install,
`yazses setup` installs and enables the right one.
² Needs `python3-pyatspi` + `gir1.2-atspi-2.0` from your package manager (not pip).
Without it the guard still works, but by best-effort window heuristics.

## Why the two ❌ rows are not bugs

**Wayland forbids one application from focusing or reading another's window.** That
is the security model working as designed, and no portal exposes the capability
today. So voice window control and look-to-pane gaze routing are X11-only, and
YazSes reports them as unavailable rather than offering a feature that silently
does nothing. Layout commands your compositor binds itself are unaffected.

Everything else on Wayland — dictation, commands, the tray, the overlay,
transcription — works normally.

## Linux: which session am I in?

```bash
echo $XDG_SESSION_TYPE      # x11 or wayland
yazses doctor               # reports the same, plus the injector it will use
```

## Known platform-specific traps

- **Linux** — hold-to-talk reads the keyboard through evdev, so a non-Snap install
  needs the `input` group and a **full logout**, not a new terminal. `yazses doctor`
  says when that is pending. The Snap instead needs its `raw-input` interface
  connected manually and supports dictation on X11 only; use the universal
  installer, APT, or `pipx` on Wayland.
- **macOS** — Accessibility and Microphone permissions are per-binary. An update
  that changes the app's identity re-prompts.
- **Windows** — an app running **as administrator** does not receive input from a
  non-elevated process (User Interface Privilege Isolation). Dictation into Task
  Manager or an elevated PowerShell silently does nothing unless YazSes is
  elevated too; `yazses doctor` reports which case you are in.

## Adding a platform

Implement the Protocol interfaces in `src/yazses/platform/<os>/` and register the
`sys.platform` value in `platform/factory.py`; the daemon and CLI need no other
change. `src/yazses/platform/bsd/` is the worked example, at about 60 lines — see
[platform support](platform-support.md#bsd--experimental) and
[the architecture guide](architecture.md).

An OS with no backend is still useful: `transcribe` and the text commands never
touch the platform layer.
