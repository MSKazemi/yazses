---
title: YazSes and Hugging Face — what runs where, and what each page is for
description: How YazSes uses Hugging Face (it downloads speech models from the Hub once), what the hosted demo Space does with your audio, and how the project's source, benchmarks and paper relate to the Hub.
---

# YazSes and Hugging Face

Hugging Face shows up in three different roles around YazSes. They have different privacy
properties, so this page keeps them apart.

## 1. The installed app: Hugging Face is where the model comes from

YazSes on your computer recognises speech **locally**, on your own CPU. It needs no
account, no subscription and no cloud inference API.

The one time it uses the network is to fetch the speech model. The default models are
open [faster-whisper](https://github.com/SYSTRAN/faster-whisper) conversions published by
SYSTRAN on the Hugging Face Hub. After that single download, dictation works with the
network off. Which models, and how to install one by hand on a machine that cannot reach
the Hub, is on [Models](models.md); every network connection YazSes can make is listed on
the [privacy statement](privacy-statement.md).

YazSes does not train these models, and using the Hub as a download host does not make
Hugging Face the maintainer of YazSes. Each model's own licence and terms apply to it.

## 2. The hosted demo: audio *does* leave your computer

There is one YazSes page on Hugging Face that runs speech recognition for you:

**[YazSes hosted transcription demo](https://huggingface.co/spaces/mskazemi/yazses-offline-transcription-demo)**

!!! warning "This is not the private, offline app"
    This is a hosted demonstration. Audio submitted here is processed on Hugging Face
    infrastructure. For private, offline voice typing, install YazSes on your own computer.

What it is for, and what it is not:

| | Hosted demo (Hugging Face Space) | YazSes installed on your computer |
|---|---|---|
| Where speech is processed | Hugging Face servers | Your own CPU |
| Does your audio leave your computer? | **Yes** | No (the model is downloaded once, then nothing leaves) |
| Hold-to-talk anywhere on the desktop | No | Yes |
| Types into the focused application | No | Yes |
| Purpose | Judge transcription quality before installing | Everyday dictation |

The demo uses the same engine family and the same default model size as the desktop app
(faster-whisper `base.en`, CPU, `int8`), but it is **not** the same pipeline, so a
transcript there is an indication of accuracy, not a guarantee of what the app would type.
It trims silence with the decoder's voice-activity filter, which the desktop app
deliberately does not use, and it applies none of the app's text post-processing.

The demo's code adds no logging or analytics of its own. It makes no promise about what
Hugging Face itself logs or keeps; that is governed by Hugging Face's own policies.

## 3. Research and source

- **GitHub is the canonical home** of the source code, the issue tracker and every
  contribution: <https://github.com/MSKazemi/yazses>.
- **The first paper**, *YazSes: An Offline, Privacy-First, Cross-Platform Hold-to-Talk
  Voice-Dictation System* ([arXiv:2607.28878](https://arxiv.org/abs/2607.28878)),
  describes the system. Cite it, or the software's concept DOI, as `CITATION.cff` says.
- **Benchmark results** behind the published numbers are archived as JSON in
  [`paper/results/`](https://github.com/MSKazemi/yazses/tree/main/paper/results), with a
  [manifest](https://github.com/MSKazemi/yazses/blob/main/paper/results/MANIFEST.md) naming the
  machine each one was taken on. Two numbers are comparable only if their machine matches.
  The method and headline results are on [Benchmarks](benchmarks.md).

## What is prepared but not published yet

The repository carries the source for a few more Hugging Face pages under
[`huggingface/`](https://github.com/MSKazemi/yazses/tree/main/huggingface). **None of them
is live, and nothing links to them as if it were:**

| Prepared | What it is |
|---|---|
| Organization card and a static showcase Space | A short introduction and a one-page overview, for an official `yazses` organization that has not been created |
| Benchmark dataset | The archived results as plain CSV tables with provenance (machine, versions, corpus), under a dataset card. It contains no audio, no transcripts and no corpus text |
| Research collection | A curated list: the paper, the demo, the dataset and the upstream models |

Publishing any of them is a manual decision by the maintainer. The files are checked
offline by `scripts/hf_preflight.py` before anything can go out, and the benchmark tables
are regenerated from the archive by `scripts/export_hf_benchmarks.py` (`--check` fails on
drift). The publishing workflow is manual-only, uses Hugging Face Trusted Publishers with
short-lived credentials rather than a stored token, and refuses any destination the
maintainer has not approved in a reviewed commit.

## Related

- [Try it without installing](try-without-installing.md): Docker, the hosted demo and Codespaces
- [Models](models.md): which speech models YazSes can run
- [Privacy statement](privacy-statement.md)
- [Benchmarks](benchmarks.md)
