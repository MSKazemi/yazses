---
title: "Voice dictation compared — YazSes vs Dragon, Wispr Flow, Handy, Vocalinux and more"
description: "YazSes compared with Dragon, Wispr Flow, Handy, Vocalinux, Speech Note and nerd-dictation: which run offline, which support Linux and Wayland, which fits."
---

# Compare

Honest, one-to-one comparisons against the tools people actually weigh YazSes
against. Each page says plainly where the other tool is the better choice —
because if you pick the wrong one on our recommendation, you will just uninstall
both.

If you want everything in a single table instead, see
**[Comparison and alternatives](../comparison.md)**.

## The comparisons

| Compared with | Read this if |
|---|---|
| **[Dragon NaturallySpeaking](dragon-naturallyspeaking-linux-alternative.md)** | You want Dragon on Linux. It has never existed, and this explains what does. |
| **[Wispr Flow](wispr-flow-linux-alternative.md)** | You like Wispr Flow but need Linux, or need dictation that works with no network. |
| **[Handy](yazses-vs-handy.md)** | You are choosing between the two most direct cross-platform open-source options. |
| **[Vocalinux](yazses-vs-vocalinux.md)** | You are on Linux, weighing GPU acceleration and engine choice against cross-platform support. |
| **[Speech Note (dsnote)](yazses-vs-speech-note.md)** | You want to know whether you need an app you open or a daemon that is always there. |
| **[nerd-dictation](yazses-vs-nerd-dictation.md)** | You already run nerd-dictation and want to know if switching buys you anything. |

## The short version

**Runs fully offline, free, open source, and works on Linux:** YazSes,
Handy, Vocalinux, Speech Note, nerd-dictation.

**Does not run on Linux at all:** Dragon, Wispr Flow.

**Does dictation *and* voice commands *and* file transcription *and* meeting
capture from one install:** YazSes. Every other tool on this list does one or two
of those, deliberately — which is a legitimate design choice, not a gap.

## How to read any comparison, including ours

Most feature differences between open-source dictation tools are **temporary**.
Offline Whisper, Wayland support, a tray icon, a command grammar — any active
project can ship these within a couple of releases, and several will.

If you are choosing a tool for this month, compare features. If you are choosing a
project to depend on or contribute to, the more useful question is what it is
structurally able to become. Every dictation tool here answers *"how does the user
start talking?"* with a hardcoded hotkey. YazSes treats that activation channel as
a replaceable part — which is why an EMG muscle sensor and gaze-based targeting
already exist in its tree, and why it can serve people who cannot press a key.

That is the difference that is not a feature, and it is the one worth choosing on.

## Related

- [Comparison and alternatives — the full table](../comparison.md)
- [Offline meeting notes](../meeting-notes-offline.md)
- [Features](../features.md)
- [Capability matrix](../capability-matrix.md)
