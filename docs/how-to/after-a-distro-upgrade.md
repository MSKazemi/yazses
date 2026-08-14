---
title: Dictation stopped working after a distro upgrade
description: The four things a Linux release upgrade breaks for YazSes — a Python that moved under the virtualenv, a session that switched to Wayland, lost input-group access, and a stopped ydotoold — and how to tell which one you have.
---

# Dictation stopped working after a distro upgrade

A release upgrade changes four things YazSes depends on, and each produces a
different symptom. Start here rather than reinstalling:

```bash
yazses doctor
```

It reports your machine rather than the general case, and the section below matches
its output line by line.

!!! info "Verified on"

    Ubuntu 24.04 · GNOME 46 · X11 · YazSes 2.18.2 · Python 3.14. The diagnosis
    commands were run there; the upgrade itself was not performed for this page —
    see the note at the end.

## 1. The `yazses` command is gone, or crashes on import

**The most common one.** A release upgrade moves the system Python — 3.11 → 3.12,
say — and a virtualenv built against the old one keeps pointing at an interpreter
that no longer exists.

```bash
yazses --version
```

`No such file or directory`, or `ModuleNotFoundError` for something you never
installed, both mean this. The fix is to rebuild the environment, not to reinstall
the OS package:

```bash
# pipx
pipx reinstall yazses

# uv tool
uv tool upgrade --reinstall yazses

# a venv you made yourself
rm -rf .venv && uv sync
```

!!! warning "`evdev` needs a compiler, and the upgrade may have removed it"

    `evdev` publishes no wheels, so every Linux install compiles it. If the
    reinstall fails building it, install the toolchain first:
    `sudo apt install build-essential python3-dev`.

## 2. Your session switched to Wayland

Ubuntu and Fedora have both flipped the default session in a release upgrade. It
does not announce itself, and dictation *appears* to work — the daemon runs, the
model loads, transcription happens — but the text goes nowhere, because the
injector for X11 cannot type on Wayland.

```bash
echo $XDG_SESSION_TYPE
```

```
x11
```

If that now says `wayland` and it used to say `x11`, you have two options:

- **Stay on Wayland** and install the right injector:

  ```bash
  yazses setup      # installs ydotool and enables ydotoold
  ```

- **Go back to X11**: log out, click the gear icon on the login screen, choose
  *Ubuntu on Xorg*.

Two features genuinely cannot follow you to Wayland — voice window focus and
gaze routing — because one application may not focus or inspect another's window
there. That is the security model, not a regression. See the
[capability matrix](../capability-matrix.md).

## 3. You are no longer in the `input` group

Hold-to-talk reads the keyboard through evdev, which needs group access to the
device nodes:

```bash
id -nG | tr ' ' '\n' | grep -x input
ls -l /dev/input/event3
```

Real output here:

```
input
crw-rw---- 1 root input 13, 67 Aug 14 02:21 /dev/input/event3
```

`crw-rw----  root input` is the point: without membership of `input`, the device
cannot be opened at all. If the first command prints nothing:

```bash
sudo usermod -aG input "$USER"
```

**Then log out completely and back in.** Group membership is established at login;
a new terminal inherits the old set, so `yazses doctor` will keep reporting the
problem until you do. It says so when the change is pending.

## 4. `ydotoold` is not running (Wayland only)

The Wayland injector needs its daemon, and an upgrade can leave the unit disabled:

```bash
systemctl --user status ydotoold
yazses doctor | grep -i ydotool
```

```bash
yazses setup      # installs it and enables the unit
```

`wtype` is not a substitute on GNOME or KDE — those compositors do not implement
the virtual-keyboard protocol it needs, so it fails silently there.

## 5. Autostart stopped

The systemd user unit points at the console script, and a reinstall can move it:

```bash
systemctl --user status yazses
yazses doctor | grep -i "systemd unit"
```

```
  [OK] systemd unit: ExecStart=/home/mohsen/.local/bin/yazses-daemon
```

If that path no longer exists, rewrite the unit:

```bash
yazses autostart disable && yazses autostart enable
```

YazSes rewrites the unit itself when it notices an upgrade moved the binary, so
this is a fallback rather than the normal path.

## What "fixed" looks like

```bash
yazses doctor
```

```
  [OK] Keyboard capture: ok
  [OK] Hotkey device: AT Translated Set 2 keyboard (/dev/input/event3)
  [OK] Session type: X11
  [OK] Injection: xdotool (X11)
  [OK] Daemon: running (PID 4084, state idle, model base.en)

✓ Everything looks good — you're all set — hold right_ctrl to dictate.
```

## What this page does not cover

**No distribution upgrade was actually performed to write it.** Each cause is
diagnosed with commands run on a working machine, and each fix is the documented
one — but nobody upgraded 24.04 to 26.04 and watched what broke. If you do,
[say what actually happened](https://github.com/MSKazemi/yazses/issues), including
anything this page missed; that report is worth more than the page.
