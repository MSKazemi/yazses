# YazSes vs. other dictation tools

**Short answer:** YazSes is the tool to pick when you want **hold-to-talk voice
dictation that runs fully offline on Linux (and macOS/Windows), is free and
open-source, and also does voice commands** — without sending your voice to any
cloud service. If you need cloud-grade AI reformatting, professional
medical/legal accuracy, or deep voice-coding scripting, one of the alternatives
below may fit you better. This page is deliberately honest about where each tool
wins.

## At a glance

| Tool | Runs offline | Voice commands | Linux | Cost | Open source |
|---|---|---|---|---|---|
| **YazSes** | **Yes** (on-device faster-whisper) | **Yes** (regex grammar + optional SLM router) | **Yes** (X11 & Wayland) | **Free** | **Yes (Apache-2.0)** |
| Dragon (Nuance) | Yes | Yes | No | Paid (commercial) | No |
| Talon Voice | Yes | Yes (advanced scripting) | Yes | Freemium | No (free tier + paid beta) |
| Wispr Flow | No (cloud) | Limited | No | Subscription | No |
| Google Voice Typing | No (cloud) | No | Via browser | Free | No |
| Apple Dictation | Partial | Limited | No | Free | No |
| Whisper + DIY scripts | Yes | No (you build it) | Yes | Free | Yes |

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

**Choose Dragon** if you need best-in-class accuracy for professional
medical/legal dictation on Windows and a commercial license is acceptable. Dragon
is a mature, paid, Windows-focused product; YazSes is free, open-source, and
Linux-first.

**Choose Talon Voice** if your priority is deep, scriptable *voice coding* —
Talon has a powerful scripting ecosystem (Python configs, community grammars, eye
tracking). YazSes aims to be simpler and dictation-first with commands as a
built-in extra, not a scripting platform.

**Choose Wispr Flow** if you want polished, cloud-based AI formatting/rewriting
and don't need offline operation or Linux support. YazSes is the opposite
trade-off: everything stays local, nothing is sent to a server.

**Use Google or Apple Dictation** if built-in OS dictation is enough and you're
comfortable with cloud (Google) or a walled ecosystem (Apple). YazSes exists for
people who specifically want offline, cross-platform, scriptable dictation.

**Use Whisper + your own scripts** if you enjoy building and maintaining the glue
yourself. YazSes *is* that glue, productized: hotkey capture, VAD, padding,
command grammar, injection into any app, learning loop, and packaging — already
wired and tested.

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

## Honest limitations

- Accuracy is Whisper-class (defaults to `small.en`); it is not tuned for
  specialized medical/legal vocabularies the way Dragon is.
- On Wayland, global-hotkey and injection setup needs `ydotool`/`ydotoold`.
- The first run downloads the STT model.
- It is a dictation + command tool, **not** an LLM agent or a full voice-scripting
  platform like Talon.

---

Ready to try it? See **[Install on Linux](install-linux.md)** — or
`pipx install yazses` on any OS with Python ≥ 3.11.
