---
title: Choosing a Whisper model on a low-RAM machine
description: Measured memory footprint of each Whisper model in YazSes, what the accuracy costs, and how to run offline dictation on a machine with 2–4 GB of RAM.
---

# Choosing a model on a low-RAM machine

The model is loaded once and stays resident for as long as the daemon runs, so on a
small machine the question is not "how fast is it" but "does it fit alongside
everything else".

!!! info "Measured here"

    13th Gen Intel Core i7-1370P · Ubuntu 24.04 · Python 3.14 · faster-whisper,
    **int8 on CPU**. "Peak RSS" is the whole Python process at its high-water mark
    during a decode — interpreter, libraries and model together, which is what your
    system actually has to find.

## The numbers

| Model | On disk | **Peak RSS** | Decode, 11 s clip | WER¹ |
|---|---|---|---|---|
| `tiny.en` | 78 MB | **285 MB** | 0.58 s | 4.82 % |
| `base.en` **(default)** | 148 MB | **370 MB** | 0.79 s | 4.07 % |
| `small.en` | 486 MB | **712 MB** | 1.93 s | 2.59 % |

¹ LibriSpeech `test-clean`, 200 utterances — the method is on the
[benchmarks page](../benchmarks.md). Real dictation is harder than that benchmark;
treat WER as a comparison *between* models, not a promise.

**Resident memory is roughly twice the file on disk.** That surprises people who
size a machine from the download.

## What to pick

| You have | Use | Why |
|---|---|---|
| **≥ 8 GB** | `base.en` (default) | 370 MB is noise on that machine |
| **4 GB** | `base.en`, or `tiny.en` if it swaps | it fits, but check against your browser |
| **2 GB** | `tiny.en` | 285 MB is the smallest resident footprint available |
| **< 2 GB** | `tiny.en`, and expect trouble | nothing here is tuned for it |

```toml
[stt]
model = "tiny.en"
```

Then `yazses restart`. Confirm what is actually loaded:

```bash
yazses status     # shows the model, and p50/p95 decode latency once you have used it
```

## Is it swapping?

The failure mode on a small machine is not an error — it is dictation that used to
take a second and now takes fifteen, because the model is being paged back in
between utterances.

```bash
# While the daemon is running:
ps -o rss=,comm= -C python3 | sort -rn | head -3     # resident KB
free -m                                              # is `swap used` climbing?
```

If `swap used` grows while you dictate, drop a model size. No amount of tuning
recovers from swapping a model in and out.

## What does *not* reduce memory

- **`[stt] compute_type`** is already `int8`, which is the smallest option that
  ships. `float16`/`float32` make it *larger*, not smaller.
- **`[stt] cpu_threads`** changes CPU use, not memory — see
  [CPU and battery](cpu-and-battery.md). Measured: 363–373 MB across every thread
  setting, i.e. no effect.
- **Turning off features** helps only if they load their *own* model. The optional
  ones that do are LLM cleanup, gaze and Cocktail Filter; the rest are pure logic.

## The multilingual models

`tiny`/`base`/`small` (without `.en`) understand many languages and are roughly the
same size as their English-only counterparts, but are less accurate on English. Only
use one if you dictate a non-English language — see
[`[stt] language`](../configuration.md).

## What is not measured here

- **A machine that actually has 2 GB.** These footprints were measured on a large
  machine; the "you have" table above is arithmetic on those numbers, not a test on
  small hardware. If you run YazSes on a Raspberry Pi or an old netbook,
  [tell us what happened](https://github.com/MSKazemi/yazses/issues) — that report
  is worth more than this table.
- **`large-v3`.** It is not in the table because it is not a sensible choice on a
  low-RAM machine, which is what this page is about.
