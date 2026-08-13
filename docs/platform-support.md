---
title: Platform support matrix
description: What works on Linux (X11 and Wayland), macOS and Windows — hotkey capture, text injection, tray, overlay, gaze and voice window control, with the reason behind every gap.
---

# Platform support

Support status was scattered across the install and troubleshooting pages. This is
the consolidated answer, taken from the backends that actually ship in
`src/yazses/platform/` and the checks `yazses doctor` runs.

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
| Voice-activity overlay | ✅ | ✅ | ✅ | ✅ |
| Autostart at login | ✅ systemd | ✅ systemd | ✅ launchd | ✅ HKCU\\Run |
| Offline transcription (`transcribe`) | ✅ | ✅ | ✅ | ✅ |
| Meeting Mode, diarization | ✅ | ✅ | ✅ | ✅ |
| **Voice window focus** ("focus the browser") | ✅ xdotool | ❌ **not possible** | ❌ | ❌ |
| **Glance-Type gaze routing** | ✅ | ❌ **not possible** | ❌ | ❌ |
| EMG / BrainFlow activation | ✅ | ✅ | ✅ | ✅ |

¹ Wayland needs `ydotool` **and** a running `ydotoold`; `wtype` works only on
wlroots compositors and is blocked on GNOME and KDE. `yazses setup` installs and
enables the right one.
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

- **Linux** — hold-to-talk reads the keyboard through evdev, so your user must be
  in the `input` group, and the change needs a **full logout**, not a new
  terminal. `yazses doctor` says when that is pending. The Snap **cannot** do
  hold-to-talk at all: strict confinement blocks raw reads of `/dev/input/event*`
  and there is no interface to grant it — install with `pipx`/`uv tool` instead.
- **macOS** — Accessibility and Microphone permissions are per-binary. An update
  that changes the app's identity re-prompts.
- **Windows** — an app running **as administrator** does not receive input from a
  non-elevated process (User Interface Privilege Isolation). Dictation into Task
  Manager or an elevated PowerShell silently does nothing unless YazSes is
  elevated too; `yazses doctor` reports which case you are in.

## Adding a platform

Implement the Protocol interfaces in `src/yazses/platform/<os>/` and register the
`sys.platform` value in `platform/factory.py`; the daemon and CLI need no other
change.

An OS with no backend is still useful: `transcribe` and the text commands never
touch the platform layer.
