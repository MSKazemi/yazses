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
    [contributing](https://github.com/MSKazemi/yazses/blob/main/.github/CONTRIBUTING.md).

!!! tip "Measure your own machine, without running anything"
    `yazses status` reports **p50 and p95 decode latency per model** from your own
    dictation — no benchmark run, no dataset, nothing to enable. This page is one
    machine; that is yours. See
    [`yazses status`](cli-reference.md#yazses-status).

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

## Speech end → text: what you actually wait for

The table above measures the model. This measures **you**: from the moment you stop
speaking, how long until the text is there? It is the number commercial dictation
products advertise, so it is the one worth publishing.

**Method:** 15 speaker-stratified LibriSpeech utterances (median duration 10.4 s), fed
at **real time** — a microphone delivers 100 ms of audio every 100 ms, and a benchmark
that feeds faster than that invents a machine which hears the future. Reproduce with
`uv run python paper/benchmark/bench_streaming.py 15`. Same machine as above.

| Model | Batch (default) | Streaming | Text already visible at release |
|---|---|---|---|
| `tiny.en` | **0.92 s** | 1.22 s | 72 % |
| `base.en` **(default)** | **1.42 s** | 2.21 s | **0 %** |

Two results here are worth stating bluntly, because both cut against the feature.

**Streaming does not make the final text arrive sooner. It makes it arrive later.**
`StreamingEngine.commit()` re-decodes the whole utterance on release regardless, so
streaming adds a decode loop running every 300 ms *alongside* the decode that actually
produces your text. On a CPU they compete. That costs 32 % on `tiny.en` and 56 % on
`base.en`.

**On the default model, streaming usually shows you nothing at all.** In 9 of 15
`base.en` utterances, **not one partial was confirmed before the key was released** —
median visible-at-release 0 %. LocalAgreement only emits a prefix two consecutive
decode passes agree on, and on `base.en` a rolling window over a growing 10-second
buffer takes long enough that the audio ends first. `tiny.en` is fast enough to keep
up (72 % visible, a partial in every single utterance).

So the honest guidance is narrower than "streaming buys perceived latency":

- **`[streaming] enabled = true` is only worth it on `tiny.en`.** There it does what it
  claims — most of your sentence is on screen before you let go — at the cost of ~0.3 s
  on the final text and considerably more CPU.
- **On `base.en` or `small.en`, enabling streaming is a straight loss:** a slower final
  result, usually with no live text to show for it. This is a real trap, because
  `yazses features enable streaming` does not currently check which model you run.
- It remains **off by default**, which these numbers support independently of the
  injection-correctness reason it was originally defaulted off for
  ([troubleshooting](troubleshooting.md)).

Caveats, in the spirit of the rest of this page: one machine, one run, n=15, and read
audiobook speech rather than spontaneous dictation. The direction of the result is
large and consistent; the exact percentages are not precise to the point given.

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

The gate that decides whether a recording contains speech at all, tested against 40
LibriSpeech clips as positives and 5 negatives — digital silence plus Gaussian noise at
0.1×, 0.25×, 0.5× and 0.75× the threshold:

| Metric | Result |
|---|---|
| Speech detected | 100 % (40/40) |
| Silence rejected | 100 % (5/5) |
| Balanced accuracy | 100 % |
| Median speech level vs threshold | 3.4× margin |

The 3.4× margin is why `yazses mic-level --set` matters: the default threshold works
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
get typed as text, which is annoying but harmless. A Tier-2 SLM router was designed
to catch those and is **not wired** — Tier 1 decides every utterance today, so the
number above is what you get.

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

This table tracks performance across different machines and engines, measured with the
community benchmark harness.

| CPU/GPU | Engine (Model) | WER | RTF | Peak RSS |
|---|---|---|---|---|
| 13th Gen Intel Core i7-1370P (CPU) | `faster-whisper` (`base.en`) | 0.0 % | 0.13x | 283.1 MB |

**This table is a smoke test, not an accuracy measurement.** The corpus that ships with
the repository is a *single* 11-second, 22-word clip, so the only WER values it can
produce at all are multiples of 1/22 — 0 %, 4.5 %, 9.1 %, and so on. It tells you the
pipeline decodes correctly on your machine; the RTF and peak-RSS columns are the ones
carrying real information. For an accuracy figure, use the 200-utterance, 40-speaker
LibriSpeech run under [Accuracy](#accuracy) instead.

> **Correction (2026-08-23).** This row previously read `4.2 % | 0.85x | 215.3 MB`, and
> two separate things were wrong with it.
>
> First, that WER cannot be produced by this harness on this corpus at all: with a
> 22-word reference every possible result is a multiple of 1/22, and 4.2 % is not one.
> The row had been typed by hand rather than pasted from the harness, which prints its
> percentage with no space before the `%`.
>
> Second, and worse, the harness itself was scoring wrongly. It compared texts after a
> bare lower-case fold, which counts punctuation as part of the word it is attached to.
> On this clip `base.en` returns the reference **exactly**, apart from two commas — and
> the lower-fold scored that flawless transcription at **9.09 %** while the standard
> Whisper `EnglishTextNormalizer` scores it **0.00 %**. So the community table was
> publishing recognition errors that were not recognition errors, and its numbers were
> not comparable with the paper harness, which had always normalised properly.
> `scripts/bench-stt.py` now uses the same normaliser, and says which one it used.
>
> Both are corrected here rather than quietly deleted: a benchmark page's whole value is
> that its numbers are real and its method repeatable, and that includes the times the
> method was wrong.

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

# one-time: fetch LibriSpeech test-clean (346 MB). The corpus is not redistributed
# here, so paper/data/ does not exist until you create it.
mkdir -p paper/data && cd paper/data
curl -fsSL -O https://www.openslr.org/resources/12/test-clean.tar.gz
tar -xzf test-clean.tar.gz
cd ../..

# run everything
uv run python paper/benchmark/run_all.py --wer-n 200 --lat-n 30 --vad-n 200

# or a single experiment
uv run python paper/benchmark/bench_wer.py 200
uv run python paper/benchmark/bench_latency.py 30
uv run python paper/benchmark/bench_streaming.py 15
```

Results land in `paper/results/*.json`. If your numbers differ materially from this
page, that is worth an [issue](https://github.com/MSKazemi/yazses/issues) — different
CPUs are expected to differ, but a large gap on the same class of hardware means
something is wrong and we would like to know.

## Diarization (Meeting Mode)

**Method:** 8 synthesised meetings, 23.3 minutes, 2–6 speakers each, generated by
`scripts/gen-meeting-corpus.py` — a language model writes the dialogue, Azure Speech
neural TTS renders each turn in a distinct voice, and a mixer lays the turns onto one
16 kHz mono timeline with ~18% of turns barging in on the previous one. Because the
mixer *places* every turn, the reference is exact rather than annotated, so the
primary figure is scored with **no forgiveness collar**; the NIST 250 ms collar is
given beside it only for comparison with published numbers. Scoring is frame-based
at 10 ms with an optimal one-to-one speaker mapping (md-eval semantics),
`paper/benchmark/bench_diarization.py`. Backend: sherpa-onnx, pyannote
segmentation-3.0 plus a 3D-Speaker ERes2Net embedder, defaults as shipped.

| Metric | Value |
|---|---|
| **DER (collar 0)** | **22.8%** |
| DER (250 ms collar) | 18.4% |
| Missed speech | 10.3% |
| False alarm | 0.4% |
| Speaker confusion | 12.1% |
| Mean speaker-count error | **+3.4** |
| Meetings with the right speaker count | **0 of 8** |

**Read this as a floor, not as the DER.** TTS voices are cleaner and more separable
than people in a room, so real meeting audio will score worse. The figure's job is
regression detection — "did this change make separation worse" — and it must never
be quoted as a field measurement or merged with an AMI/VoxConverse number.

**The result is not really the DER; it is the speaker count.** False alarm is 0.4%,
so speech is found accurately. What goes wrong is clustering: the count was
over-estimated in *every one* of the eight meetings — 4 clusters for 2 speakers, 12
for 5, 8 for 4 — and confusion (12.1%) is the largest single error term. On a
transcript that reads as one person appearing under several labels, which is more
damaging than the aggregate percentage suggests, and it happens here on **clean,
deliberately distinct voices** — the easiest case there is.

### The shipped clustering threshold looks mis-set

`[recimport] cluster_threshold` defaults to `0.5`. Sweeping it over the same corpus
(`bench_diarization.py <corpus> --sweep`):

| `cluster_threshold` | DER | Mean speaker-count error | Meetings with exact count |
|---|---|---|---|
| 0.4 | 28.4% | +6.25 | 0 / 8 |
| **0.5 — shipped default** | **22.8%** | **+3.38** | **0 / 8** |
| 0.6 | 20.2% | +2.00 | 0 / 8 |
| 0.7 | 16.0% | +0.62 | 6 / 8 |
| **0.8** | **14.7%** | **+0.12** | 6 / 8 |
| 0.9 | 15.8% | −0.25 | 7 / 8 |

The curve has an interior minimum near `0.8` rather than running monotonically to the
edge of the range, which is what makes this a real optimum rather than an artefact of
the corpus being easy. Moving the default there is a 35% relative DER reduction and
takes the speaker count from wrong in 8 of 8 meetings to roughly right.

**This has not been changed, and the number above is not sufficient reason to change
it.** The sweep is over synthetic speech, and a threshold tuned on clean, distinct
TTS voices is precisely the parameter most likely to be overfitted by them — real
speakers sit closer together in embedding space, which pushes the optimum back down.
What the sweep does establish is a direction: `0.5` is dominated on every metric by
several values above it, so it is very unlikely to be the right default. Confirming
where the optimum actually sits needs real meeting audio.


## What is not measured here

Being explicit about the gaps, because a benchmark that only reports its wins is
not a benchmark:

- **No real-world dictation WER.** Everything above uses read audiobook speech.
  Spontaneous speech into a laptop microphone in a normal room is harder, and we do
  not have a licensed corpus to quantify it.
- **No diarization accuracy on *real* meeting audio.** There is now a number — see
  [Diarization](#diarization-meeting-mode) below — but it comes from a synthetic
  corpus, so it is a floor rather than a field figure. AMI and VoxConverse remain
  unscored: the first is 100+ GB, and the second's audio is pulled from YouTube
  under terms that forbid redistribution, so neither can become a fixture here.
- **No macOS or Windows figures yet.** Every number above was measured on Linux
  x86_64. The harness itself is cross-platform as of the `Benchmarks` workflow
  (`.github/workflows/benchmark.yml`), which runs it on Linux x86_64, Linux arm64,
  macOS arm64, macOS x86_64 and Windows — but it is dispatched by hand and has not
  been run yet, so there is nothing to publish here. This bullet becomes a table,
  not a promise, once it has.
- **No arm64 figures.** The `.deb`, the snap and the docker image all ship for
  arm64 and not one published number comes from the architecture.
- **Single machine.** One CPU model, one run. There is no variance estimate across
  machines.

When those runs do land, latency and RTF get **one table per host and are never
merged**: word error rate is a property of the model and is comparable everywhere,
while latency is a property of the machine. Each result JSON carries a provenance
block naming the CPU, OS and library versions that produced it, so a number can
never be quoted without its conditions.

Contributions on any of these are welcome, and reporting results from your own
hardware is a genuinely useful first contribution.
