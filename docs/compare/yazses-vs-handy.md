---
title: Handy alternative — YazSes vs Handy for offline speech to text
description: An honest comparison of YazSes and Handy, two free offline open-source dictation tools for Linux, macOS and Windows — Wayland support, voice commands, file transcription and meeting capture, and where Handy is the better pick.
---

# YazSes vs Handy

**Short answer:** [Handy](https://github.com/cjpais/Handy) is the better choice if
you want dictation and nothing else, with the smoothest install and a large,
active community behind it. YazSes is the better choice if you want **voice
commands**, **offline transcription of existing recordings**, **meeting capture
with speaker labels**, or **full Wayland support** — or if accessibility features
are the reason you are looking.

Both are free, open source, and run entirely offline on Linux, macOS and Windows.
Handy is by far the more popular project. This page is about which fits your job,
not which has more stars.

## At a glance

| | Handy | YazSes |
|---|---|---|
| Licence | MIT | Apache-2.0 |
| Built with | Tauri (Rust) + React | Python |
| Models | Whisper (GPU when available), Parakeet V3 | faster-whisper (CPU int8); Parakeet optional |
| Activation | Hotkey, or push-to-talk | Hold-to-talk |
| Linux Wayland | Limited — needs `wtype` or `dotool` | **Full** — runtime backend probe |
| Voice commands | No | **Yes** (regex grammar → key sequences) |
| Transcribe existing files | No | **Yes** (`yazses transcribe`) |
| Meeting capture + speaker labels | No | **Yes** (`yazses meeting`) |
| macOS / Windows | Yes | Yes |

## Where Handy is the better tool

Being straight about this matters, because for a lot of people Handy is the right
answer.

- **It is more polished to install.** A Tauri desktop app with a real installer is
  a friendlier front door than a Python daemon plus a permissions checklist. YazSes
  ships `yazses doctor` and `yazses verify` precisely because its install has more
  ways to go wrong.
- **It uses your GPU.** Handy runs Whisper with GPU acceleration where available.
  YazSes deliberately targets CPU int8, so a strong GPU sits idle.
- **The community is much larger.** More users means more bug reports, faster
  fixes, and more chance your exact hardware has already been hit and solved.
- **It does one thing.** If you only want to dictate, everything below is weight
  you do not need.

## Where YazSes does something Handy does not

- **Voice commands.** Spoken phrases mapped by a fast regex grammar to real key
  sequences — *"undo that"*, *"save file"*, *"go to line 42"*. Handy is dictation
  only.
- **Wayland without caveats.** Handy documents *limited* Wayland support requiring
  external tools. YazSes probes the session at runtime and selects a working
  injection backend — `ydotool`, `wtype`, `xdotool`, or clipboard paste — and
  `yazses doctor` reports which one it picked.
- **Existing recordings.** `yazses transcribe <file>` turns any audio or video file
  into text, Markdown, SRT, WebVTT or JSON, optionally with speaker diarization.
- **Whole meetings.** `yazses meeting` captures hands-free and produces a
  speaker-labelled transcript, optionally with minutes written by a local LLM.
- **Accessibility.** VAD calibration, a dysfluency-friendly mode for stuttered or
  dysarthric speech, and an activation layer where the hotkey is a replaceable part
  — an EMG muscle sensor is an existing alternative for people who cannot hold a key.
- **An opt-in on-device learning loop.** `yazses tune` proposes accuracy fixes from
  your own corrections, all encrypted and local.

## The honest summary

If your answer to *"what do you want it to do?"* is **"type what I say"**, Handy is
an excellent choice and probably the easier one to live with.

If your answer includes *"…and run commands"*, *"…and handle my recordings"*,
*"…and take my meeting notes"*, or *"…and work for someone who cannot hold a key"*,
those are the jobs YazSes was built for, and they are not on Handy's roadmap as far
as its documentation describes.

## Trying both

They can coexist — just do not bind them to the same key.

```sh
sudo snap install yazses      # or: pipx install yazses
yazses doctor
yazses enroll
yazses start
```

## Related

- [Full comparison with Dragon, Talon, Wispr Flow and others](../comparison.md)
- [YazSes vs Vocalinux](yazses-vs-vocalinux.md)
- [Voice dictation on Wayland](../use-cases/voice-dictation-wayland.md)
- [Control your computer by voice](../use-cases/voice-commands.md)
