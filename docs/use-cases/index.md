---
title: What people use YazSes for — offline voice dictation use cases
description: Real use cases for offline, on-device voice dictation — Linux and Wayland voice typing, confidential work, coding by voice, RSI and hands-free accessibility, offline transcription, meeting notes and minutes, dictating to remote servers, and multilingual dictation.
---

# What people use YazSes for

YazSes is one program — hold a key, speak, release, and your words are typed into
whatever app has focus, transcribed entirely on your own machine. But people arrive
at it from very different problems.

These pages start from **the problem**, not the feature list. Each one explains
whether YazSes actually solves it, what to turn on, and — honestly — where it
falls short.

<div class="grid cards" markdown>

-   :material-linux:{ .lg .middle } **Voice typing on Linux**

    ---

    Dictation that works on both X11 and Wayland, in any application, with no
    cloud service behind it.

    [:octicons-arrow-right-24: Voice dictation on Linux](voice-dictation-linux.md)

-   :material-wave:{ .lg .middle } **Dictation on Wayland**

    ---

    Wayland blocks apps from typing into each other, which silently breaks most
    dictation tools. How YazSes gets around it on GNOME, KDE, sway and Hyprland.

    [:octicons-arrow-right-24: Voice dictation on Wayland](voice-dictation-wayland.md)

-   :material-shield-lock:{ .lg .middle } **Confidential & offline work**

    ---

    When the audio legally or practically cannot be uploaded — clinical notes,
    legal work, classified or air-gapped machines.

    [:octicons-arrow-right-24: Private offline dictation](private-offline-dictation.md)

-   :material-code-braces:{ .lg .middle } **Writing code by voice**

    ---

    Spoken symbols, LaTeX maths, git phrases turned into git commands, and a
    safety gate before a destructive shell command runs.

    [:octicons-arrow-right-24: Voice coding](voice-coding.md)

-   :material-robot-outline:{ .lg .middle } **Prompts for AI coding agents**

    ---

    Dictate long prompts into Claude Code, Codex or a chat app. Hold-to-talk
    never cuts you off mid-thought, and nothing leaves your machine.

    [:octicons-arrow-right-24: Voice input for AI agents](voice-input-for-ai-agents.md)

-   :material-code-tags:{ .lg .middle } **Code and technical vocabulary**

    ---

    Get identifiers, jargon and punctuation right — personal vocabulary,
    `initial_prompt`, vocabulary correction and spoken punctuation.

    [:octicons-arrow-right-24: Dictating code](dictating-code.md)

-   :material-scale-balance:{ .lg .middle } **Law, medicine & journalism**

    ---

    Dictation and transcription under a confidentiality duty, where the audio
    may not leave the building — what it does, and what it does not promise.

    [:octicons-arrow-right-24: Confidential professions](confidential-professions.md)

-   :material-microphone-message:{ .lg .middle } **Controlling the computer**

    ---

    Undo, save, jump to a line, run the tests, or fire a multi-step macro —
    with the same key that types your words.

    [:octicons-arrow-right-24: Voice commands & macros](voice-commands.md)

-   :material-human-cane:{ .lg .middle } **RSI & hands-free access**

    ---

    For repetitive strain injury, motor impairment, dysfluent speech, or
    eyes-free use — including non-keyboard triggers.

    [:octicons-arrow-right-24: Accessibility & RSI](accessibility-rsi-hands-free.md)

-   :material-file-music:{ .lg .middle } **Transcribing recordings**

    ---

    Turn an existing audio or video file into text, with speaker labels, without
    uploading it anywhere.

    [:octicons-arrow-right-24: Offline transcription](transcribe-audio-offline.md)

-   :material-school:{ .lg .middle } **Research interviews**

    ---

    A tool-neutral guide for qualitative researchers: why cloud transcription
    raises consent and ethics questions, and the free local options.

    [:octicons-arrow-right-24: Research interview transcription](research-interview-transcription.md)

-   :material-account-group:{ .lg .middle } **Meetings & minutes**

    ---

    Record a whole meeting hands-free and get a speaker-labelled transcript —
    and optional minutes — without a bot joining the call.

    [:octicons-arrow-right-24: Offline meeting notes](../meeting-notes-offline.md)

-   :material-console-network:{ .lg .middle } **Dictating to a remote server**

    ---

    Speak into your laptop mic; the text is typed on the machine you are
    SSH'd into.

    [:octicons-arrow-right-24: Dictation over SSH](../how-to/remote-dictation.md)

-   :material-translate:{ .lg .middle } **More than one language**

    ---

    Dictating in a non-English language with a multilingual Whisper model you
    choose — a how-to, not a support claim.

    [:octicons-arrow-right-24: Multilingual dictation](multilingual-dictation.md)

-   :material-ideogram-cjk:{ .lg .middle } **Chinese & Mandarin**

    ---

    Point YazSes at a multilingual model for Mandarin, and avoid the
    Simplified/Traditional trap.

    [:octicons-arrow-right-24: Chinese voice typing](chinese-voice-typing.md)

-   :material-earth:{ .lg .middle } **Hindi & Indian languages**

    ---

    Configure a multilingual Whisper model for Hindi and other Indian languages,
    and what to expect when Devanagari is typed.

    [:octicons-arrow-right-24: Hindi voice typing](hindi-voice-typing.md)

</div>

## The common thread

Every use case above is served by the same install and the same locally downloaded
model. Nothing on this site requires an account, an API key, a subscription, or a
network connection after install.

If you are comparing YazSes against Dragon, Talon, Wispr Flow, nerd-dictation or
cloud dictation, the [comparison page](../comparison.md) is deliberately honest
about which of them wins for which job.

## Not sure where to start?

```sh
yazses quickstart   # the three steps to get dictating, tailored to your machine
```

See also the [FAQ](../faq.md) and the [install guide for your platform](../install-linux.md).
