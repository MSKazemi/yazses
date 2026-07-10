---
layout: default
title: YazSes — offline voice dictation for Linux, macOS & Windows
description: Hold a key, speak, release — your words are transcribed on-device with faster-whisper and typed into any focused app. No cloud, no API key, no subscription.
---

# YazSes

**Hold a key → speak → release.** YazSes is an open-source, **offline** voice‑dictation daemon for **Linux, macOS, and Windows**. It transcribes your speech locally with [faster-whisper](https://github.com/SYSTRAN/faster-whisper) and types the result into whatever window has focus — plus voice commands and macros. **No cloud. No API key. No subscription. Nothing leaves your machine.**

[Get it on PyPI](https://pypi.org/project/yazses/){: .btn }
[Source on GitHub](https://github.com/MSKazemi/yazses){: .btn }

![yazses doctor — all green, fully offline](screenshots/yazses-doctor.png)

## Install

```sh
# Any OS with Python ≥ 3.11
pipx install yazses

# Linux (Debian/Ubuntu)
bash <(curl -fsSL https://raw.githubusercontent.com/MSKazemi/yazses/main/install-apt.sh)
```

> **Not the snap.** The strict-confinement snap can't read the keyboard, so
> hold-to-talk never fires — use the APT script or `pipx` above.

**Linux only — provision the system in one command** (the `install-apt.sh` / APT path does it automatically):

```sh
yazses setup        # installs audio + injection deps, joins the input group, sets up ydotoold
# then log out and back in (the input-group change needs a fresh login)
```

This installs `libportaudio2` (audio), the X11/Wayland injection tools, adds you to the `input` group, and — on **GNOME/KDE Wayland**, where `wtype` is blocked — sets up `ydotoold` (the only way to inject keystrokes there). Re-run it anytime; it only fixes what's missing.

Then:

```sh
yazses doctor     # check mic, injection backend, permissions (want [OK] Keyboard capture)
yazses enroll     # calibrate your microphone (~30 s)
yazses start      # start the dictation daemon
```

Hold the hotkey (Space on Linux, Right Option on macOS, Right Ctrl on Windows), speak, release — the text appears in the focused app within about a second.

## What it does

- **Offline dictation** — type into any focused app with on-device faster-whisper (CPU, int8). No GPU needed.
- **Transcribe recordings** — `yazses transcribe meeting.m4a` turns any audio/video file into text, fully offline. Add `--diarize` to tag who said what and `--format srt` for subtitles. See the [transcription guide](https://github.com/MSKazemi/yazses/blob/main/docs/tutorials/transcribe-recordings.md).
- **Voice commands** — a regex grammar (plus an optional ~0.5B SLM router) maps phrases to editor/terminal key sequences: *"undo that"*, *"save file"*, *"go to line 42"*, *"run the tests"*, *"rename this to user_id"*.
- **Macros & personal vocabulary** — define multi-step commands and teach YazSes your mis-heard words.
- **Dysfluency-Friendly Mode** — opt-in collapse of stutters/repeats for stuttered or dysarthric speech.
- **Self-improving** — opt-in, encrypted on-device learning corpus; `yazses tune` proposes accuracy fixes from your own corrections.
- **Accessibility** — VAD calibration, mic-level tuning, and EMG (muscle-sensor) trigger support.

## When *not* to use it

YazSes is **not an LLM agent** — it dictates text and runs editor/terminal commands; it does not browse, reason over your files, or hold a conversation. It uses CPU faster-whisper (a cloud service may still win on raw accuracy for a noisy mic), ships English-tuned `*.en` models by default, and is desktop-only.

## How it works

```
Hold hotkey → record audio → VAD gate → faster-whisper (CPU)
            → clean + disfluency filter → command grammar (Tier 1 regex,
              optional Tier 2 SLM router) → dictate? type it · command? send keys
```

## Documentation

- [Install on Linux](https://github.com/MSKazemi/yazses/blob/main/docs/install-linux.md)
- [Install on macOS](https://github.com/MSKazemi/yazses/blob/main/docs/macos-install.md)
- [Install on Windows](https://github.com/MSKazemi/yazses/blob/main/docs/windows-install.md)
- [CLI reference](https://github.com/MSKazemi/yazses/blob/main/docs/cli-reference.md)
- [Transcribe recordings (tutorial)](https://github.com/MSKazemi/yazses/blob/main/docs/tutorials/transcribe-recordings.md)
- [v2 features (preview)](https://github.com/MSKazemi/yazses/blob/main/docs/v2-features.md)
- [Privacy statement](https://github.com/MSKazemi/yazses/blob/main/docs/privacy-statement.md)

## FAQ

**Does it work without internet?** Yes — transcription runs locally; nothing is sent anywhere by default.

**What GPU do I need?** None. It runs on CPU; 4 GB RAM minimum, 8 GB comfortable.

**Does it work on Wayland?** Yes via the APT or pipx install (uses wtype/ydotool). Use one of those, not the snap — strict confinement stops the snap from reading the keyboard, so the hold-to-talk hotkey never fires.

**Is it a replacement for Talon?** YazSes focuses on offline dictation plus a practical command grammar. Talon has far more advanced scripting. They can coexist.

---

Apache-2.0 licensed. If YazSes is useful to you, a ⭐ on [GitHub](https://github.com/MSKazemi/yazses) helps others find it.
