---
title: Install offline voice dictation on Linux (Ubuntu, Debian, Fedora, Arch)
description: Step-by-step install of YazSes offline voice dictation on Linux — apt, snap or pipx, microphone calibration, hotkey setup, and text injection on both X11 and Wayland.
---

# Installing YazSes on Linux

This guide installs the Python daemon as a global command and starts it
automatically at login. It targets the reliable batch (transcribe-on-release)
configuration. Tested on X11 + PipeWire.

## 1. Prerequisites

**The easy way — one command does all of this:**

```bash
yazses setup    # installs deps, joins the input group, sets up ydotoold (Wayland)
# then log out and back in (the input-group change needs a fresh login)
```

`yazses setup` is idempotent (safe to re-run) and provisions everything below
automatically. It finishes by printing a numbered **"finish installing" checklist**
of the steps only you can do — join the `input` group, log out and back in,
calibrate your voice (`yazses mic-level --set`), and `yazses start` — and offers
to run the mic calibration for you there and then. The rest of this section
explains what it does, for when you want to do it by hand or understand the
pieces. Verify anytime with `yazses doctor` (want `[OK] Keyboard capture`,
`[OK] Microphone`, `[OK] Injection`).

```bash
yazses doctor   # after install: checks injection backend, mic, input group, ydotoold
```

**Manual route — install every runtime dependency in one command** (the APT
`.deb` pulls these in automatically, so skip this if you used `install-apt.sh`):

```bash
sudo apt install libportaudio2 xdotool ydotool wtype xclip wl-clipboard pipx
```

What each is for:

| Package | Role | Needed when |
|---|---|---|
| `libportaudio2` | Audio capture — `sounddevice` loads it at import | **Always** (else the daemon crashes on start: `OSError: PortAudio library not found`) |
| `xdotool` | Text injection (X11) | X11 sessions |
| `xclip` | Clipboard fallback (X11) | X11 sessions |
| `wtype` / `ydotool` | Text injection (Wayland) | Wayland sessions |
| `wl-clipboard` | Clipboard fallback (Wayland) — provides `wl-copy` | Wayland sessions |
| `pipx` | Installs the `yazses` CLI | If installing via `pipx` |

Installing all of them makes YazSes work whether you log into X11 or Wayland —
at runtime YazSes auto-selects the right backend (`inject/auto.py`). You also
need membership in the **`input`** group (step 1a) and a working microphone
(PipeWire/PulseAudio/ALSA).

### 1a. Add yourself to the `input` group (required)

The hold-to-talk hotkey is read directly from the kernel input devices
(`/dev/input/event*`), which are owned by the `input` group. If your user is not
in that group the daemon **cannot detect the hotkey** and dictation never starts
(`yazses doctor` reports `[FAIL] Keyboard capture: denied`).

```bash
sudo usermod -aG input "$USER"   # add yourself to the input group
```

Then **log out and back in (or reboot)** — group membership only refreshes on a
new login session. **Opening another terminal tab is not enough**: it inherits
the old session's groups, so the hotkey stays dead and `yazses doctor` still
reports `[FAIL] Keyboard capture` (that line reflects the shell running doctor,
not a running daemon). Confirm it took effect:

```bash
id -nG | tr ' ' '\n' | grep -x input   # should print: input
yazses doctor                          # should show [OK] Keyboard capture
```

Do this **before** starting the daemon (step 3). `yazses start`/`restart` will
warn you if this re-login is still pending. To dictate **immediately** without
logging out, bridge the group for one session:

```bash
sg input -c "yazses restart"           # runs the daemon with input-group access now
```

After a real re-login, a plain `yazses start` just works — no bridge needed.

### 1b. Wayland keystroke injection — `ydotoold` (GNOME/KDE Wayland)

How text gets typed depends on your session:

| Session | Injector | Notes |
|---|---|---|
| X11 | `xdotool` | works out of the box |
| Wayland — wlroots (Sway, Hyprland, …) | `wtype` | works out of the box |
| **Wayland — GNOME / KDE** | **`ydotool` + `ydotoold`** | `wtype` is **blocked** by Mutter/KWin; `ydotool` injects at the kernel `/dev/uinput` level and is the only reliable option |

On GNOME/KDE Wayland you must run the `ydotoold` daemon, or injection fails with
`failed to connect socket … .ydotool_socket`. `yazses setup` configures this for
you; to do it manually, install the user service:

```bash
mkdir -p ~/.config/systemd/user
cp /usr/lib/systemd/user/ydotoold.service ~/.config/systemd/user/ 2>/dev/null \
  || curl -fsSL https://raw.githubusercontent.com/MSKazemi/yazses/main/contrib/ydotoold.service \
       -o ~/.config/systemd/user/ydotoold.service
systemctl --user daemon-reload
systemctl --user enable --now ydotoold.service
ls -l /run/user/$(id -u)/.ydotool_socket   # socket should now exist
```

`ydotoold` runs as your user (no root) because `/dev/uinput` is owned by the
`input` group (step 1a). After this, `yazses doctor` shows `[OK] Injection` and
`[OK] ydotoold`.

## 2. Install the CLI globally

The project ships as a Python package. Install it isolated so `yazses` works
from anywhere. Either tool works — `uv tool` if you already use `uv`, otherwise
`pipx`:

```bash
# Option A — uv (recommended if uv is installed)
uv tool install --force /path/to/yazses

# Option B — pipx
pipx install /path/to/yazses
```

This installs four commands: `yazses`, `yazses-daemon`, `yazses-tray`,
`yazses-agent` into `~/.local/bin` (make sure that's on your `PATH`).

> If an old `alias yazses=...` exists in your shell rc pointing at a previous
> build, remove it so the installed binary is used.

## 3. Start at login (systemd user service)

Create `~/.config/systemd/user/yazses.service`:

```ini
[Unit]
Description=YazSes offline voice dictation daemon
After=graphical-session.target
PartOf=graphical-session.target

[Service]
Type=simple
ExecStart=%h/.local/bin/yazses-daemon
Restart=on-failure
RestartSec=2
# X11 injection (xdotool) needs the display + auth cookie of the active session.
# Match these to your session — check with: echo $DISPLAY ; echo $XAUTHORITY
Environment=DISPLAY=:1
Environment=XAUTHORITY=/run/user/1000/gdm/Xauthority
Environment=PATH=%h/.local/bin:/usr/local/bin:/usr/bin:/bin

[Install]
WantedBy=default.target
```

Enable and start it:

```bash
systemctl --user daemon-reload
systemctl --user enable --now yazses.service
systemctl --user status yazses.service     # should be "active (running)"
```

> **Important:** `DISPLAY`/`XAUTHORITY` must match your live session or injected
> text goes nowhere. On X11 they are usually `:0`/`:1` and a GDM `Xauthority`
> path. On Wayland, set `WAYLAND_DISPLAY` instead and use `ydotool`/`wtype`.

## 4. Use it

1. Focus any text field.
2. Hold the hotkey (default `right_alt`), speak, release.
3. The transcript types in once.

```bash
yazses status      # state, hotkey, model, backend
yazses logs        # recent diagnostic log (metadata only)
```

## 5. Tune the silence threshold

If dictation does nothing and `yazses logs` shows `Silent audio -- discarding`,
your speech is below the VAD gate. Measure and set it:

```bash
yazses mic-level --set      # records ~4s; writes a fitting vad_threshold
systemctl --user restart yazses.service
```

Re-run whenever your speaking volume changes (e.g. quiet late-night dictation).

## 6. Manage the service

```bash
systemctl --user restart yazses.service    # after a config change
systemctl --user stop yazses.service       # stop
systemctl --user disable --now yazses.service   # stop + remove autostart
journalctl --user -u yazses.service -f     # live logs via journald
```

Config lives at `~/.config/yazses/config.toml`. See the
[CLI reference](cli-reference.md) for all commands.

## 7. Troubleshooting: the hotkey does nothing

If holding the key records nothing (no transcript, no overlay reaction), run the
health check first — it now pinpoints every common cause in one shot:

```bash
yazses doctor
```

Look for these lines and act on any that are not `[OK]`:

- **`Hotkey device: bound to virtual device …`** — the daemon is listening on an
  injector's virtual device (e.g. `ydotoold virtual device`) instead of your real
  keyboard, so your keypresses are never seen. Make sure you are in the `input`
  group (`groups | grep input`; if missing, [§1a](#1a-add-yourself-to-the-input-group-required),
  then log out and back in) so the real keyboard is readable. Fixed in v1.3.3+,
  which skips virtual devices automatically; older builds need an upgrade.
- **`systemd unit: ExecStart=… does not exist`** — the service points at a binary
  that isn't there (a leftover from a different install method), so it crash-loops
  with `status 203/EXEC` and `yazses start`/`restart` silently start nothing. Point
  the unit's `ExecStart` at your real binary (`which yazses-daemon`) and
  `systemctl --user daemon-reload && systemctl --user restart yazses`.
- **`Install: multiple yazses on PATH …`** — you have more than one copy installed
  (e.g. apt + pipx + uv tool). Keep one and uninstall the rest so an upgrade can't
  leave you running stale code: `pipx uninstall yazses`, `sudo apt remove yazses`,
  or `uv tool uninstall yazses` as appropriate.
- **`Keyboard capture: FAIL`** — you are not in the `input` group; see
  [§1a](#1a-add-yourself-to-the-input-group-required).

If `yazses logs` shows `Silent audio -- discarding`, the key *is* working but your
speech is below the VAD gate — see [§5](#5-tune-the-silence-threshold).

> **Tip:** manage the daemon with `systemctl --user restart yazses` when a systemd
> unit exists; mixing `yazses start` (detached) with a systemd unit can leave two
> daemons fighting over the hotkey, or none running at all.

## 8. Voice-activity overlay

The overlay draws neon "sonar" rings near the cursor that pulse with your voice
while you dictate. It is **on by default** and works out of the box: PySide6 is
part of the base install (and bundled in the snap), so there is no extra step.
The PySide6 wheels need glibc ≥ 2.28 (Ubuntu 20.04+); on older distros the
daemon logs a one-line hint and keeps dictating.

The daemon then auto-launches `yazses-overlay` on start when a display is present
and terminates it on shutdown. If PySide6 isn't installed the daemon logs a
one-line hint and keeps dictating — nothing breaks. To turn the overlay off, set
`[overlay] enabled = false` in `~/.config/yazses/config.toml`. Run `yazses
overlay` yourself to preview it.

**Transparency note (X11):** the see-through glow needs a compositing window
manager. If you run a bare WM without one, install `picom`:

```bash
sudo apt install picom && picom -b      # or enable your DE's compositor
```

Without a compositor the rings still render, just on a small opaque panel.

To autostart it as its own user service instead of letting the daemon spawn it,
create `~/.config/systemd/user/yazses-overlay.service` with
`ExecStart=%h/.local/bin/yazses-overlay`, `Environment=DISPLAY=:0`, and
`After=yazses.service`, then `systemctl --user enable --now yazses-overlay`.
