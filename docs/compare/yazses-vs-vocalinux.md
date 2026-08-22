---
title: Vocalinux alternative — YazSes vs Vocalinux for Linux voice dictation
description: An honest comparison of YazSes and Vocalinux, two offline open-source voice dictation tools for Linux — GPU versus CPU, engine choice, licensing (Apache-2.0 vs AGPL-3.0), and whether you need macOS or Windows too.
---

# YazSes vs Vocalinux

**Short answer:** [Vocalinux](https://github.com/VocaHQ/vocalinux) is the better
choice if you have a capable GPU and want to use it, or if you want to pick
between three recognition engines. YazSes is the better choice if you also need
**macOS or Windows**, if you want the same install to transcribe recordings and
capture meetings, or if you need the accessibility-oriented pieces.

Both are free, open source, run entirely offline on Linux, and work on X11 and
Wayland. This is a genuinely close comparison — the two projects have made
different, defensible choices rather than one being behind the other.

## At a glance

| | Vocalinux | YazSes |
|---|---|---|
| Licence | **AGPL-3.0** | **Apache-2.0** |
| Engines | whisper.cpp (default), Whisper, VOSK | faster-whisper; Parakeet optional |
| Hardware target | GPU-accelerated | CPU int8 |
| Activation | Toggle **or** push-to-talk | Hold-to-talk |
| Platforms | Linux only | Linux, macOS, Windows |
| X11 and Wayland | Yes | Yes |
| Transcribe existing files | Not its focus | `yazses transcribe` |
| Meeting capture + speaker labels | Not its focus | `yazses meeting` |

## The licence difference is worth understanding

This is the difference most likely to actually matter to you, and it is easy to
skim past.

Vocalinux is **AGPL-3.0**. YazSes is **Apache-2.0**. For someone dictating into
their own editor, this changes nothing at all — use either. It starts to matter if
you intend to *build on* the tool: the AGPL's network clause reaches further than
most permissive-licence users expect, and Apache-2.0 also carries an explicit
patent grant. If you are embedding a dictation engine into something you ship,
read both licences rather than taking a comparison table's word for it.

## GPU versus CPU is a real fork in the road

Vocalinux advertises GPU acceleration. YazSes deliberately targets **CPU int8**.

Neither is the "right" answer — they optimise for different machines:

- **If you have a discrete GPU**, Vocalinux can use hardware that YazSes will
  leave idle. On long dictation sessions that is a genuine speed advantage.
- **If you are on a laptop, a thin client, or a machine with integrated
  graphics**, CPU int8 is the design that assumes nothing about your hardware.
  It is also what lets the same configuration run unchanged on macOS and Windows.

If you have a strong GPU and only use Linux, that is a real argument for Vocalinux.

## Engine choice versus one tuned path

Vocalinux lets you pick between whisper.cpp, OpenAI Whisper and VOSK. That is
useful if you want VOSK's tiny footprint on old hardware, or you already know which
engine suits your accent.

YazSes ships one well-tuned default (faster-whisper) with an optional second engine
(NVIDIA Parakeet, behind `yazses features enable stt-parakeet`). Fewer choices, more
opinion. Which you prefer is temperament as much as requirement.

## Where YazSes is doing something different

These are outside Vocalinux's scope rather than places it falls short:

- **Three jobs, one install.** Live dictation, offline transcription of existing
  recordings (`yazses transcribe`, with optional speaker diarization), and
  hands-free whole-meeting capture producing a speaker-labelled transcript and
  optional local-LLM minutes (`yazses meeting`).
- **Accessibility as an architecture, not a checkbox.** VAD calibration, a
  dysfluency-friendly filter for stuttered or dysarthric speech, and an activation
  layer that treats the hotkey as a replaceable part — a USB-serial EMG muscle
  sensor is an existing alternative implementation for people who cannot hold a key.
- **An opt-in on-device learning loop.** `yazses tune` reads an encrypted local
  corpus of your own corrections and proposes concrete config changes.
- **macOS and Windows**, with the same configuration file.

## When to choose Vocalinux

- You have a GPU you want used.
- You only use Linux, and cross-platform support is worth nothing to you.
- You specifically want VOSK, or want to switch engines to compare them.
- You prefer a copyleft licence on principle.

A smaller tool that does one thing well is not a worse tool.

## Trying YazSes alongside it

The two can be installed at the same time while you decide — just do not bind them
to the same key.

```sh
sudo snap install yazses      # or: pipx install yazses
yazses doctor
yazses hotkey set <key>
yazses enroll
yazses start
```

## Related

- [Full comparison with Dragon, Talon, Handy and others](../comparison.md)
- [YazSes vs nerd-dictation](yazses-vs-nerd-dictation.md)
- [YazSes vs Speech Note](yazses-vs-speech-note.md)
- [Voice dictation on Wayland](../use-cases/voice-dictation-wayland.md)
