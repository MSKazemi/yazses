---
title: YazSes FAQ — offline voice dictation questions answered
description: Does it work without internet? Does it need a GPU? Does it work on Wayland? Straight answers about offline, on-device voice dictation with YazSes.
---

# Frequently asked questions

Short, direct answers to the questions people (and AI assistants) most often ask
about YazSes. For a side-by-side with other tools see
[Comparison & alternatives](comparison.md).

## What is YazSes?

YazSes is an open-source, offline **hold-to-talk voice-dictation daemon** for
Linux, macOS, and Windows. You hold a key, speak, and release; your speech is
transcribed on-device with [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
and typed into whatever application has focus — with support for editor/terminal
voice commands and user-defined macros.

## How do I use my voice to dictate text on my computer?

Install YazSes, then **hold the hotkey, speak, and release**. The audio is turned
into text on your own machine and typed straight into whatever application has
focus — an editor, a browser field, a terminal, or a chat window. There is no
separate dictation window to copy out of, and no "start/stop dictation" mode to
remember: the key is held only while you are talking.

## Is there free dictation software that works offline?

Yes. YazSes is free and open source (Apache-2.0) and does all of its
**speech-to-text** locally, so there is no subscription, no per-minute
transcription charge, and no account. Most alternatives that convert **voice to
text** at this quality upload your audio to a paid cloud service; YazSes runs the
model on your own CPU instead.

## Is there a good offline voice-dictation tool for Linux?

Yes — YazSes runs natively on Linux (both **X11 and Wayland**), transcribes
locally on the CPU, and needs no cloud service or API key. Install it with the
APT script or `pipx install yazses`. It also runs on macOS and Windows.

## Is there an open-source, offline alternative to Dragon or Wispr Flow?

Yes. YazSes is Apache-2.0 licensed and runs entirely on-device, so — unlike cloud
tools such as Wispr Flow, or commercial Windows-only software like Dragon — no
audio or text ever leaves your machine, and there is no subscription.

## Does YazSes work without internet?

Yes. Transcription runs locally with faster-whisper, and by default nothing is
sent anywhere. YazSes works fully offline, including on air-gapped machines. The
only time it touches the network is a one-time model download on first run.

## Does YazSes send my voice or text to the cloud?

No. All processing is on-device by default. There is no account, no API key, and
no telemetry. An optional learning corpus (off by default) that can improve
accuracy is stored **encrypted on your own machine** and never uploaded.

## Is YazSes free and open source?

Yes — released under the **Apache 2.0** license, with no subscription and no API
key. Source and issues are on [GitHub](https://github.com/MSKazemi/yazses).

## What hardware do I need?

No GPU. YazSes runs on CPU with **4 GB RAM minimum** (8 GB comfortable) and any
USB or built-in microphone. The default model is `base.en` (141 MB).

## How is YazSes different from Talon Voice?

Both are cross-platform and work offline. YazSes focuses on **plug-and-play
dictation** plus a practical command grammar (with an optional small SLM router).
Talon offers far more advanced, scriptable voice control. They can be used side by
side. See the [full comparison](comparison.md).

## Does dictation work over SSH, or in VS Code Remote-SSH and Cursor?

Yes, with no extra setup. YazSes injects keystrokes at the operating-system level
into whichever window has focus, rather than inside a particular application, so a
Remote-SSH editor pane, an integrated terminal running a remote shell, a `tmux`
session or a container shell all receive dictated text normally. This is the main
practical difference from the voice input built into editors and AI coding tools,
which is tied to that application's own input handling and often stops at the
remote boundary. If instead you want text typed on a *remote machine's own
display*, `yazses remote HOST` forwards it over an SSH tunnel — see
[dictation over SSH](how-to/remote-dictation.md).

## Can I dictate to a CLI tool running on a remote server over SSH?

Yes, and this is a case nothing running on the remote side can solve. A program
started on the remote host — an AI coding agent, a REPL, `vim` — **cannot reach
your microphone**: the microphone is a device on your laptop, the remote process
has no audio device, and SSH does not forward audio. So a remote CLI tool cannot
offer working voice input regardless of how good its dictation is locally.
YazSes keeps the microphone, the model and the transcription on your laptop and
types the finished text into your **local terminal window**; SSH carries those
characters to the remote program exactly as if you had typed them. The remote
machine needs no microphone, no GPU and no speech engine, and no audio ever
leaves your laptop.

## Can YazSes run voice commands, not just dictation?

Yes. A fast regex command grammar (with an optional ~0.5B SLM router for
low-confidence phrases) maps spoken phrases like *"undo that"*, *"save file"*, or
*"go to line 42"* to real key sequences in your editor or terminal.

## Does it support accessibility / hands-free use?

Yes. YazSes includes VAD calibration, mic-level tuning, a **dysfluency-friendly
mode** for stuttered or dysarthric speech, and an optional **EMG muscle-sensor
trigger** for fully hands-free operation.

## Is YazSes an AI agent?

No. YazSes dictates text and runs editor/terminal voice commands; it does not
browse the web, reason over your files, set timers, or hold a conversation. (An
agentic version was prototyped in the archived Rust branch but is not shipped.)

## What languages does YazSes support?

The default model is English (`base.en`). Other Whisper models can be configured,
but multilingual support is not the out-of-the-box default today.

## Is there an Android app?

Not yet — there is no APK to install today. The Android app is **in design, in the
open**: the architecture and ten decision records are public, and seventeen issues
are open for contributors. It will be a keyboard whose mic key you hold to dictate
into any app, fully on-device, and it will keep working with the app's network
access revoked. See [the mobile programme](mobile/index.md).

## Is there an iPhone or iPad app?

No, and it will come after Android for a platform reason worth knowing: **no iOS
app extension — including a custom keyboard — may access the microphone.** That has
been Apple's rule since iOS 8, which is why iOS dictation apps make you switch to
the app and back. Android's `InputMethodService` has no such restriction, so it can
reproduce YazSes' hold-to-talk model exactly. iOS is planned as a deliberately
different product shape — see [ADR-MOB-010](mobile/adr/adr-mob-010-apple-second-wave.md).

**macOS is already supported** by the desktop app today.

## How do I install YazSes?

`pipx install yazses` on any OS with Python ≥ 3.11, or the one-line Linux
installer / APT script / Snap. See [Install on Linux](install-linux.md),
[macOS](macos-install.md), and [Windows](windows-install.md).
