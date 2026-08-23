---
title: "Speech Note alternative — YazSes vs Speech Note (dsnote) on Linux"
description: "YazSes vs Speech Note (dsnote) on Linux: a background dictation daemon versus a note-taking app with speech to text, text to speech and translation."
---

# YazSes vs Speech Note (dsnote)

**Short answer:** these two are less interchangeable than they look.
[Speech Note](https://github.com/mkiol/dsnote) is a **note-taking application**
that happens to include excellent offline speech-to-text, text-to-speech and
translation. YazSes is a **background dictation daemon** whose whole job is to put
your words into whatever window already has focus.

Pick Speech Note if you want an app you open. Pick YazSes if you want dictation
available everywhere without opening anything.

## At a glance

| | Speech Note | YazSes |
|---|---|---|
| Licence | MPL-2.0 | Apache-2.0 |
| Shape | Desktop app you open | Background daemon |
| Engines | whisper.cpp, faster-whisper, VOSK, Coqui STT, april-asr | faster-whisper; Parakeet optional |
| Text to speech | **Yes** | Read-back only |
| Translation | **Yes** | Not a feature |
| Insert into focused window | Yes (X11 native; `ydotool` on Wayland) | Yes (runtime backend probe) |
| Global shortcut | Via XDG portal — KDE Plasma and GNOME | Any desktop; evdev on Linux |
| Voice commands | No | **Yes** |
| Platforms | Linux, Sailfish OS | Linux, macOS, Windows |

## The difference that actually decides it

Speech Note's global shortcut relies on the **GlobalShortcuts XDG portal**, which
its documentation notes is supported by KDE Plasma and GNOME. If you run something
else — a tiling window manager, XFCE, a minimal session — that route may not be
available to you.

YazSes reads the keyboard through evdev on Linux, which is desktop-independent. The
cost is a permission step: your user has to be in the `input` group. That is a real
tax, and `yazses doctor` exists to catch it, but it is paid once and does not depend
on which desktop you run.

## Where Speech Note is clearly ahead

- **It does more kinds of language work.** Text-to-speech and offline translation
  are first-class features. YazSes has read-back but is not a TTS or translation
  tool.
- **More engines, including april-asr and Coqui.** If you want to compare engines
  on your own accent, Speech Note is the better laboratory.
- **A real GUI for working with text.** If your task is *"produce a transcript and
  edit it"*, an app built around a document beats a daemon that types into other
  windows.
- **Sailfish OS**, which nothing else here supports.

## Where YazSes is doing a different job

- **Dictation is always available.** Hold a key in any application and speak. There
  is no window to focus first, which is the entire point of a daemon.
- **Voice commands** mapped to real key sequences.
- **Meeting capture** with speaker labels and optional local-LLM minutes.
- **macOS and Windows** with the same configuration.
- **Accessibility architecture** — VAD calibration, dysfluency-friendly filtering,
  and a replaceable activation channel including an EMG muscle sensor.

## They coexist well

This is a genuine case where running both makes sense: Speech Note for producing
and editing transcripts and for translation, YazSes for dictating into your editor,
browser and terminal all day. They do not compete for the same moment.

```sh
sudo snap install yazses      # or: pipx install yazses
yazses doctor
yazses enroll
yazses start
```

## Related

- [Full comparison with Dragon, Talon, Handy and others](../comparison.md)
- [YazSes vs Vocalinux](yazses-vs-vocalinux.md)
- [Transcribe recordings offline](../use-cases/transcribe-audio-offline.md)
