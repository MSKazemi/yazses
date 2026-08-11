---
title: Troubleshooting
description: Known problems and fixes for YazSes — daemon won't start, dead hotkey, no text typed, silent audio, lost words, double typing, snap limits, and macOS/Windows permissions.
---

# Troubleshooting

This page collects the real, documented problems users hit with YazSes and their
exact fixes. Each entry is **Symptom → Cause → Fix**.

## First: run `yazses doctor`

Before anything else, run the built-in health check. It diagnoses almost every
problem on this page in one shot — missing audio library, `input`-group
membership, injection backend readiness, which keyboard the hotkey binds to,
whether the STT model is downloaded, a stale/duplicate install, and (with
`--mic`) your microphone level versus the silence gate.

```sh
yazses doctor          # full health check; act on any line that is not [OK]
yazses doctor --mic    # also records a short ambient clip and checks it vs the VAD gate
```

Read the **bottom-line verdict** it prints:

- `✓ Everything looks good` — you're set; hold the hotkey and dictate.
- `▲ Good to go (… optional warnings)` — dictation works; the warnings are optional.
- `✗ N problems to fix` — fix the `[FAIL]` lines above, then re-run `yazses doctor`.

If `yazses quickstart` looks more helpful, run that — it's a read-only, 3-step
guide tailored to your machine and changes nothing.

See also: [Install on Linux](../docs/install-linux.md) · [Configuration reference](../docs/configuration.md).

---

## Startup and installation

### Daemon won't start / crashes immediately

**Symptom** — `yazses start` prints "started" but nothing works; the daemon is
not actually running. `yazses logs` / journald show `OSError: PortAudio library
not found`. `yazses doctor` shows the daemon as not running.

**Cause** — The `libportaudio2` system library is missing. `sounddevice` loads
it at import time, so the daemon aborts on startup. The APT `.deb` pulls this in
automatically, but the `pipx`, `uv tool`, and snap paths do not — so a plain
`pip`/`pipx` install can crash on first start while `yazses start` still reports
success.

**Fix** — Install the library (and the rest of the runtime deps), then restart:

```sh
sudo apt install libportaudio2       # the one that fixes the crash
yazses restart
```

Or let `yazses setup` install every runtime dependency for you (safe to re-run):

```sh
yazses setup
```

### `yazses start` / `restart` starts nothing (systemd `203/EXEC`)

**Symptom** — `yazses start` or `restart` appears to succeed, but no daemon runs
and the hotkey is dead. `yazses doctor` shows
`systemd unit: ExecStart=… does not exist`.

**Cause** — A leftover systemd user unit points its `ExecStart` at a binary that
no longer exists (a leftover from a different install method), so the service
crash-loops with `status 203/EXEC` and swallows the start.

**Fix** — Point the unit at your real binary and reload:

```sh
which yazses-daemon                                   # find the real path
# edit ~/.config/systemd/user/yazses.service so ExecStart=<that path>
systemctl --user daemon-reload
systemctl --user restart yazses
```

### Multiple `yazses` installs / running stale code

**Symptom** — Fixes or upgrades don't seem to take effect. `yazses doctor` shows
`Install: multiple yazses on PATH …`.

**Cause** — More than one copy is installed (e.g. apt **and** pipx **and** uv
tool). An upgrade can leave you running an older copy.

**Fix** — Keep one, remove the rest:

```sh
pipx uninstall yazses          # or
sudo apt remove yazses         # or
uv tool uninstall yazses
```

---

## The hotkey does nothing

### Keyboard capture fails — not in the `input` group

**Symptom** — Holding the key records nothing (no transcript, no overlay). `yazses
doctor` reports `[FAIL] Keyboard capture: denied`.

**Cause** — The hold-to-talk hotkey is read directly from the kernel input
devices (`/dev/input/event*`), which are owned by the `input` group. If your user
isn't in that group the daemon cannot see the hotkey.

**Fix** — Join the group, then **log out and back in** (or reboot):

```sh
sudo usermod -aG input "$USER"
# now LOG OUT and back in — a new terminal tab is NOT enough
id -nG | tr ' ' '\n' | grep -x input     # should print: input
yazses doctor                            # should show [OK] Keyboard capture
```

The re-login is mandatory and one-time — group membership only refreshes in a
**new login session**; opening another terminal tab inherits the old session's
groups and the hotkey stays dead. To dictate **immediately** without logging out,
bridge the group for one session:

```sh
sg input -c "yazses restart"             # runs the daemon with input-group access now
```

After a real re-login, a plain `yazses start` just works — no bridge needed. See
[Install on Linux §1a](../docs/install-linux.md#1a-add-yourself-to-the-input-group-required).

### Hotkey bound to a virtual device

**Symptom** — Keyboard capture looks granted, but the hotkey still does nothing.
`yazses doctor` reports `Hotkey device: bound to virtual device …` (e.g.
`ydotoold virtual device`).

**Cause** — The daemon bound to an injector's virtual `uinput` device instead of
your real keyboard. That device only ever carries synthetic events, so your real
keypresses are never seen. This tends to appear after `yazses setup` provisions
`ydotoold`.

**Fix** — Ensure your real keyboard is readable (you are in the `input` group,
per the previous entry) and upgrade YazSes. v1.3.3+ skips virtual/injection
devices automatically and prefers a full keyboard; older builds need the upgrade:

```sh
pipx upgrade yazses      # or: uv tool install --force <path> / apt upgrade
yazses restart
yazses doctor            # Hotkey device should now name your real keyboard
```

### First word(s) of dictation lost

**Symptom** — The beginning of what you say is clipped — the first one to three
words don't get transcribed.

**Cause** — A short lead-in of silence is prepended before decode so
faster-whisper doesn't clip the onset. If that padding is too short for your
speaking style, the first word can still be lost.

**Fix** — Increase the pre-speech padding in `~/.config/yazses/config.toml`
(default `300` ms), then restart:

```toml
[accessibility]
pre_speech_padding_ms = 400   # widen the silence lead-in before decode
```

```sh
yazses restart
```

(Dysfluency-Friendly Mode already widens this onset padding automatically when
enabled.)

---

## Nothing gets typed (injection fails)

### No text appears after you speak

**Symptom** — Transcription happens (you may see the overlay react), but no text
lands in the focused app. `yazses doctor` shows an `Injection` line that is not
`[OK]`.

**Cause** — The right injection backend for your session isn't available or
running. How text gets typed depends on the session type:

| Session | Injector | Notes |
|---|---|---|
| X11 | `xdotool` | works out of the box |
| Wayland — wlroots (Sway, Hyprland, …) | `wtype` | works out of the box |
| **Wayland — GNOME / KDE** | **`ydotool` + a running `ydotoold`** | `wtype` is **blocked** by Mutter/KWin; `ydotool` is the only reliable option |

On GNOME/KDE Wayland, `ydotool` also needs the `ydotoold` daemon running, or it
fails with `failed to connect socket … .ydotool_socket`.

**Fix** — Let `yazses setup` install and enable the correct backend
(including `ydotoold` on GNOME/KDE Wayland):

```sh
yazses setup
yazses doctor      # want [OK] Injection (and [OK] ydotoold on GNOME/KDE Wayland)
```

To set it up by hand on GNOME/KDE Wayland, enable the `ydotoold` user service —
see [Install on Linux §1b](../docs/install-linux.md#1b-wayland-keystroke-injection--ydotoold-gnomekde-wayland).

### `xdotool` present but injection fails (missing `libxdo.so.3`)

**Symptom** — On X11, nothing is typed even though `xdotool` is installed.
`yazses doctor` warns that `xdotool` is present but not runnable
(missing `libxdo.so.3`).

**Cause** — The `xdotool` binary is on `PATH` but its shared library
(`libxdo.so.3`) is missing — every `type()` exits with a loader error and
injection silently fails (common in a broken/partial bundle).

**Fix** — Reinstall/upgrade the package so the library is present:

```sh
sudo apt install --reinstall xdotool libxdo3
yazses doctor      # Injection should return to [OK]
```

### Clipboard backend types nothing in a terminal

**Symptom** — With `[injection] backend = "clipboard"`, dictation works in GUI
apps but a terminal receives nothing (or a literal `^V`), and your clipboard gets
overwritten.

**Cause** — The `clipboard` backend pastes with Ctrl+V. In a terminal Ctrl+V is
literal (not paste), so it's a no-op there, and it overwrites whatever you had
copied.

**Fix** — Use the default `auto` backend, which **types** the text (works
everywhere, terminals included) and never touches the clipboard:

```toml
[injection]
backend = "auto"   # auto | xdotool | ydotool | wtype | clipboard
```

```sh
yazses restart
```

`backend` values: `auto` (recommended), `xdotool`/`ydotool`/`wtype` to force a
specific typing backend, or `clipboard` only when you specifically want paste.

---

## Audio and recognition

### `Silent audio -- discarding` in the logs

**Symptom** — Dictation does nothing. `yazses logs` shows
`Silent audio -- discarding`.

**Cause** — Your speech fell below the VAD (voice-activity) gate — the daemon
treats the recording as silence and drops it. The gate compares the mean
absolute audio level against `accessibility.vad_threshold`.

**Fix** — Measure your voice and write a fitting threshold, then restart:

```sh
yazses mic-level --set     # records ~4s; writes a fitting vad_threshold
yazses restart
```

Lower `vad_threshold` for quiet speech; raise it if room noise triggers spurious
transcripts. Re-run whenever your speaking volume changes (e.g. quiet late-night
dictation). You can also edit it directly:

```toml
[accessibility]
vad_threshold = 0.0008     # lower for quiet speech, higher for a noisy room
```

`yazses doctor --mic` warns when your resting room level already meets or exceeds
the threshold (which would leak noise through as spurious transcripts).

### Dictation stopped after plugging in a monitor / dock / headset

**Symptom** — Dictation was working, then stopped writing after you connected a
USB-C monitor, a docking station, or a headset. It may have worked for a while
first. `yazses logs` shows repeated `Silent audio -- discarding`.

**Cause** — Capture follows the OS **default input device**. Plugging in a monitor
or dock that carries an audio endpoint can make PulseAudio/PipeWire silently
re-pick *that* as the default input — usually a dead or very quiet source — so
every clip falls below the VAD gate and is discarded. Nothing crashes; the OS just
switched your mic out from under the daemon (and it often only flips a little while
after you plug in, which is why it "worked for a moment").

**Fix** — See which mic is in use and pin your real one:

```sh
yazses audio status              # pinned vs OS-default mic + live capture health
yazses audio devices             # ● = OS default, ★ = pinned
yazses audio use "AT Translated" # pin your built-in/real mic by name (substring)
yazses restart
```

The **mic-change guard** (on by default) also catches this automatically: it
notices the device change / run of silent clips, **auto-heals** by switching
capture back to the last mic that worked, and pops a desktop notification with
**Re-calibrate / Pin this mic / Ignore** buttons. Turn it off with
`yazses features disable mic-guard` if you don't want the notifications.

### I dictated but nothing was typed (no text field focused)

**Symptom** — You hold the key, the sonar/tray shows you're recording, you speak and
release — but no text appears. The tray icon was **yellow** (not green) while you spoke.

**Cause** — There was no editable text field focused, so there was nowhere to type. This is
the most common "it heard me but typed nothing" case: you need to click into a text box
*before* dictating.

**What YazSes does** — With the **text-target guard** (on by default), instead of typing
into the wrong place it turns the tray icon **yellow** and **copies your dictation to the
clipboard** + notifies you. Click into a text field and **paste with Ctrl+V** — your words
aren't lost. Fix it going forward by clicking into the field first.

For **precise** detection (so it also catches "app focused but no field", not just
"no window at all"), install the accessibility bridge:

```sh
sudo apt install python3-pyatspi gir1.2-atspi-2.0
yazses restart
```

`yazses doctor` shows whether the guard is running in AT-SPI (precise) or best-effort mode.
Change the behaviour with `[injection] target_guard` (`clipboard` default | `warn` — notify
but still type | `off`), or `yazses features disable target-guard`.

### Tray icon doesn't appear in the top bar

**Symptom** — `yazses tray` runs (or the daemon started) but no microphone icon shows
in the top bar. The log says `No system tray is available on this desktop`.

**Cause** — The desktop has no StatusNotifier/AppIndicator host. GNOME does not show
tray icons out of the box; it needs the AppIndicator extension. (Ubuntu ships and enables
it by default, which is why it works there.)

**Fix** — Install/enable an AppIndicator extension:

```sh
# GNOME (non-Ubuntu): install the extension, then enable it
sudo apt install gnome-shell-extension-appindicator    # Debian/Ubuntu package name
gnome-extensions enable ubuntu-appindicators@ubuntu.com   # or appindicatorsupport@rgcjonas.gmail.com
# log out/in (or restart GNOME Shell) so the extension loads, then:
yazses tray
```

Everything the tray does is also available from the terminal (`yazses audio use <name>`,
`yazses mic-level --set`, `yazses restart`), so the tray is a convenience, not a
requirement. Turn off auto-launch with `yazses features disable tray`.

### STT model not downloaded

**Symptom** — The first dictation stalls or a model download runs unexpectedly.
`yazses doctor` shows `STT model … not downloaded`.

**Cause** — The configured faster-whisper model isn't in the local cache yet. It
is fetched automatically on first dictation, which needs a network connection
once.

**Fix** — Trigger it once with a network connection (dictate once, or start the
daemon and hold the hotkey briefly). After that it runs fully offline. Re-run
`yazses doctor` — the model should show `(cached)`.

### Double typing (everything appears twice)

**Symptom** — Each dictation is typed twice.

**Cause** — Two daemons are running and both react to the hotkey — typically a
detached `yazses start` surviving alongside a systemd-managed instance.

**Fix** — Stop every daemon (including detached ones) and start exactly one:

```sh
yazses restart      # kills all strays, starts a single daemon
```

If you manage the daemon with systemd, use `systemctl --user restart yazses`
instead of mixing it with a detached `yazses start` — mixing the two can leave
two daemons fighting over the hotkey (or none running at all).

---

## Snap-specific limits

### Hold-to-talk never fires on the snap

**Symptom** — Installed via `sudo snap install yazses`, but the hotkey never
triggers dictation, no matter what `yazses doctor` says about the `input` group.

**Cause** — The snap runs under **strict confinement**, which blocks reading the
raw kernel input devices (`/dev/input`). Hold-to-talk cannot work from the
confined snap — only the offline `yazses transcribe <file>` path does.

**Fix** — Install unconfined instead (APT script or `pipx`/`uv tool`), which
capture the hotkey:

```sh
# APT (Debian/Ubuntu) — pulls in all runtime deps:
bash <(curl -fsSL https://raw.githubusercontent.com/MSKazemi/yazses/main/install-apt.sh)

# or pipx (any distro, Python ≥ 3.11):
pipx install yazses

# or from a source checkout with uv:
uv tool install --force /path/to/yazses
```

### Snap microphone not granted

**Symptom** — On the snap, `yazses doctor` reports the microphone as not granted,
or nothing records.

**Cause** — Strictly-confined snaps can't self-connect interfaces, and the
`audio-record` interface is not auto-connected. It stays disconnected until you
connect it once.

**Fix** — Connect it once (a one-time step):

```sh
sudo snap connect yazses:audio-record
```

---

## macOS and Windows

### macOS — nothing types / mic denied

**Symptom** — On macOS, dictation is transcribed but nothing is typed, or the mic
never records.

**Cause** — macOS gates keystroke injection behind **Accessibility** and
recording behind **Microphone** permission. Both must be granted to YazSes.

**Fix** — Grant them in System Settings, then restart the app:

- **Accessibility** — System Settings → Privacy & Security → Accessibility →
  enable YazSes. Shortcut:
  ```sh
  open 'x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility'
  ```
- **Microphone** — approve the prompt on first record, or enable YazSes under
  Privacy & Security → Microphone.

On unsigned developer-preview builds, Gatekeeper blocks the first launch:
right-click the app → **Open**, then grant the permissions above.

### Windows — SmartScreen blocks the app

**Symptom** — On Windows, launching the app shows a SmartScreen warning and it
won't start.

**Cause** — v0 builds are unsigned, so SmartScreen flags them.

**Fix** — Click **More info → Run anyway**. If antivirus quarantines the
executable, add an exception for it. See
[Install on Windows](../docs/windows-install.md).

## Gaze / Glance-Type (look-to-pane)

Full setup is in [Aim dictation with your gaze](../docs/how-to/gaze-look-to-pane.md);
these are the common snags. Run `yazses gaze status` first — every line should be
a `✓`.

### `can't open camera by index` / `0 point(s) captured a face` when calibrating

**Cause** — Something else is holding the single webcam, almost always the running
YazSes **daemon** (it uses the camera at hold-time when gaze is on), or a video
call / browser tab.

**Fix** — Stop the daemon, then calibrate, then start it again:

```bash
yazses stop
yazses gaze calibrate
yazses start
```

If your webcam is not index 0, set `[gaze] camera_index` in `config.toml`.

### Dictation ignores my gaze — always types into the same window

**Cause** — Usually calibration that does not discriminate between screen regions.
Confirm what the router is choosing:

```bash
tail -f ~/.local/state/yazses/log/daemon.log | grep "Gaze routed"
```

If the **window id changes** as you look left vs right, gaze is working — line up
your windows in clearly different halves of the screen. If it is the **same id
every time**, re-calibrate carefully (deliberate eye movement to each point, head
still, good lighting):

```bash
yazses stop && yazses gaze calibrate && yazses start
```

### Nothing routes at all

**Cause** — Glance-Type is **X11-only** (Wayland forbids focusing other apps'
windows), or the webcam deps / calibration are missing.

**Fix** — Check `echo $XDG_SESSION_TYPE`; if it says `wayland`, log in with an
**Xorg / X11** session. Otherwise run `yazses gaze status` and fix any `✗` line
(`yazses features enable gaze --force` installs the deps; `yazses gaze calibrate`
creates the calibration).

---

## Still stuck?

Re-run `yazses doctor` and read the bottom-line verdict — it points at the exact
next command. If a problem persists, the doctor output prints the author's
contact and the issue tracker; include the full `yazses doctor` output and the
tail of `yazses logs` when reporting.
