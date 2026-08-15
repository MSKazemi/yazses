---
title: What installing YazSes actually costs — disk, downloads and time
description: Honest, measured numbers for a YazSes install — how much disk it uses, what gets downloaded, how long it takes, and what it does to your system. Published before you install, not after.
---

# What installing it actually costs

Most projects tell you how to install and never what it costs. These are measured
numbers, not estimates, so you can decide before you start.

## Disk

| What | Size | Notes |
|---|---|---|
| YazSes, headless (no desktop extra) | **414 MB** | `pip install yazses` — enough for `transcribe`. 42 distributions; 84% of it is four binary wheels that arrive with faster-whisper |

*The 414 MB is measured on **Linux x86_64, CPython 3.12**. Expect it to differ by a few
tens of MB elsewhere: the platform-conditional dependencies are not the same set —
Linux compiles `evdev`, macOS pulls four `pyobjc` frameworks plus `rumps`, Windows pulls
`pywin32`, `pystray` and Pillow. The four wheels that dominate the total are the same
everywhere.*
| YazSes + the `desktop` extra | **1.1 GB** | what `install.sh`, the `.deb` and the Snap install |
| ↳ of which **PySide6 (Qt)** | **648 MB** | the overlay and the tray — now optional, see below |
| Speech model — `tiny.en` | 75 MB | fastest, least accurate |
| Speech model — `base.en` | **141 MB** | **the default** |
| Speech model — `small.en` | 464 MB | most accurate of the three |
| Speaker diarization models | ~45 MB | only if you use `--diarize` |
| Docker image (transcription only) | 833 MB | no Qt |

**A normal desktop install is therefore about 1.25 GB**: 1.1 GB of program plus the
141 MB default model. A **headless** install is roughly **555 MB** all-in. Only one
model is downloaded — the one you configure.

!!! question "Can the headless 414 MB be made smaller?"

    Not meaningfully, and it is worth being straight about why. **84% of it is four
    binary wheels that arrive with the speech engine**: `ctranslate2` (135 MB), PyAV
    (103 MB), `numpy` (58 MB) and `onnxruntime` (53 MB) — the last of which is
    `faster-whisper`'s own dependency, for its bundled voice-activity detector.
    YazSes' own code is **4 MB**, under 1% of the install.

    So the floor is set by the speech engine's dependency tree, not by how YazSes is
    packaged. Every lever packaging *does* control has already been pulled: Qt is an
    extra, the 21 optional features install on demand, and no speech model ships with
    the program — it is fetched on first use, and only the one you configure.
    Measurements and the full breakdown:
    [modular distribution survey](https://github.com/MSKazemi/yazses/blob/main/design/research/2026-08-15-modular-distribution-survey.md).

!!! success "Qt is now optional — headless installs are ~650 MB lighter"
    `PySide6` is **no longer a base dependency**. It is 648 MB of Qt and it exists for
    exactly two desktop features: the voice-activity overlay and the system-tray icon.
    Installs that can never show either — servers, containers, CI, anything headless,
    and anyone who only runs `yazses transcribe` — were paying for all of it.

    It now lives in the **`desktop` extra**:

    ```sh
    pip install yazses              # headless: transcribe, meetings, the CLI
    pip install 'yazses[desktop]'   # adds the overlay and the tray
    ```

    **Nothing changes for a normal desktop install.** `install.sh`, the `.deb` and the
    Snap all pull the desktop extra, so the tray and overlay work out of the box exactly
    as before. If you installed headless and later want them,
    `yazses features enable tray` (or `overlay`) fetches Qt on demand.

    Every import of it is lazy, so a headless copy simply reports the feature as
    unavailable rather than failing. Tracked as
    [#259](https://github.com/MSKazemi/yazses/issues/259).

## What a feature costs to turn on

Nothing below is installed unless you ask for it. `yazses features info <name>` shows
the figure before you commit, and `yazses features enable` prints it again — loudly —
before it fetches anything.

| Feature | Download | Packages |
|---|---:|---:|
| `cocktail`, `multiprofile`, `voiceguard` (speaker voiceprint) | **~3.1 GB** | 37 |
| `overlay`, `tray` (Qt) | ~256 MB | 4 |
| `gaze` (mediapipe + OpenCV) | ~219 MB | 12 |
| `stt-moonshine` | ~113 MB | 18 |
| `llm-cleanup` (llama.cpp) | ~72 MB | 4 |
| `read-back`, `readback_clone` (Kokoro TTS) | ~25 MB | 23 |
| `diarize`, `meeting`, `recimport` (sherpa-onnx) | ~18 MB | 2 |
| `prosody`, `voicehealth` | ~11 MB | 1 |
| `agent` (MCP) | ~4 MB | 20 |
| `stt-parakeet` | ~4 MB | 1 |
| `chinese-script` | ~0.5 MB | 1 |

!!! warning "The voiceprint features cost 3.1 GB, and it is worth knowing why"

    `cocktail`, `multiprofile` and `voiceguard` all need a speaker-embedding model, and
    the default backend (`speechbrain`) resolves to **PyTorch and the full NVIDIA CUDA
    stack** — cuDNN, NCCL, cuSPARSE, cuSOLVER — none of which YazSes uses, because
    everything here runs on the CPU. That is a dependency of a dependency, not a choice
    this project makes, and it is **7× the size of YazSes itself**.

    If you want speaker features without it, `[voiceprint] backend = "resemblyzer"` is
    the lighter alternative. Otherwise, leave them off — all three are off by default
    and `cocktail` is experimental besides.

These are **download** sizes for the fully resolved dependency set, measured on Linux
x86_64 against a clean base install, so they will not match a `du` afterwards. A feature
whose packages you already have costs nothing, and says so.

## What each install path actually pulls

There is no single installer, and they do not all install the same thing — correctly,
because a container and a laptop need different software. This is what each one
decides for you:

| How you installed | Pulls the `desktop` extra (Qt, 648 MB)? | You get | Roughly |
|---|---|---|---|
| `pip install yazses` / `pipx install yazses` | **No** | The CLI, dictation, `transcribe`, meetings | **414 MB** |
| `install.sh` (the Linux one-liner) | **Yes** | …plus the tray and the voice-activity overlay | ~1.1 GB |
| The `.deb` | **Yes** (`yazses[desktop]`) | Same as above | ~1.1 GB |
| The Snap | **Yes** (bundled) | Same, in a confined package | ~1.1 GB |
| The Docker image | **No** — it has no display | `transcribe` + diarization only | 833 MB |

**If you want the smallest install, `pip install yazses` already is it.** There is no
`minimal` extra to ask for, because the base install *is* the minimum — see the box
above for why 414 MB is a floor rather than a choice. Everything beyond it is opt-in
through `yazses features enable <name>`, which now tells you the download size before
it fetches anything.

`install.sh` names Qt directly rather than asking for the `desktop` extra — `uv`
resolves extras awkwardly from a `git+` source — so the two are kept in step by
[`tests/test_install_paths_agree.py`](https://github.com/MSKazemi/yazses/blob/main/tests/test_install_paths_agree.py)
rather than by anyone remembering.

## Downloads

Nothing is downloaded that you did not ask for, and **the speech model is the only large
download**. It happens once, on first use, from Hugging Face — after that YazSes never
needs the network again.

You can prove that rather than trust it:

```sh
docker run --rm --network none -v yazses-models:/models -v "$PWD:/data" yazses jfk.wav
```

That transcribes with networking switched off entirely. It works.

## Time

| Step | Time | Measured how |
|---|---|---|
| First transcription (incl. 141 MB model download) | **43 s** | 4-core CPU, `base.en` |
| Every transcription after | **2.3 s** for 11 s of audio | model cached |
| System provisioning (`yazses setup`) | under a minute | apt packages |
| The one-time log-out and back in | **you pick when** | required on Linux; see below |

Install time itself depends almost entirely on your network and on whether `evdev` has to
be compiled (it has no wheels, so it usually does — this needs a C compiler, which
`install.sh` installs for you if it is missing).

## What it changes on your system

On Linux, a full dictation install touches these and nothing else:

| Change | Why | Reversible |
|---|---|---|
| Installs `libportaudio2`, `xdotool`/`ydotool`/`wtype`, clipboard tools | capture audio, type text | yes — normal apt packages |
| Adds you to the **`input` group** | read the hold-to-talk key from the kernel | yes — `sudo gpasswd -d $USER input` |
| Enables **`ydotoold`** (Wayland only) | the only way to inject keystrokes on GNOME/KDE Wayland | yes — `systemctl --user disable --now ydotoold` |
| Writes config to `~/.config/yazses/` | your settings | yes — delete it |
| Writes data to `~/.local/share/yazses/` | logs, PID, learning corpus if enabled | yes — delete it |
| Optional systemd **user** unit | start at login, if you ask for it | yes — `yazses autostart disable` |

!!! note "The `input` group is the one real security consideration, and it is worth understanding"
    Membership lets any program you run read raw input events — which is how the
    hold-to-talk hotkey works at all, and it is the same mechanism every Linux hotkey
    daemon uses. It is a genuine privilege grant, so it is stated plainly here rather
    than buried. If you are not comfortable with it, `yazses transcribe` needs none of
    it, and neither does Docker.

## What it does *not* do

- **No account, no API key, no licence server, no sign-up.**
- **No telemetry.** Nothing is counted, phoned home, or reported — there is no analytics
  code in the project at all. Downloads on PyPI are the only number the project can see,
  and that is PyPI's counter, not ours.
- **No background network access** after the model is downloaded.
- **No autostart unless you run `yazses autostart enable`.**

## Getting it back off

[Uninstalling is one page](uninstall.md), and it removes everything listed above.

---

**Ready?** [Install on Linux](install-linux.md) · [macOS](macos-install.md) ·
[Windows](windows-install.md) — or
[try it without installing anything](try-without-installing.md) first.
