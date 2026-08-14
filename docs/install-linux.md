---
title: Install offline voice dictation on Linux (Ubuntu, Debian, Fedora, Arch)
description: Step-by-step install of YazSes offline voice dictation on Linux — apt, snap or pipx, microphone calibration, hotkey setup, and text injection on both X11 and Wayland.
---

# Installing YazSes on Linux

This guide installs the Python daemon as a global command and starts it
automatically at login. It targets the reliable batch (transcribe-on-release)
configuration. Tested on X11 + PipeWire.

## 1. Install — one command

**You do not need to clone the repository** — the script fetches everything
itself. Paste this. It installs YazSes and **every** system prerequisite (audio,
keystroke injection, clipboard, the `input` group, and `ydotoold` on Wayland),
then runs `yazses doctor` so anything missing surfaces during install rather than
as silent failure later:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/MSKazemi/yazses/main/install.sh)
```

That is the whole install. Skip to [§2](#2-finish-setup).

> **Build prerequisites are handled for you.** The script needs `git` (it installs
> the latest code straight from the repo) and a C compiler with the Python headers
> (`evdev`, which reads the hotkey, publishes no wheels and is always compiled from
> source). It checks for all three up front and installs them via `apt` if they are
> missing, instead of failing later inside the build. On a distro without `apt` it
> stops and names the packages — Fedora `git gcc python3-devel`, Arch
> `git base-devel`. The **Snap** is the one channel that needs none of this: it
> bundles a prebuilt `evdev`. The APT package does *not* — it `pipx`-installs the
> Python package in its post-install step, so it compiles `evdev` too.

<details>
<summary>Other install channels (APT, Snap, pipx)</summary>

| Channel | Command | Notes |
|---|---|---|
| **Universal script** (recommended) | `bash <(curl -fsSL https://raw.githubusercontent.com/MSKazemi/yazses/main/install.sh)` | Latest code from git. Installs `uv` if absent. Provisions everything. |
| **APT** (Debian/Ubuntu) | `bash <(curl -fsSL https://raw.githubusercontent.com/MSKazemi/yazses/main/install-apt.sh)` | Last tagged release. The script adds the YazSes apt repo, installs the runtime deps, joins you to the `input` group and sets up `ydotoold`; the `.deb`'s post-install step then `pipx`-installs the Python package and enables the user service. |
| **Snap** | `sudo snap install yazses`<br>`sudo snap connect yazses:audio-record`<br>`sudo snap connect yazses:raw-input`<br>`yazses setup` | **All four lines are required.** A snap cannot connect its own interfaces, so without `audio-record` it has no microphone and without `raw-input` the hold-to-talk key does nothing at all ([#44](https://github.com/MSKazemi/yazses/issues/44)) — the daemon still starts and looks healthy either way. `yazses setup` then provisions the rest; `yazses doctor` tells you if anything is still missing. A snap also ships a **fixed** set of libraries — see [what the snap can and cannot do](#3e-what-the-snap-can-and-cannot-do). |
| **pipx** (any distro, Python ≥ 3.11) | `pipx install yazses` | Installs **only** the Python package — needs `build-essential python3-dev` to compile `evdev`, and you must then run `yazses setup` yourself ([§3](#3-installing-by-hand-what-the-installer-did-for-you)). |

Already installed and want the newest release?

```bash
pipx upgrade yazses          # or: yazses update
```

</details>

!!! warning "On arm64 (Raspberry Pi, Ampere, arm64 VMs), don't use the snap yet"

    `snap install yazses` resolves the **stable** channel, and stable currently has an
    **amd64 revision only** — on arm64 it fails to find a revision at all. An arm64 build
    exists on `edge`, but it is a release behind:

    ```bash
    sudo snap install yazses --edge   # arm64: the only channel with a build today
    ```

    The publishing workflow now builds and releases arm64 to `stable` alongside amd64, so
    this clears at the next tagged release ([#267](https://github.com/MSKazemi/yazses/issues/267)).
    Until then the **universal script** (`install.sh`) and **pipx** are the recommended
    arm64 paths — PyPI ships `aarch64` wheels for the whole runtime stack, so both work
    today.

## 2. Finish setup

Three steps only you can do — the installer prints this same list when it
finishes:

```bash
# 1. Log out and back in  (once — so the `input` group takes effect)
yazses mic-level --set   # 2. tune the silence gate to your voice (~4 s)
yazses start             # 3. start dictating
```

The **log-out/in is mandatory and one-time.** Group membership only refreshes in
a *new login session* — opening another terminal tab is **not** enough, because
it inherits the old session's groups and the hotkey stays dead. To dictate
immediately without logging out, bridge the group for one session:

```bash
sg input -c "yazses restart"    # runs the daemon with input-group access now
```

Verify anytime — you want `[OK] Keyboard capture`, `[OK] Microphone`,
`[OK] Injection`:

```bash
yazses doctor
```

Then hold the hotkey (default `right_alt`), speak, release — the text types into
whatever field has focus. That's it; the rest of this page is reference.

## 3. Installing by hand (what the installer did for you)

Skip this if [§1](#1-install--one-command) worked — it is for people installing
with `pipx`, or who want to understand the pieces.

**Order matters: the package first, provisioning second.** `yazses setup` is a
subcommand *of YazSes*, so it cannot run until YazSes is installed:

```bash
sudo apt install -y pipx build-essential python3-dev   # pipx + the evdev build toolchain
pipx install yazses                                    # 1. install the CLI
yazses setup                                           # 2. now provision the system
# then log out and back in (the input-group change needs a fresh login)
```

`yazses setup` installs the audio + injection packages, joins you to the `input`
group and sets up `ydotoold` on Wayland. It is idempotent (safe to re-run — it
only fixes what's missing) and finishes by printing the [§2](#2-finish-setup)
checklist, offering to run the mic calibration for you there and then.

The remaining sub-sections spell out what `yazses setup` does, for when you want
to do each piece yourself.

### 3a. Runtime dependencies

**Install every runtime dependency in one command** (the APT `.deb` pulls these
in automatically, so skip this if you used `install-apt.sh`):

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
need membership in the **`input`** group (§3b) and a working microphone
(PipeWire/PulseAudio/ALSA).

### 3b. Add yourself to the `input` group (required)

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

Do this **before** starting the daemon (§2). `yazses start`/`restart` will
warn you if this re-login is still pending. To dictate **immediately** without
logging out, bridge the group for one session:

```bash
sg input -c "yazses restart"           # runs the daemon with input-group access now
```

After a real re-login, a plain `yazses start` just works — no bridge needed.

### 3c. Wayland keystroke injection — `ydotoold` (GNOME/KDE Wayland)

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
`input` group (§3b). After this, `yazses doctor` shows `[OK] Injection` and
`[OK] ydotoold`.

### 3d. What gets installed

The script, APT and `pipx` all install five commands into `~/.local/bin` (make
sure that's on your `PATH`): `yazses`, `yazses-daemon`, `yazses-tray`,
`yazses-agent`, `yazses-overlay`. The Snap instead exposes `yazses`,
`yazses-daemon`, `yazses-tray` and `yazses-overlay` on `/snap/bin`, which is
already on your `PATH`.

> If an old `alias yazses=...` exists in your shell rc pointing at a previous
> build, remove it so the installed binary is used.

Working on YazSes itself? Clone the repo and run `bash scripts/dev-install.sh` —
an editable install plus provisioning plus start, in one command.

### 3e. What the snap can and cannot do

A snap ships a **fixed** set of Python libraries. Its files are read-only, so
`yazses features enable <name>` cannot download anything into it the way the
other channels can — whatever is bundled in a revision is all that revision will
ever have.

Everything needed for dictation is bundled, plus the capabilities whose libraries
fit inside a snap:

| Capability | In the snap? | Why |
|---|---|---|
| Dictation, commands, tray, overlay, mic guard, target guard | ✅ | Part of the base install |
| `stt-parakeet` — higher-accuracy English engine | ✅ | `onnx-asr` is a base dependency |
| `meeting`, `recimport`, `diarize` — Meeting Mode and diarized import | ✅ | `sherpa-onnx` is bundled |
| `read-back` — spoken read-back of what you dictated | ✅ | `kokoro-onnx` + `soundfile` are bundled |
| `cocktail` — Cocktail Filter | ❌ | `speechbrain` pulls PyTorch (~1 GB) |
| `llm-cleanup` — offline LLM reformatting | ❌ | `llama-cpp-python` has no PyPI wheels; needs a compiler |
| `gaze` — Glance-Type | ❌ | `mediapipe` + `opencv` cost ~110 MB, and it needs a webcam and X11 |
| `prosody` — prosody-aware punctuation | ❌ | `praat-parselmouth` publishes no `aarch64` wheel |

Enabling one of the ❌ rows inside the snap refuses with an explanation rather
than failing halfway through — the config is left untouched, so nothing reads as
"on" while being unable to work.

To use those four, install through any other channel:

```bash
sudo snap remove yazses
pipx install yazses
```

Note that settings do not carry over: the snap keeps config and models under
`~/snap/yazses/`, an unconfined install under `~/.config/yazses`.

### 3f. Fedora and the RHEL family (COPR)

```bash
sudo dnf copr enable mskazemi/yazses
sudo dnf install yazses
yazses doctor
```

The spec lives at
[`packaging/fedora/yazses.spec`](https://github.com/MSKazemi/yazses/blob/main/packaging/fedora/yazses.spec)
and builds a package that has been installed and run on a clean Fedora 41
container — `packaging/fedora/build-and-test.sh` is that test, and it is meant to
be run in a container rather than on your machine:

```bash
podman run --rm -v "$PWD:/src:z" fedora:41 /src/packaging/fedora/build-and-test.sh
```

Two honest notes about this package:

- **It bundles its Python dependencies** into a private virtualenv under
  `/usr/lib64/yazses`, which makes the installed size about **380 MB**. The
  idiomatic Fedora approach would declare each dependency as a
  `python3dist(...)` require, and that is not possible today: faster-whisper,
  ctranslate2 and onnx-asr are not in the Fedora repositories, and a spec that
  declared them would fail dependency generation on a clean build. Bundling is
  acceptable for a COPR and is **not** acceptable for the official Fedora
  repositories — getting there means packaging that dependency tree first.
- **`portaudio` is a hard requirement; the injection tools are not.** `xdotool`
  and `xclip` are *Recommends*, `ydotool` and `wl-clipboard` are *Suggests*,
  because transcribing files with `yazses transcribe` needs none of them and a
  hard dependency would drag an X11 stack onto a headless machine.

After installing, `yazses doctor` will still ask you to join the `input` group
(§3b) — that is a system-level change no package can make on your behalf, and it
needs a full logout.

> **Status:** the spec and its container test are in the repository and verified.
> The COPR itself lives under the maintainer's Fedora account; until it is
> published, build the RPM locally with the command above.

## 4. Start at login

**Usually already done.** `yazses start` sets this up once the daemon is up, whichever way
you installed — so if you have started YazSes at least once, it will be running again after
the next reboot. It says so the one time it does it, and does nothing on later starts.

To skip it, `yazses start --no-autostart`. To do it explicitly — or to redo it after
disabling — it is one command:

```bash
yazses autostart enable
```

That writes a systemd user service pointing at *this* install, enables it, and starts it.
Check it any time:

```bash
yazses autostart status    # will YazSes be running after the next reboot?
yazses doctor              # includes a "Starts at login" check
```

`yazses autostart disable` turns it off again.

The service restarts YazSes automatically if it ever crashes — verified by killing it
outright, it is back within about five seconds — and gives up after five failures in a
minute so a genuinely broken machine leaves a diagnosable state instead of a spin loop.

> **Display access.** X11 injection needs `DISPLAY` and `XAUTHORITY`, which the unit takes
> from the systemd user manager via `PassEnvironment`. GNOME/GDM export them there
> automatically; confirm with `systemctl --user show-environment | grep DISPLAY`. If they
> are missing, add them to the unit explicitly with
> `systemctl --user edit yazses.service`, or run `systemctl --user import-environment
> DISPLAY XAUTHORITY` from inside your session. Without them, dictation runs and the text
> goes nowhere.

<details>
<summary>Writing the unit by hand instead</summary>

`yazses autostart enable` is the supported path, and it keeps the unit correct across
upgrades that move the binary. If you would rather manage it yourself, the unit it
installs lives at `~/.config/systemd/user/yazses.service`; `contrib/yazses.service` in the
repo is the same file.

</details>

## 5. Use it

1. Focus any text field.
2. Hold the hotkey (default `right_alt`), speak, release.
3. The transcript types in once.

```bash
yazses status      # state, hotkey, model, backend
yazses logs        # recent diagnostic log (metadata only)
```

## 6. Tune the silence threshold

If dictation does nothing and `yazses logs` shows `Silent audio -- discarding`,
your speech is below the VAD gate. Measure and set it:

```bash
yazses mic-level --set      # records ~4s; writes a fitting vad_threshold
systemctl --user restart yazses.service
```

Re-run whenever your speaking volume changes (e.g. quiet late-night dictation).

## 7. Manage the service

```bash
systemctl --user restart yazses.service    # after a config change
systemctl --user stop yazses.service       # stop
systemctl --user disable --now yazses.service   # stop + remove autostart
journalctl --user -u yazses.service -f     # live logs via journald
```

Config lives at `~/.config/yazses/config.toml`. See the
[CLI reference](cli-reference.md) for all commands.

## 8. Troubleshooting: the hotkey does nothing

If holding the key records nothing (no transcript, no overlay reaction), run the
health check first — it now pinpoints every common cause in one shot:

```bash
yazses doctor
```

Look for these lines and act on any that are not `[OK]`:

- **`Hotkey device: bound to virtual device …`** — the daemon is listening on an
  injector's virtual device (e.g. `ydotoold virtual device`) instead of your real
  keyboard, so your keypresses are never seen. Make sure you are in the `input`
  group (`groups | grep input`; if missing, [§3b](#3b-add-yourself-to-the-input-group-required),
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
  [§3b](#3b-add-yourself-to-the-input-group-required).

If `yazses logs` shows `Silent audio -- discarding`, the key *is* working but your
speech is below the VAD gate — see [§6](#6-tune-the-silence-threshold).

> **Tip:** manage the daemon with `systemctl --user restart yazses` when a systemd
> unit exists; mixing `yazses start` (detached) with a systemd unit can leave two
> daemons fighting over the hotkey, or none running at all.

## 9. Voice-activity overlay

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
