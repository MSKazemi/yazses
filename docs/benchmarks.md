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

## Every engine, measured against every other

The table above is the three default Whisper checkpoints on the reference laptop. This
one is the whole pluggable-engine matrix, including the two engines the documentation
had been comparing on the vendors' word since they shipped. Measured on a 16-vCPU Intel
Xeon Platinum 8573C (Azure `Standard_D16s_v6`, Ubuntu 24.04, CTranslate2 4.8.1, int8 on
CPU, otherwise idle), the same 200-utterance speaker-stratified `test-clean` subset, the
same `EnglishTextNormalizer`, and every engine built through the shipping
`stt.factory.build_engine` rather than a bespoke call.

| Engine / model | WER | 95 % CI | Sub | Del | Ins | RTF | vs real time |
|---|---|---|---|---|---|---|---|
| `parakeet-tdt-0.6b-v2` | **2.06 %** | 1.54–2.68 | 73 | 12 | 11 | 0.050 | 19.8× |
| `small.en` | 2.66 % | 2.05–3.28 | 100 | 16 | 8 | 0.092 | 10.9× |
| `moonshine/base` | 3.17 % | 2.49–4.02 | 110 | 15 | 23 | **0.023** | **42.6×** |
| `large-v3` | 3.23 % | 1.95–5.00 | **62** | 8 | **89** | 0.451 | 2.2× |
| `medium.en` | 3.28 % | 2.09–5.01 | 86 | 27 | 40 | 0.246 | 4.1× |
| `base.en` **(default)** | 4.01 % | 3.21–4.87 | 141 | 16 | 30 | 0.042 | 24.1× |
| `moonshine/tiny` | 4.20 % | 3.42–5.06 | 152 | 16 | 28 | 0.016 | 62.6× |
| `tiny.en` | 5.18 % | 4.22–6.31 | 166 | 23 | 42 | 0.028 | 35.4× |

RTF is real-time factor — decode seconds per audio second, so lower is faster. It is a
property of this machine and may not be carried to another one; the WER column may.

**The two largest Whisper models lose, and the reason is insertions, not recognition.**
`large-v3` has the *fewest* substitutions of anything measured — 62, against `small.en`'s
100 — so as a recogniser it is exactly as good as its reputation. It also has 89
insertions against `small.en`'s 8. On dictation-length clips the large models add text
that was never spoken, and on a short utterance that is the dominant error. This is the
same failure mode as Whisper's hallucination on silence, and it is why a bigger model is
not automatically the better choice for hold-to-talk.

**Parakeet wins, and the confidence intervals overlap.** 2.06 % against `large-v3`'s
3.23 % is a point estimate on 200 utterances, and the intervals (1.54–2.68 against
1.95–5.00) share a lot of ground. Parakeet is the right way to bet on this evidence;
"Parakeet beats whisper-large-v3" is not something 200 utterances establish.

**Parakeet is about twice `small.en`'s speed, not four times.** Five places in this
project's own documentation said "roughly 4× whisper-small CPU speed", inherited from
the vendor. 0.092 / 0.050 = 1.84, and a second run on the same box gave 1.79. The
vendor's ~30× real time is ~20× here. Those five places now quote this table.

**Moonshine is the fastest thing here by a distance**, and `moonshine/base` reaches
`large-v3`'s accuracy at twenty times the speed — worth knowing before assuming the
accuracy/latency trade-off has to be paid in the usual direction.

### How much worse: the same models on `test-other`

This page has always said "your dictation WER will be worse than this" without measuring
anything that was worse — the benchmark harness only knew about `test-clean`. It now
takes `--split test-other`: the same corpus, the same readers' format, drawn from the
half LibriSpeech's authors set aside as harder. 200 utterances, 33 speakers, 23.4 minutes,
same machine, same method.

| Engine / model | `test-clean` | `test-other` | Multiplier |
|---|---|---|---|
| `parakeet-tdt-0.6b-v2` | 2.06 % | **2.88 %** | **1.4×** |
| `large-v3` | 3.23 % | 4.86 % | 1.5× |
| `small.en` | 2.66 % | 5.59 % | 2.1× |
| `medium.en` | 3.28 % | 5.51 % | 1.7× |
| `moonshine/base` | 3.17 % | 8.04 % | 2.5× |
| `base.en` **(default)** | 4.01 % | 9.46 % | 2.4× |
| `moonshine/tiny` | 4.20 % | 10.35 % | 2.5× |
| `tiny.en` | 5.18 % | 11.61 % | 2.2× |

**Take the right lesson from the multiplier.** `test-other` is still read speech from a
recording session; it is not you dictating into a laptop microphone with a fan running.
So this is not a prediction of your desk — it is a lower bound on how far a number from
this page can move when only the audio gets harder. On the default model that is 4 % to
9.5 %, which is the difference between "occasional fix" and "one word in ten".

**The ranking is not stable across the two splits.** On clean audio `small.en` beats
both `medium.en` and `large-v3`; on harder audio it falls behind both, and `large-v3`
becomes the best Whisper checkpoint measured. The reason is visible in the error
breakdown: `large-v3`'s substitutions barely move (87 on clean, 87 on other) while
`small.en`'s rise from 100 to 161. The big model's recognition advantage was always real
and was simply outweighed, on easy audio, by the words it invents. Make the audio harder
and the trade flips.

**Two models barely degrade at all** — Parakeet (1.4×) and `large-v3` (1.5×), the
non-Whisper engine and the largest Whisper checkpoint. Everything else lands between
1.7× and 2.5×, with `base.en` and both Moonshine models at the top of that range.
If you are choosing a model for conditions you cannot control, this column matters more
than the `test-clean` one.

### The same number, measured twice, is not the same number

Repeating the whole matrix on the same box, same code, same 200 utterances:

| Model | Measurements across repeated runs |
|---|---|
| `tiny.en` | 4.93 %, 4.95 %, 5.18 %, 5.25 % |
| `large-v3` | 3.23 %, 3.41 %, 3.98 % |
| `base.en`, `small.en`, `medium.en`, `parakeet`, both `moonshine` | identical every time |

So two of the eight are unstable by up to three quarters of a point, and the rest do not
move at all. That is not the machine. Decoding the same subset **twice inside one
process** — same loaded weights, same threads, same instruction set — still produced one
differing utterance in two hundred, and seeding CTranslate2's RNG changed nothing.

Decoding that one clip (`7176-88083-0001`, 16.6 s) forty times names the mechanism:

| `tiny.en`, 40 decodes of one clip | Distinct outputs |
|---|---|
| faster-whisper defaults | **34** |
| `temperature=0.0` (fallback disabled) | **1** — and it is the single word `"The"` |
| `condition_on_previous_text=False` | 34 |
| `beam_size=1` | 35 |

The greedy decode of this clip **fails**, emitting one word. faster-whisper's default
`temperature=[0.0, 0.2, … 1.0]` fallback notices — the output fails its compression-ratio
and log-probability checks — and re-decodes by *sampling* until something plausible comes
out. The fallback is what rescues the utterance; sampling is why the rescue is a
different sentence each time. Turning it off is not a fix: it trades a random correct-ish
sentence for a deterministic one-word truncation.

Run against `base.en` and `small.en`, the same clip gives **1 distinct output in 40**,
with the fallback on or off. The instability is not general — it is what happens when a
model is small enough that its first-choice decode fails the quality check, and on this
corpus that is `tiny.en` and `large-v3` and nothing else.

Two things follow. The second decimal place on the `tiny.en` and `large-v3` rows above is
noise, and the first is not entirely safe either. And it is a **product** behaviour, not
only a benchmark artefact: on `tiny.en`, dictating one long sentence twice can return two
different transcripts, or one word. YazSes' default is `base.en`, which on this evidence
does not do it.

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

### The one decode knob that is not the model

`[stt] beam_size` is the only setting that changes how the decoder searches rather than
what it searches with. `0` — the default — leaves faster-whisper's own default of 5.
This project's source described `1` as "measurably faster and measurably worse", which
had never been measured. It is now, on the same 200-utterance subsets and the same idle
16-vCPU Xeon as the tables above:

| Model | Split | `beam_size` | WER | RTF |
|---|---|---|---|---|
| `base.en` | `test-clean` | 1 | 4.39 % | 0.0310 |
| `base.en` | `test-clean` | 2 | **4.01 %** | 0.0322 |
| `base.en` | `test-clean` | 3 | 4.07 % | 0.0348 |
| `base.en` | `test-clean` | 5 *(default)* | **4.01 %** | 0.0361 |
| `base.en` | `test-clean` | 8 | **4.01 %** | 0.0377 |
| `base.en` | `test-other` | 1 | 10.56 % | 0.0376 |
| `base.en` | `test-other` | 2 | 9.49 % | 0.0388 |
| `base.en` | `test-other` | 5 *(default)* | **9.46 %** | 0.0417 |
| `small.en` | `test-clean` | 1 | **2.53 %** | 0.0663 |
| `small.en` | `test-clean` | 5 *(default)* | 2.66 % | 0.0765 |
| `small.en` | `test-other` | 1 | 6.18 % | 0.0823 |
| `small.en` | `test-other` | 5 *(default)* | **5.59 %** | 0.0919 |

**"Faster" is 11–16 %, not a category change.** Greedy decoding sounds like it should
be several times quicker. It is not: the beam is not where a Whisper decode spends its
time. On a five-second utterance the whole saving is about 20 ms.

**"Worse" depends on the model and the audio, and once reverses.** Greedy costs
`base.en` 0.38 points on clean audio and 1.07 on hard audio — the harder the audio, the
more the search is worth. On `small.en` and clean audio greedy is *better* (2.53 %
against 2.66 %) and faster, and on hard audio it is worse again. So the cost of greedy
is a property of the pairing, not of beam search.

**Everything beam 5 buys, beam 2 already has.** On `base.en` beams 2, 5 and 8 score
identically on clean audio, and beam 2 is within 0.03 points on hard audio, for 8–11 %
less decode. The default stays at 5 anyway: 20 ms on a burst is not perceptible, and 5
is the setting the rest of the world runs. What this table is for is the Adaptive
Latency Governor, which drops to greedy on a loaded machine — it can now say what that
costs instead of guessing.

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
LibriSpeech run under [Accuracy](#accuracy--word-error-rate) instead.

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

Scored on two corpora that answer two different questions. **Their numbers are not
comparable and must never be averaged.** Scoring is frame-based at 10 ms with an
optimal one-to-one speaker mapping (md-eval semantics),
`paper/benchmark/bench_diarization.py`; the backend is sherpa-onnx — pyannote
segmentation-3.0 plus a 3D-Speaker ERes2Net embedder — with the defaults as shipped.

The aggregate is the **mean across recordings**, not time-weighted across the corpus.
That is a deliberate choice (a 40-minute meeting should not drown out three short
ones) and it is a different number from the corpus-aggregated DER most papers quote,
so it is named here rather than left for a reader to assume.

### On real meetings: AMI — the number that matters

The **whole AMI test split**: 16 recordings, 543.7 minutes of real four-person meetings
in real rooms, headset mix, scored against the human reference RTTMs published by
`pyannote/AMI-diarization-setup` (`only_words`, test split). This is what Meeting Mode is
actually pointed at.

| | DER (collar 0) | mean speaker-count error | exact count |
|---|---|---|---|
| defaults **before v2.30** (`cluster_threshold = 0.5`) | **75.21%** | **+155.19** | 0 / 16 |
| defaults **now** (`[meeting] cluster_threshold = 1.2`) | **26.71%** | +2.06 | 2 / 16 |
| `max_speakers = 4` (count supplied) | 29.42% | +0.06 | 16 / 16 |

Per recording the old default ran from 53.7% to 92.0% DER, finding between **81 and 272**
speakers in rooms holding four people. The threshold change is
[ADR-v2-133](https://github.com/MSKazemi/yazses/blob/main/design/adr/adr-v2-133-diarization-clustering-default.md);
the rest of this section is the evidence behind it, kept because the old numbers were
published and deleting them would be the wrong kind of tidy.

Note the third row. **Supplying the exact speaker count is now worse than letting the
clustering estimate it** — 29.42% against 26.71% — which is the reverse of what the
four-meeting subset below showed at the old threshold, and is why the pre-run hint about
`--speakers` no longer claims to be a large win.

#### The four-meeting subset, at the old defaults

The first measurement, kept for continuity with the sweeps further down, which were all
run on these four (EN2002a, ES2004a, IS1009a, TS3003a — 90 minutes).

| Metric | Shipped defaults | `max_speakers = 4` |
|---|---|---|
| **DER (collar 0)** | **84.09%** | **28.55%** |
| DER (250 ms collar) | 78.32% | 22.21% |
| Missed speech | 10.88% | 10.70% |
| False alarm | 4.73% | 4.44% |
| Speaker confusion | **68.49%** | 13.41% |
| Mean speaker-count error | **+126.5** | **0.0** |

Per meeting, with the number of speakers the clustering found in each four-person room:

| Meeting | Shipped defaults | `max_speakers = 4` |
|---|---|---|
| EN2002a | 90.47% (257 speakers) | 35.42% (4 / 4) |
| ES2004a | 74.02% (81 speakers) | 38.82% (4 / 4) |
| IS1009a | 90.20% (86 speakers) | 21.89% (4 / 4) |
| TS3003a | 81.67% (98 speakers) | 18.08% (4 / 4) |

**This is a clustering failure, not a speech-detection failure.** Missed speech and
false alarm barely move between the two columns — the segmentation model finds the
speech either way. What collapses is who said it: 68.49% of scored time is attributed
to the wrong speaker at the defaults, because the clustering split four people into
between 81 and 257 clusters. A transcript in that state is not "somewhat inaccurate";
it is unreadable.

**At the old threshold, telling it the speaker count was the single largest improvement
available** — `--speakers 4` on `yazses transcribe`, or `[meeting] max_speakers` in
`config.toml`, took the DER from 84.09% to 28.55% and the speaker count from wrong in 4 of
4 meetings to exact in 4 of 4. **That is no longer true at the shipped defaults**: on the
full test split the count-supplied run scores 29.42% against auto's 26.71%. The flag is
still worth setting when you know the number and the recording is unusual — a crowded
call, or a meeting where the labels come out obviously wrong — but it is not a fix for a
broken default any more, because the default is not broken any more.

Note that on the shipped sherpa backend this is an **exact** cluster count, not an upper
bound — a cautious "at most 6" for a three-person conversation invents six speakers, which
is why nothing recommends guessing it.

### Where the threshold actually sits on real audio

`cluster_threshold` used to default to `0.5` on both features. Swept on IS1009a,
which that value scores at 90.20%:

| `cluster_threshold` | DER | Speakers found (true: 4) |
|---|---|---|
| **0.5 — the old default** | **90.20%** | 86 |
| 0.7 | 76.49% | 56 |
| 0.9 | 51.68% | 28 |
| 1.0 | 31.89% | 21 |
| 1.1 | 28.14% | 10 |
| **1.2** | **21.89%** | **4** |
| 1.3 | 45.45% | 1 |
| 1.5 | 45.45% | 1 |
| 2.0 | 45.45% | 1 |

Two things are worth reading off that table. The optimum is **more than twice** the old
default, and the window around it is narrow: `1.3` merges every speaker into
one cluster. And `1.2` reaches 21.89% — the same figure `max_speakers = 4` reaches on
this meeting — because both routes arrive at the same four-cluster solution.

Higher is *more permissive* here, which is backwards from most tuning intuitions.
sherpa-onnx L2-normalises the embeddings, measures cosine distance and uses
**complete** linkage, so the threshold is a dendrogram cut height that has to exceed
the **worst-case** same-speaker pair anywhere in the recording. That is why the useful
value grows with how long and how variable the recording is — and why the default
range of `--sweep` (which stops at `0.9`) reports a metric still improving at the edge
rather than "your range is too narrow".

### The embedding model matters less than the threshold

The shipped embedder is a 3D-Speaker ERes2Net trained on Mandarin (`zh-cn`). Six
embedders on IS1009a, DER with the speaker count in brackets:

| Embedder | 0.5 | 0.7 | 0.9 |
|---|---|---|---|
| ERes2Net zh-cn — **shipped** | 90.20% (86) | 76.49% (56) | 51.68% (28) |
| ERes2Net EN (VoxCeleb) | 52.89% (62) | 41.96% (46) | 32.87% (25) |
| CAM++ EN (VoxCeleb) | 74.16% (36) | 73.49% (20) | 72.27% (9) |
| CAM++ zh+en advanced | 74.88% (68) | 53.03% (43) | 30.86% (24) |
| WeSpeaker EN CAM++ | 81.47% (22) | 69.70% (8) | 53.11% (4) |
| NeMo EN TitaNet-small | 78.47% (67) | 34.20% (46) | 27.96% (29) |

An English-trained embedder is worth a lot at the shipped threshold — but every model
in the table is still far from usable at `0.5`, and the shipped model at `1.2` (21.89%)
beats every alternative at `0.9`. The threshold dominates; the embedder is second.
An earlier reading of this data blamed the Mandarin embedder first, and the sweeps
above are what corrected it.

**Both defaults have since been changed on the strength of these numbers, to two
different values.** `[meeting] cluster_threshold` is `1.2` and `[recimport]
cluster_threshold` is `1.0`, because the two features are handed different audio and a
cut height is a property of the recording rather than of the product. The reasoning, the
cross-domain gate that nearly stopped it, and what the decision explicitly does *not*
claim are in
[ADR-v2-133](https://github.com/MSKazemi/yazses/blob/main/design/adr/adr-v2-133-diarization-clustering-default.md).

### The cross-domain check: VoxConverse

A threshold tuned on meetings could easily be a threshold that only works on meetings, so
it was gated against a corpus that is not meetings before anything moved. 15 VoxConverse
dev recordings, 137.7 minutes of broadcast and YouTube audio, 1 to 20 speakers each:

| `cluster_threshold` | DER | speaker-count error | right count |
|---|---|---|---|
| 0.5 (old default) | 41.72% | +31.73 | 1 / 15 |
| 0.6 | 31.61% | +22.80 | 1 / 15 |
| 0.7 | 24.39% | +16.20 | 2 / 15 |
| **0.9** | **16.30%** | +5.20 | **4 / 15** |
| **1.0 — `[recimport]` default** | 17.34% | **+0.73** | 3 / 15 |
| 1.1 | 24.99% | −3.27 | 2 / 15 |
| 1.2 — `[meeting]` default | 42.13% | −6.40 | 1 / 15 |

Two things to read off it. **AMI's optimum is VoxConverse's worst**, and the count error
changes *sign*: at `1.2` a crowd-scene broadcast is under-counted by 6.4 speakers where a
meeting is within 0.75. And **`0.5` is optimal on none of the three corpora measured** —
synthetic peaks at 0.8–0.9, VoxConverse at 0.9, AMI at 1.2 — which is the whole case for
moving it, and does not depend on agreeing about where to move it to.

`[recimport]` takes `1.0` rather than the `0.9` that scores 1 pp better here, because
`yazses transcribe` is handed arbitrary files: `1.0` gets the speaker count almost exactly
right (+0.73 against +5.20), which the naming path downstream depends on, and it degrades
far more gracefully toward meeting audio (33.58% against 46.28%).

### How often the plausibility guard fires, and how often it is right

A warning is only worth having if it is rare and correct. `recimport/plausibility.py`
warns when a diarization result looks like fragments rather than people; it was measured
against the same corpora, at the **shipped** defaults, after it had already shipped.

| corpus / threshold | recordings | genuinely over-split | flat 20 s fires | of those, correct |
|---|---|---|---|---|
| VoxConverse @ `0.9` | 15 | 11 | 8 | 7 |
| VoxConverse @ `1.0` — `[recimport]` default | 15 | 5 | **7** | **4** |

**Seven firings in fifteen recordings, three of them wrong.** And wrong in the way that
matters: `aisvi` found 8 speakers where there were 8, `epdpg` 9 where there were 12,
`vmaiq` 14 where there were 17 — so the sentence the user was shown, *"a person's worth of
speech split apart rather than that many people"*, was false about the result it was
describing. A warning that fires on half a corpus and misdiagnoses three of those trains
people to dismiss it, and a dismissed guard costs attention and catches nothing.

The cause was a constant with a unit nobody had noticed: **20 seconds is a
meeting-length number.** AMI recordings run forty minutes, where a participant holding the
floor for under twenty seconds is barely present. VoxConverse clips run three to fifteen
minutes, where twenty seconds is an ordinary speaker's whole contribution.

The threshold now scales with the recording — `min(20 s, max(5 s, 2 % of total speech))` —
which takes both corpora to **zero false alarms** with the same true positives at `1.0`
and one fewer at `0.9`. Two bounds, each earning its place: the ceiling means every number
on this page still stands, because 2 % of half an hour is 36 s and AMI is evaluated at the
same 20 s it always was; the floor catches what a proportion cannot, since a three-minute
clip shattered into forty equal slivers gives every label exactly `total/40` and a
fraction-of-total threshold moves with the shattering instead of catching it.

### Scoring cross-check

Because every number above rests on the scorer, it was validated against two
independent implementations on IS1009a. `pyannote.metrics` 4.1 returns **exactly** the
same DER, miss, false-alarm and confusion figures. NIST `md-eval-22.pl` returns
89.34% against this harness's 90.20%, with the whole 0.86-point gap in false alarm —
the expected difference between a frame-based scorer and a segment-based one.

### The synthetic corpus — the regression fixture

8 synthesised meetings, 23.3 minutes, 2–6 speakers each, generated by
`scripts/gen-meeting-corpus.py` — a language model writes the dialogue, Azure Speech
neural TTS renders each turn in a distinct voice, and a mixer lays the turns onto one
16 kHz mono timeline with ~18% of turns barging in on the previous one. Because the
mixer *places* every turn, the reference is exact rather than annotated, so the
primary figure is scored with **no forgiveness collar**.

| Metric | Value |
|---|---|
| **DER (collar 0)** | **22.8%** |
| DER (250 ms collar) | 18.4% |
| Missed speech | 10.3% |
| False alarm | 0.4% |
| Speaker confusion | 12.1% |
| Mean speaker-count error | **+3.4** |
| Meetings with the right speaker count | **0 of 8** |

**Read this as a floor, not as the DER**, and never as a substitute for the AMI number
above. TTS voices are cleaner and more separable than people in a room: the same
defaults that score 22.8% here scored 84.09% on real meetings. Its job is regression
detection — "did this change make separation worse" — on a corpus that can be
regenerated on demand.

Swept the whole way to `1.6`, it has an interior minimum near `0.8`–`0.9` and gets
*worse* above it, where AMI is still improving at `1.0` and optimal at `1.2`:

| `cluster_threshold` | DER | speaker-count error | right count |
|---|---|---|---|
| 0.5 (the old default) | 22.77% | +3.38 | 0 / 8 |
| 0.7 | 15.98% | +0.62 | 6 / 8 |
| 0.8 | 14.7% | +0.12 | — |
| **0.9** | **15.79%** | −0.25 | **7 / 8** |
| 1.0 | 28.33% | −1.12 | 3 / 8 |
| 1.1 | 37.58% | −1.62 | 3 / 8 |
| 1.2 | 63.61% | −2.62 | 0 / 8 |
| 1.3 – 1.6 | 63.61% | −2.62 | 0 / 8 |

Flat from `1.2` upward because everything has already collapsed into one or two
clusters, so a higher cut has nothing left to merge.

**The two corpora disagreeing was predicted before the sweep was run, and the widened
range is what tested it.** The prediction on the record was: if this optimum stays near
`0.8`–`0.9` when the range is widened to `1.6`, the complete-linkage mechanism described
above explains both corpora; if it drifts up toward AMI's `1.2`, they disagree about
something else and the mechanism is wrong. It stayed. Complete linkage cuts a dendrogram
at a fixed height, so the cut has to clear the worst-case *same-speaker* pair in the
recording — and these meetings are three minutes long in deliberately distinct synthetic
voices, so that pair is close by, while forty minutes of a person in a real room is not.

Two things follow. **A default cannot be tuned here**, because the parameter this corpus
is most likely to overfit is the one being tuned — so it is now a regression fixture and
nothing more. And the useful cut height is a property of the *recording* rather than of
the dataset, which is why the fix that shipped is two constants rather than one, and why
even two is a compromise: the right answer is a per-recording estimate that nobody has.


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
merged**: latency is a property of the machine. Word error rate is *nearly* a
property of the model — near enough to rank checkpoints, not near enough to read a
tenth of a point between two hosts. CTranslate2 owns the int8 kernels and the order
their partial sums are reduced in, and that order depends on the instruction set it
dispatched to and on how many threads it split the matrix multiply across. On one
laptop, one byte-identical 200-utterance subset and one set of library versions,
`tiny.en` scored 4.78% with the thread count left to CTranslate2, 4.88% at one
thread and 4.95% at four; `base.en` and `small.en` did not move at all. The 0.17
point spread sits well inside the 95% interval the harness already reports for
`tiny.en` (4.03–5.83), so it changes no conclusion on this page — but it is why
`bench_wer.py` takes `--threads` and records the value in every result. Each result
JSON also carries a provenance block naming the CPU, OS, thread count, load average
and library versions that produced it, so a number can never be quoted without its
conditions.

Contributions on any of these are welcome, and reporting results from your own
hardware is a genuinely useful first contribution.
