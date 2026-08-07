---
title: YazSes vs Dragon, Talon, Wispr Flow & nerd-dictation — offline dictation compared
description: "An honest comparison of offline voice dictation tools for Linux, macOS and Windows: YazSes vs Dragon NaturallySpeaking, Talon Voice, nerd-dictation, Vocalinux, TalkType, VOXD, Speech Note, Wispr Flow, Google and Apple dictation — which runs offline, which does voice commands, which supports Wayland, and which is free."
---

# YazSes vs. other dictation tools

**Short answer:** YazSes is the tool to pick when you want **hold-to-talk voice
dictation that runs fully offline on Linux (and macOS/Windows), is free and
open-source, and also does voice commands** — without sending your voice to any
cloud service. If you need cloud-grade AI reformatting, professional
medical/legal accuracy, or deep voice-coding scripting, one of the alternatives
below may fit you better. This page is deliberately honest about where each tool
wins.

## At a glance

| Tool | Runs offline | Voice commands | Linux | macOS / Windows | Cost | Open source |
|---|---|---|---|---|---|---|
| **YazSes** | **Yes** (on-device faster-whisper) | **Yes** (regex grammar + optional SLM router) | **Yes** (X11 & Wayland) | **Yes** | **Free** | **Yes (Apache-2.0)** |
| Dragon (Nuance) | Yes | Yes | No | Windows | Paid (commercial) | No |
| Talon Voice | Yes | Yes (advanced scripting) | Yes | Yes | Freemium | No (free tier + paid beta) |
| nerd-dictation | Yes (VOSK) | Via Python config | Yes | No | Free | Yes (GPLv3) |
| Vocalinux | Yes (whisper.cpp / Whisper / VOSK) | Yes (text manipulation) | Yes (X11 & Wayland) | No | Free | Yes (GPLv3) |
| Wispr Flow | No (cloud) | Limited | No | Yes | Subscription | No |
| Google Voice Typing | No (cloud) | No | Via browser | Yes | Free | No |
| Apple Dictation | Partial | Limited | No | macOS only | Free | No |
| Whisper + DIY scripts | Yes | No (you build it) | Yes | Yes | Free | Yes |

> **Looking for meeting notes rather than dictation?** YazSes also records whole
> meetings and transcribes existing recordings offline. That is a different
> competitor set (Otter.ai, Fireflies, Granola, Meetily) and has its own page:
> **[Offline meeting notes](meeting-notes-offline.md)**.

## What makes YazSes different

- **Fully offline & private by default.** Audio is transcribed on-device with CPU
  faster-whisper (int8). No GPU, no network, no account — nothing you say leaves
  the machine.
- **Dictation *and* voice commands.** Speak to type, or use a fast regex command
  grammar (with an optional ~0.5B SLM router for low-confidence phrases) that maps
  *"undo that"*, *"save file"*, *"go to line 42"* to real key sequences.
- **Hold-to-talk.** Natural push-to-talk that types into whatever app has focus —
  editor, browser, terminal, chat.
- **Linux-first, cross-platform.** Works on X11 and Wayland, plus macOS and Windows.
- **Built for accessibility.** VAD calibration, a dysfluency-friendly mode for
  stuttered/dysarthric speech, and an optional EMG muscle-sensor trigger for
  hands-free use.
- **Self-improving on your terms.** An opt-in, encrypted, on-device learning corpus
  lets `yazses tune` propose accuracy fixes from your own corrections.
- **One tool for three jobs.** The same install and the same downloaded model do
  live dictation, offline transcription of existing recordings
  (`yazses transcribe`), and whole-meeting capture with speaker labels
  (`yazses meeting`). Every other tool on this page does one of the three.

## When another tool is the better choice

### YazSes vs Dragon NaturallySpeaking

**Choose Dragon** if you need best-in-class accuracy for professional
medical/legal dictation on Windows and a commercial license is acceptable. Dragon
is a mature, paid, Windows-focused product with specialist vocabularies YazSes
does not ship.

**Choose YazSes** if you are on Linux or macOS (Dragon is Windows-only), if a
per-seat commercial licence is a blocker, or if you want the source to be
auditable. On accuracy for general prose the gap is much smaller than it used to
be; on specialist terminology it is not.

### YazSes vs Talon Voice

**Choose Talon** if your priority is deep, scriptable *voice coding*. Talon has a
powerful scripting ecosystem — Python configs, a large community grammar library,
eye tracking — and for people who drive their whole desktop by voice it remains
the most capable option.

**Choose YazSes** if you want dictation that works out of the box without
learning a scripting system, want it fully open-source (Apache-2.0), or want file
transcription and meeting capture from the same install. The two coexist happily;
they are aimed at different points on the effort/power curve.

### YazSes vs nerd-dictation

[nerd-dictation](https://github.com/ideasman42/nerd-dictation) is a single Python
file using the VOSK API, GPLv3, with famously small models and no background
process — dictation is started and stopped with explicit begin/end commands, and
you customise output by writing Python string operations.

**Choose nerd-dictation** if you want maximum minimalism and hackability, the
lowest possible resource footprint, or you like configuring behaviour in code.

**Choose YazSes** if you want a hold-to-talk key instead of begin/end commands,
Whisper-class accuracy rather than VOSK, macOS/Windows support (nerd-dictation is
Linux-only), or the packaged extras — voice commands, macros, personal
vocabulary, file transcription, meeting capture.

### YazSes vs Vocalinux

[Vocalinux](https://github.com/jatinkrmalik/vocalinux) is GPLv3, supports
whisper.cpp / Whisper / VOSK, runs on X11 and Wayland, has voice commands for
text manipulation, and — notably — offers **Vulkan GPU acceleration** across AMD,
Intel and NVIDIA.

**Choose Vocalinux** if you have a capable GPU and want to use it, or you want to
pick between three recognition engines.

**Choose YazSes** if you need macOS or Windows too (Vocalinux is Linux-only), if
you want the same install to also transcribe recordings and capture meetings with
speaker labels, or if you need the accessibility-oriented pieces —
dysfluency-friendly mode, EMG triggering, VAD calibration — and the opt-in
on-device learning loop.

YazSes deliberately targets **CPU int8** rather than GPU, so it runs on modest
hardware; if you have the GPU, a whisper.cpp-based tool will transcribe faster.

### YazSes vs TalkType

[TalkType](https://github.com/ronb1964/TalkType) is the closest thing to YazSes on
Linux: it is offline, Whisper-based, Wayland-first, and uses the **same
hold-to-talk gesture** — press a key to talk, release to type. It ships as a
zero-config AppImage with optional GPU acceleration.

**Choose TalkType** if you want a single-file AppImage with nothing to configure,
and Linux is the only machine you dictate on.

**Choose YazSes** if you also work on macOS or Windows, if you want the same
install to transcribe existing recordings and capture meetings with speaker
labels, or if you need the accessibility and voice-command layers.

### YazSes vs Wispr Flow

**Choose Wispr Flow** if you want polished, cloud-based AI formatting and
rewriting and do not need offline operation or Linux support.

**Choose YazSes** if the audio must not leave the machine, if you are on Linux,
or if you do not want a subscription. This is the clearest trade-off on the page:
cloud polish versus local privacy.

### YazSes vs Google / Apple / Windows built-in dictation

**Use the built-in** if it is already good enough and you are comfortable with
cloud processing (Google), a walled ecosystem (Apple), or Windows-only
(Windows Speech Recognition). They cost nothing and need no setup.

**Choose YazSes** if you want the same dictation behaviour across all three
operating systems, need it to work with no network, or want voice commands that
the built-ins largely do not offer. Note that Linux has no comparable built-in at
all — that gap is the reason this project exists.

### YazSes vs Whisper + your own scripts

**Roll your own** if you enjoy building and maintaining the glue.

**Choose YazSes** if you would rather not: it *is* that glue, productized and
tested — hotkey capture across multiple keyboards, VAD calibration, pre-speech
padding, command grammar, text injection that works on X11 *and* Wayland *and* in
terminals, a no-text-target guard, mic-change auto-healing, and packaging for
APT/Snap/PyPI.

### Others in this space

[Whispering](https://github.com/epicenter-so/epicenter), OpenWhispr, Handy and
[VOXD](https://github.com/jakovius/voxd) are also active open-source offline
dictation projects, mostly built on whisper.cpp.

[Speech Note](https://github.com/mkiol/dsnote) is worth calling out separately
because it is a **different shape of tool**: a notepad application you dictate
*into*, which also does text-to-speech and offline translation. If you want a
document to write in rather than dictation injected into whatever window has
focus, it is the better fit — and it does more than YazSes on translation.

These are worth a look if the tools above do not fit; this page is a comparison,
not a claim that YazSes wins every case.

## Common questions

**Is there a good open-source, offline alternative to Dragon or Wispr Flow on
Linux?** Yes — YazSes is an open-source (Apache-2.0), fully offline dictation tool
that runs on Linux, macOS, and Windows and needs no cloud account.

**What's the best free voice dictation for Linux that also does commands?** YazSes
combines on-device transcription with a voice-command grammar, so the same
hold-to-talk key both types text and triggers editor/terminal actions.

**Does YazSes send my audio anywhere?** No. Transcription runs locally with
faster-whisper; by default nothing leaves your machine.

**Is there an offline, open-source alternative to Otter.ai for meeting notes?**
Yes. `yazses meeting start` / `yazses meeting stop` records a meeting hands-free
and produces a speaker-labelled transcript on-device, with optional minutes from a
local LLM — no account, no per-seat fee, and no bot joining the call. It records
the room through your microphone rather than capturing a video call's system
audio; see [Offline meeting notes](meeting-notes-offline.md).

**Can I transcribe an existing recording offline?** Yes —
`yazses transcribe interview.m4a` converts any audio or video file to txt, md,
srt, vtt, or json, with `--diarize` for who-said-what speaker tags.

**What is the best open-source dictation tool for Linux?** It depends on what you
weight. nerd-dictation is the most minimal, Vocalinux has GPU acceleration, Talon
is the most powerful for voice *control*, and YazSes is the one that is
cross-platform and covers dictation, file transcription and meeting capture from a
single install. All four are free and run offline; the sections above lay out the
trade-offs honestly.

**Does YazSes work on Wayland?** Yes. It probes the session at runtime and injects
text through `ydotool` or `wtype` on Wayland and `xdotool` on X11. This is the
part that most Linux dictation tools struggle with — see
[voice dictation on Linux](use-cases/voice-dictation-linux.md).

**Is there an alternative to Dragon NaturallySpeaking for Linux?** Dragon does not
run on Linux at all. The closest open-source options are YazSes, Talon Voice,
Vocalinux and nerd-dictation. For general prose dictation the accuracy gap to
Dragon is modest; for specialist medical or legal vocabularies it is not.

## Honest limitations

- Accuracy is Whisper-class — **4.07 % WER** on LibriSpeech test-clean with the
  default model, [measured and reproducible](benchmarks.md). It is not tuned for
  specialized medical/legal vocabularies the way Dragon is, and real dictation in
  a room will be worse than a clean read-speech benchmark.
- On Wayland, global-hotkey and injection setup needs `ydotool`/`ydotoold`.
- The first run downloads the STT model.
- It is a dictation + command tool, **not** an LLM agent or a full voice-scripting
  platform like Talon.

---

Ready to try it? See **[Install on Linux](install-linux.md)** — or
`pipx install yazses` on any OS with Python ≥ 3.11.
