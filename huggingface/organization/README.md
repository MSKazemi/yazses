---
title: YazSes
emoji: 🎙️
colorFrom: purple
colorTo: indigo
sdk: static
pinned: false
short_description: Free, open-source, offline voice typing for Linux, macOS and Windows.
license: apache-2.0
---

# YazSes

**Offline voice typing for Linux, macOS and Windows.** Hold a key, speak, release. The words
are typed into whatever app you are using.

YazSes runs speech recognition on your own computer, so your voice does not leave it. It is
free and open source under the Apache-2.0 licence. It needs no account, no subscription and
no API key.

## What it does

- **Type with your voice** (always on). Hold the hotkey, speak, release. The text goes into
  the window that has focus.
- **Voice commands** (on by default). Say "undo that", "go to line 42" or "run the tests" and
  YazSes carries out the action instead of typing the words.
- **Recording transcription** (optional, off by default). `yazses transcribe` turns an audio
  or video file into text. Enable it with `yazses features enable recimport`.
- **Meeting capture** (optional, off by default). `yazses meeting start` and `yazses meeting stop`
  record a meeting and write a transcript. Speaker labels need the optional diarization extra.
- **Other optional features**, all off until you turn them on: voice punctuation, a
  voice-activity overlay, an encrypted local learning loop, and the NVIDIA Parakeet and
  Moonshine speech engines as alternatives to Whisper.

Dictation works out of the box. Each optional feature is switched on with
`yazses features enable <name>` and applied with `yazses restart`.

**Limits.** The default speech models are English (`*.en`). YazSes is a desktop program. It
is not a chatbot or an AI agent, and it has no mobile or web app.

## Privacy, in plain words

- Speech recognition uses [faster-whisper](https://github.com/SYSTRAN/faster-whisper) on your
  CPU. By default, no audio, transcripts, editor context or usage data leave your computer.
- The speech model is downloaded once from Hugging Face the first time you use it. After
  that, dictation needs no network connection.
- Two opt-in features can send text you dictated: `yazses remote <host>`, and dictation
  cleanup through Ollama. Both are off by default.

Read the full [privacy statement](https://mskazemi.com/yazses/privacy-statement.html).

## Hosted demo: a different privacy setting

**[Open the hosted demo](https://huggingface.co/spaces/mskazemi/yazses-offline-transcription-demo)**
to try the accuracy of the same engine and model in a browser.

This is a hosted demonstration. Audio submitted here is processed on Hugging Face infrastructure.
For private, offline voice typing, install YazSes on your own computer.

## Platforms and how far they have been verified

| Platform | Status |
|---|---|
| Linux (X11 and Wayland) | The primary platform, and the one with the most reports from real machines. |
| macOS 14 or later, Apple silicon (M1 or newer) | Preview. |
| Windows 10 (21H2) or later | Preview. |

The project's [validation matrix](https://mskazemi.com/yazses/validation-matrix.html) lists what
has been confirmed on real hardware, with the evidence for each entry. The maintainer does not
own a Mac or a Windows PC, so results for those systems come from volunteers. A short report
from a real machine is one of the most useful contributions you can make.

## Install

- [Linux guide](https://mskazemi.com/yazses/install-linux.html)
- [macOS guide](https://mskazemi.com/yazses/macos-install.html)
- [Windows guide](https://mskazemi.com/yazses/windows-install.html)
- [Try it without installing](https://mskazemi.com/yazses/try-without-installing.html), in Docker or the browser
- [What installing actually costs](https://mskazemi.com/yazses/install-cost.html), before you start
- Python package: [yazses on PyPI](https://pypi.org/project/yazses/)

## Research

**Paper:** *YazSes: An Offline, Privacy-First, Cross-Platform Hold-to-Talk Voice-Dictation System*,
by Mohsen Seyedkazemi Ardebili. arXiv:2607.28878. https://arxiv.org/abs/2607.28878

**Benchmarks.** With the default `base.en` model, the paper and the
[benchmarks page](https://mskazemi.com/yazses/benchmarks.html) report a word error rate of
4.07 % on a 200-utterance subset of LibriSpeech `test-clean`. Median decode time was 1.56 s on a
13th-generation Intel Core i7 laptop CPU, with int8 inference and no GPU. Read speech in a
clean recording is easier than dictation on your own microphone, so expect your own results to
differ.

**Reproduce.** The benchmark commands and the method are on the benchmarks page. Every archived
measurement, including runs that were later superseded, is listed in the
[results manifest](https://github.com/MSKazemi/yazses/blob/main/paper/results/MANIFEST.md).

## Models used (third-party, not trained by YazSes)

YazSes does not train speech models. It uses these open models:

- **faster-whisper** speech models by SYSTRAN: `tiny.en`, `base.en` (default) and `small.en`
  ([tiny.en](https://huggingface.co/Systran/faster-whisper-tiny.en),
  [base.en](https://huggingface.co/Systran/faster-whisper-base.en),
  [small.en](https://huggingface.co/Systran/faster-whisper-small.en)).
- **Optional engines:** NVIDIA Parakeet TDT (`parakeet-tdt-0.6b-v2`, English) and Moonshine
  (`moonshine/base`, English). Each is off until you enable it.

Each model's own licence and terms apply to that model.

## Contribute

YazSes is open source and welcomes contributions that need no speech or AI background:

- [Test it on your computer and report what happened](https://mskazemi.com/yazses/contribute/start.html).
- [Open issues](https://github.com/MSKazemi/yazses/issues)
- [Good first issues](https://github.com/MSKazemi/yazses/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22)
- [Source code](https://github.com/MSKazemi/yazses)

If YazSes is useful to you, a star on GitHub helps other people find it.

## Licence and attribution

YazSes is released under the [Apache License 2.0](https://github.com/MSKazemi/yazses/blob/main/LICENSE).
See the [NOTICE file](https://github.com/MSKazemi/yazses/blob/main/NOTICE) for attribution.
Documentation: [mskazemi.com/yazses](https://mskazemi.com/yazses/).
