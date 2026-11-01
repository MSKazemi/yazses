---
title: Choosing a Whisper model on a low-RAM machine
description: Measured memory footprint of each Whisper model in YazSes, what the accuracy costs, and how to run offline dictation on a machine with 2–4 GB of RAM.
---

# Choosing a model on a low-RAM machine

By default the model is loaded once and stays resident for as long as the daemon runs,
so on a small machine the question is not "how fast is it" but "does it fit alongside
everything else". If you dictate in bursts with long gaps between them, you can also
[release the model while you are not using it](#release-the-model-when-idle).

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

The peak figures above and the 2026-10-21 re-measurement on the
[models page](../models.md) (peak 272 / 344 / 618 MB on an AMD Ryzen 5 PRO 4650U) were
taken on different machines, and agree within about 20 %. An older ~874 MB figure for
`base.en` included an ~820 MB import baseline that the current code no longer has.

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

## Release the model when idle

!!! warning "Experimental, off by default"

    `[stt] idle_unload_s` has unit tests but has not yet been tried on real hardware.

```toml
[stt]
idle_unload_s = 600     # release the model after 10 minutes without a decode; 0 = never (default)
```

Then `yazses restart`. After that many seconds with no dictation, YazSes releases the
speech model. The next time you press the key it loads the model again:

- **Your audio is not lost.** Recording starts at the press, as always. The reload starts
  at the same moment and runs while you speak.
- **The first words after a long pause arrive late.** If the model is still loading when
  you let go, the tray shows *loading* until it is ready. Then the burst is transcribed and
  typed as usual. Loading `base.en` takes a few seconds; on a slow disk it takes longer.
- **Short values cost more than they save.** Below a few minutes, most presses pay for a
  reload. Start at 300–600 seconds.

The daemon only releases the model when it is idle or paused. A dictation, a meeting or a
file transcription in progress is never cut short.

**To see which state you are in,** run `yazses status`. With `idle_unload_s` set it prints
one more line under the model:

```text
  memory:   speech model loaded, idle 45 s of 600 s
  memory:   speech model unloaded after 642 s idle, 3 min ago — reloads on the next press
  memory:   speech model reloading — the next words wait for it
```

The tray tooltip (and the Linux tray menu) shows the same phrase as `Speech model: …`.
`yazses status --json` carries it as `stt_residency`, with `idle_unload_s`, `loaded`,
`loading`, `idle_s` (seconds since the last dictation, `null` while unloaded),
`unloaded_after_s` (how long the model had really been idle when it was released) and
`unloaded_for_s` (how long ago that was); the last two are `null` while the model is
loaded. The release can come later than `idle_unload_s`: YazSes checks every quarter of
it (and at least every 30 s), and it waits while you are dictating. So the unloaded line
shows the measured time, not the setting. At the default of `0` the whole field is `null`
and no line is printed. On macOS the line appears near the top of the menu-bar menu,
under the engine line (not yet tested on a real Mac).

### The latency governor's second model

If you turn on the latency governor (`[latency]`), it can load a second, smaller speech model
beside the main one. Left alone, that second model stays in memory. To release it when it has
not been used for a while, set this under `[residency]`:

```toml
[residency]
latency_keep_alive_s = 600     # release the governor's extra model after 10 minutes unused; 0 = never (default)
```

Then `yazses restart`. The default of `0` keeps today's behaviour. The key only matters when
`[latency]` is on. It does not touch the main speech model, which `[stt] idle_unload_s` still
controls. When the governor needs the extra model again, it loads it in the background, the same
way as above. `yazses status` shows one line for it, and `yazses status --json` carries it as
`latency_residency` (`null` at `0`).

**How much memory comes back is not measured yet.** CTranslate2, the library that runs
Whisper, may keep part of its memory after the model is released, so the drop you see in
`ps` can be smaller than the figures in the table above. If you try it, please
[report what `ps` shows](https://github.com/MSKazemi/yazses/issues) before and after an
unload. That measurement decides whether a future version runs the model in a separate
process instead.

## What does *not* reduce memory

- **`[stt] compute_type`** is already `int8`, which is the smallest option that
  ships. `float16`/`float32` make it *larger*, not smaller.
- **`[stt] cpu_threads`** changes CPU use, not memory — see
  [CPU and battery](cpu-and-battery.md). Measured: 363–373 MB across every thread
  setting, i.e. no effect.
- **Turning off features** helps only if they load their *own* model. The ones that
  do include the Adaptive Latency Governor (`latency`: a second Whisper model, about
  116 MB of RAM for `tiny.en`, once load is high — off by default, but configs written
  by first run before it was moved out of the recommended set have it on), LLM cleanup, gaze and the camera features, Cocktail Filter and voiceprints,
  speaker labels and Meeting Mode, and the Parakeet and Moonshine engines.
  `yazses features disable latency` is the one worth knowing on a small machine.

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
