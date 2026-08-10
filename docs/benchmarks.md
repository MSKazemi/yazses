---
title: YazSes benchmarks — accuracy, latency and memory on CPU
description: Measured word error rate, decode latency and memory for offline Whisper dictation on a laptop CPU, across tiny.en, base.en and small.en. Full method, hardware, and the commands to reproduce every number.
---

# Benchmarks

Every number on this page was measured on real hardware with the shipping code, and
every one can be reproduced with the commands at the bottom. Nothing here is
estimated, extrapolated, or measured on a machine chosen to flatter the result.

These are the same measurements reported in the
[accompanying paper](https://arxiv.org/abs/2607.28878) (arXiv:2607.28878).

!!! info "Test machine"
    13th Gen Intel Core i7-1370P · 20 logical CPUs · 33.3 GB RAM · Ubuntu 24.04.4
    · Python 3.12.3 · faster-whisper 1.2.1 · YazSes 2.12.0 · **int8 on CPU, no GPU**

    A slower or older CPU will be proportionally slower. Report yours — see
    [contributing](https://github.com/MSKazemi/yazses/blob/main/CONTRIBUTING.md).

## Accuracy — word error rate

**Dataset:** LibriSpeech `test-clean` ([Panayotov et al., ICASSP 2015](https://www.openslr.org/12/)),
200 utterances across 40 speakers, chosen by deterministic speaker-stratified
round-robin so the sample is not cherry-picked. 1,808 seconds of audio in total.
Text is normalised with Whisper's own `EnglishTextNormalizer` before scoring, which
is the standard that makes these numbers comparable with other Whisper results.

| Model | WER | Substitutions | Deletions | Insertions | On-disk size |
|---|---|---|---|---|---|
| `tiny.en` | 4.82 % | 159 | 27 | 39 | 78 MB |
| `base.en` **(default)** | 4.07 % | 145 | 17 | 28 | 148 MB |
| `small.en` | **2.59 %** | 98 | 15 | 8 | 486 MB |

LibriSpeech is read audiobook speech in clean conditions. **Your dictation WER will
be worse than this** — a real microphone in a real room with spontaneous speech is a
harder problem than the benchmark. Treat these as a comparison *between models*, not
as a promise about your desk.

## Speed — how long until the text appears

Decode time for a single utterance, measured end-to-end on 30 utterances (median
duration 7.3 s):

| Model | Cold-start load | Decode, median | Decode, p95 | Real-time factor (median) |
|---|---|---|---|---|
| `tiny.en` | 0.60 s | **0.89 s** | 1.61 s | 0.154 (6.5× faster than real time) |
| `base.en` **(default)** | 0.85 s | **1.56 s** | 3.53 s | 0.283 (3.5× faster than real time) |
| `small.en` | 1.63 s | **5.05 s** | 8.97 s | 0.520 (1.9× faster than real time) |

Read this table before choosing a model. The honest summary:

- **`tiny.en`** feels instant, and costs you about 2.2 points of WER against `small.en`.
- **`base.en`** is the default because it is the best compromise: noticeably more
  accurate than `tiny.en`, and still returns a typical utterance in about a second
  and a half.
- **`small.en`** is the most accurate and is the right choice for transcribing files
  or meetings — but at a **5-second median** for live dictation it is slow enough to
  break your flow. Use it for `yazses transcribe` and Meeting Mode, not for typing.

Change it with `[stt] model` in your config, or see
[performance tuning](how-to/performance-tuning.md).

### Everything that isn't the model is free

The rest of the pipeline is irrelevant to your latency. Measured over 2,000
repetitions each:

| Stage | Median |
|---|---|
| VAD gate | 0.063 ms |
| Text cleaner | 0.005 ms |
| Disfluency filter | 0.147 ms |
| Command grammar (dictation) | 0.075 ms |
| Command grammar (command) | 0.044 ms |
| **Total non-decode overhead** | **0.29 ms** |

That is roughly **0.02 %** of `base.en` decode time. All latency is the speech model;
optimising anything else would be pointless.

## Memory

| Model | RSS after load | Peak RSS | Model's own footprint |
|---|---|---|---|
| `tiny.en` | 857 MB | 873 MB | 37 MB |
| `base.en` | 874 MB | 892 MB | 53 MB |
| `small.en` | 1,340 MB | 1,340 MB | 520 MB |

The 820 MB baseline is the Python process with its dependencies loaded, before any
model. This is the honest cost of a Python daemon — it is why the requirements say
4 GB minimum and 8 GB comfortable.

## Voice-activity gate

The gate that decides whether a recording contains speech at all, tested against 200
LibriSpeech clips as positives and digital silence plus Gaussian noise at 0.1×, 0.25×,
0.5× and 0.75× the threshold as negatives:

| Metric | Result |
|---|---|
| Speech detected | 100 % (200/200) |
| Silence rejected | 100 % |
| Balanced accuracy | 100 % |
| Median speech level vs threshold | 2.4× margin |

The 2.4× margin is why `yazses mic-level --set` matters: the default threshold works
because typical speech sits well above it, but a quiet voice or a low-gain
microphone can fall below it — which shows up as `Silent audio -- discarding` in the
log rather than as an error.

## Command recognition

Whether a spoken phrase is correctly routed to *type this text* or *run this action*.
Tested on 68 command phrases and 80 lines of ordinary dictation:

| Metric | Result |
|---|---|
| Correct action for recognised commands | 100 % (68/68) |
| Commands recognised by the Tier-1 regex grammar | 92.6 % |
| **Dictation misfiring as a command** | **0 % (0/80)** |
| Classification time, median | 0.022 ms |

The zero false-positive rate is the number that matters. A dictation tool that
occasionally interprets your sentence as "delete the last three words" is worse than
one that occasionally fails to recognise a command — the remaining 7.4 % of commands
get typed as text, which is annoying but harmless. The optional Tier-2 SLM router
exists to catch those.

## Dysfluency-Friendly Mode

The opt-in pass that collapses stutters and repeats (`b-b-because` → `because`),
tested against a pre-registered gate defined *before* the evaluation was run
(ADR-015):

| Metric | Result | Pre-registered gate |
|---|---|---|
| False collapse on fluent control speech | **0 %** (33 clips) | < 2 % |
| Recall on dysfluent speech | **92.9 %** (28 clips) | ≥ 60 % |

The false-collapse rate is the safety-critical one: the feature must never mangle
fluent speech. The sample is small — 61 clips — so treat the recall figure as
indicative rather than precise.

## Community results

This table tracks performance across different machines and engines, measured with the community benchmark harness.

| CPU/GPU | Engine (Model) | WER | RTF | Peak RSS |
|---|---|---|---|---|
| Local Virtual Machine (CPU) | `faster-whisper` (`base.en`) | 4.2 % | 0.85x | 215.3 MB |

Want to contribute your machine's benchmark? See [Add your machine](#add-your-machine) below.

## Add your machine

Run the reproducible benchmark harness to measure your machine's performance and add it to the table above.

```sh
# 1. Download a tiny sample of LibriSpeech for a standardised test
uv run python scripts/download-sample.py

# 2. Run the harness
uv run python scripts/bench-stt.py data/librispeech-sample --engine faster-whisper --model base.en
```

The script will output a Markdown row at the end. Open a PR to add your row to the table!

## Reproducing the paper figures

The harness lives in the repository, reuses the shipping code rather than a
reimplementation, and writes JSON with a provenance block recording the exact
hardware and library versions.

```sh
git clone https://github.com/MSKazemi/yazses
cd yazses
uv sync --group benchmark

# one-time: fetch LibriSpeech test-clean (346 MB)
cd paper/data
curl -fsSL -O https://www.openslr.org/resources/12/test-clean.tar.gz
tar -xzf test-clean.tar.gz
cd ../..

# run everything
uv run python paper/benchmark/run_all.py --wer-n 200 --lat-n 30 --vad-n 200

# or a single experiment
uv run python paper/benchmark/bench_wer.py 200
uv run python paper/benchmark/bench_latency.py 30
```

Results land in `paper/results/*.json`. If your numbers differ materially from this
page, that is worth an [issue](https://github.com/MSKazemi/yazses/issues) — different
CPUs are expected to differ, but a large gap on the same class of hardware means
something is wrong and we would like to know.

## What is not measured here

Being explicit about the gaps, because a benchmark that only reports its wins is
not a benchmark:

- **No real-world dictation WER.** Everything above uses read audiobook speech.
  Spontaneous speech into a laptop microphone in a normal room is harder, and we do
  not have a licensed corpus to quantify it.
- **No diarization accuracy.** Meeting Mode's speaker separation has not been scored
  against a labelled multi-speaker corpus. It works well in practice; "well in
  practice" is not a number.
- **No macOS or Windows figures.** All measurements are Linux.
- **Single machine.** One CPU model, one run. There is no variance estimate across
  machines.

Contributions on any of these are welcome, and reporting results from your own
hardware is a genuinely useful first contribution.
