---
title: nerd-dictation alternative — YazSes vs nerd-dictation for Linux voice typing
description: A detailed, honest comparison of YazSes and nerd-dictation for offline Linux voice dictation - hold-to-talk versus begin/end commands, Whisper versus VOSK accuracy, Wayland support, and a step-by-step guide to migrating your nerd-dictation setup.
---

# YazSes vs nerd-dictation

**Short answer:** [nerd-dictation](https://github.com/ideasman42/nerd-dictation) is
the better choice if you want maximum minimalism, the smallest possible resource
footprint, and you enjoy configuring behaviour by writing Python. YazSes is the
better choice if you want a **hold-to-talk key** instead of explicit begin/end
commands, **Whisper-class accuracy** instead of VOSK, and the same install to work
on **macOS and Windows** as well as Linux.

Both are free, open source, and run entirely offline. Neither sends your voice
anywhere. This page is for people who already run nerd-dictation and are deciding
whether switching buys them anything.

## At a glance

| | nerd-dictation | YazSes |
|---|---|---|
| Licence | GPLv3 | Apache-2.0 |
| Recognition engine | VOSK | faster-whisper (CPU int8) |
| Activation | Explicit `begin` / `end` commands | Hold a key, speak, release |
| Background process | None by design | A daemon (`yazses start`) |
| Platforms | Linux only | Linux, macOS, Windows |
| Customisation | Python string operations | TOML config + personal vocabulary |
| Footprint | Very small VOSK models | Larger Whisper models |

## The difference that actually changes how it feels

nerd-dictation is started and stopped by running commands. You bind
`nerd-dictation begin` to one shortcut and `nerd-dictation end` to another, or wrap
both in a script. It is explicit, scriptable, and completely predictable.

YazSes is **hold-to-talk**: you hold one key for as long as you are speaking and
release it when you are done. Nothing is listening when the key is up.

The practical consequence is what happens when you pause mid-sentence. With a
begin/end model, a pause is just silence inside an open recording session. With
hold-to-talk, the key is still held, so a pause is still *your turn* — silence is
thinking time rather than a signal to stop. Which of these you prefer is genuinely
a matter of taste, and it is the main thing to try before switching.

## Accuracy: VOSK versus Whisper

This is the clearest technical difference. nerd-dictation uses the VOSK API with
famously small models — that is what makes it start instantly and use very little
memory. YazSes uses faster-whisper, which is more accurate on natural speech,
punctuation, and unusual vocabulary, at the cost of a larger model download and
more CPU per utterance.

If VOSK's accuracy is already good enough for what you dictate, that is a real
argument for staying — you are paying nothing for it. The accuracy gap is most
visible on proper nouns, technical terms, and long unbroken sentences.

YazSes targets **CPU int8** deliberately so it runs on modest hardware. If you have
a strong GPU and want to use it, neither of these is the right tool — a
whisper.cpp-based project will transcribe faster.

## Wayland

Both projects have to solve the same problem: Wayland deliberately prevents one
application from synthesising input into another, which breaks the `xdotool`
approach that worked on X11.

YazSes probes the session at runtime and selects a working injection backend —
`ydotool`, `wtype`, `xdotool`, or clipboard paste — rather than assuming one.
`yazses doctor` reports which backend it selected and whether its tools are
installed; `yazses verify` goes further and runs the real chain end to end,
naming the first link that is actually broken.
See [voice dictation on Wayland](../use-cases/voice-dictation-wayland.md) for the
details.

## What YazSes adds beyond dictation

These are the things that are simply not in nerd-dictation's scope, and they are
the honest reason to switch if any of them matter to you:

- **Voice commands** — spoken phrases mapped to real key sequences by a regex grammar.
- **Personal vocabulary** — `yazses vocab add` teaches it words it keeps mis-hearing.
- **File transcription** — `yazses transcribe <file>` turns an existing recording into text.
- **Meeting capture** — hands-free whole-meeting recording with speaker labels.
  Off by default, and the speaker labels need an optional extra plus a one-time
  ~45 MB model download: `yazses features enable meeting`.
- **Accessibility work** — VAD calibration, dysfluency-friendly filtering, alternative
  activation hardware.
- **macOS and Windows** — the same configuration, on all three systems.

If you want none of these, that is a legitimate reason to stay on nerd-dictation.
A smaller tool that does one thing is not a worse tool.

## Migrating from nerd-dictation

Nothing here removes nerd-dictation — the two can be installed side by side while
you decide, as long as you do not bind them to the same key.

1. **Install.**

    ```sh
    pipx install yazses     # or: sudo snap install yazses
    ```

2. **Check the three things that actually break.** Microphone capture, keyboard
   access, and text injection:

    ```sh
    yazses doctor
    ```

    Two Linux-specific gotchas it will catch: `libportaudio2` is required for
    microphone capture and is **not** pulled in by pipx, and reading the keyboard
    needs membership of the `input` group — after `sudo usermod -aG input $USER`
    you must log out and back in.

3. **Calibrate to your voice and room** — roughly thirty seconds. This replaces
   nothing in nerd-dictation; there is no equivalent step:

    ```sh
    yazses enroll
    ```

4. **Bring your vocabulary across.** If you customised nerd-dictation's output with
   Python string replacements for names or jargon, the equivalent is the personal
   dictionary:

    ```sh
    yazses vocab add Kubernetes
    ```

5. **Pick your key.** nerd-dictation users are used to binding two shortcuts; here
   you bind one and hold it:

    ```sh
    yazses hotkey set <key>
    ```

6. **Start it.**

    ```sh
    yazses start
    ```

If dictation produces nothing, the usual cause is that your speech is falling below
the silence gate. `yazses mic-level --set` measures your actual microphone level and
writes a matching threshold.

## When to stay with nerd-dictation

- You want no background process at all. YazSes runs a daemon; that is a real
  architectural difference, not a detail.
- Your machine is old or memory-constrained enough that VOSK's small models are the
  point.
- You genuinely prefer configuring behaviour in Python to editing TOML.
- You only ever use Linux, and none of the extras above interest you.

## Related

- [Full comparison with Dragon, Talon, Vocalinux and others](../comparison.md)
- [Offline voice dictation on Linux](../use-cases/voice-dictation-linux.md)
- [Voice dictation on Wayland](../use-cases/voice-dictation-wayland.md)
- [Install on Linux](../install-linux.md)
