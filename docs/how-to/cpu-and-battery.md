---
title: Reducing CPU use and battery drain on a laptop
description: Measured CPU cost of offline Whisper dictation, and the settings that actually reduce it — model choice, cpu_threads, and the features worth turning off on battery.
---

# Reducing CPU use and battery drain

Dictation feels instant, and that hides the cost. A decode that takes **one second**
of your time can spend **five seconds of CPU**, because the work is spread across
cores. On mains power that is the right trade. On battery it is the thing draining
it.

!!! info "The machine these numbers came from"

    13th Gen Intel Core i7-1370P · 20 logical CPUs · 30 GB RAM · Ubuntu 24.04 ·
    Python 3.14 · faster-whisper, **int8 on CPU, no GPU**. Input is an 11-second
    clip. Your absolute numbers will differ; the *ratios* are the point.

## What it actually costs

Measured with `time.process_time()` around the decode itself — this is CPU seconds,
not wall-clock:

| Model | Wall time | **CPU time** | Peak RSS |
|---|---|---|---|
| `tiny.en` | 0.58 s | **4.0 s** | 285 MB |
| `base.en` (default) | 0.79 s | **4.9 s** | 370 MB |
| `small.en` | 1.93 s | **9.5 s** | 712 MB |

**Model choice is the biggest lever.** Moving from `small.en` to `base.en` roughly
halves the CPU cost of every utterance. See
[choosing a model](low-ram-models.md) for what that costs in accuracy.

```toml
[stt]
model = "base.en"   # or tiny.en on a small battery
```

## Capping the cores: `[stt] cpu_threads`

By default the decoder uses whatever ctranslate2 chooses, which is effectively all
of them. `[stt] cpu_threads` caps it:

```toml
[stt]
cpu_threads = 2   # 0 (default) leaves it to the library
```

Measured on `base.en`, three runs per setting, same 11-second clip:

| `cpu_threads` | Mean wall time | Mean CPU time |
|---|---|---|
| `0` (default) | 0.98 s | 5.49 s |
| `4` | 0.98 s | 5.45 s |
| `2` | 1.32 s | 4.55 s |
| `1` | 2.05 s | 4.08 s |

**Read this table honestly.** Capping at 4 on a 20-core machine changed nothing
measurable — the library was not using 20 cores' worth in the first place, so the
"limit the threads" advice you will find for other Whisper tools does not
automatically apply here. The real trade starts below that: `2` buys about **17 %
less CPU for about 35 % more latency**, and `1` about **26 % less for roughly double
the latency**.

Whether that is worth it is a judgement about your own tolerance for waiting. It is
a smaller lever than the model, and this page would be selling you something if it
pretended otherwise.

## Things that cost nothing when idle

YazSes is event-driven: between bursts it holds the model in memory and does no
work. There is no background transcription and no polling of your microphone. The
idle cost is the resident model, which is the "Peak RSS" column above.

Three components do poll, all switchable:

| Setting | What it polls | Idle rate | Turn it off with |
|---|---|---|---|
| `[audio] device_poll_interval_s` (default `3.0`) | the OS default input device, **only while idle** | 0.33 Hz | set to `0` |
| `[tray] enabled` (default `true`) | the daemon's status, for the icon colour | 1 Hz | `yazses features disable tray` |
| `[overlay] enabled` (default `true`) | the daemon's status, for the voice-activity ring | 4 Hz | `yazses features disable overlay` |

Both status pollers speed up *while you are recording* — the tray to about 6.7 Hz
and the overlay to 20 Hz — so the colour and the ring track a short hold. That part
is bounded by how long you hold the key; the idle rates above are not.

Which is why what the status call *does* matters more than how often it is asked.
It is a read of fields the daemon already has in memory — with one exception, now
fixed: it also looked up the installed package version, and that walks `sys.path`
for a `.dist-info` on every call (2.1 ms measured). Both status pollers are on by
default, so a stock idle install spent roughly 40 s of CPU an hour re-reading a
string that cannot change while the process lives. It is now looked up once per
process, which is all it can ever change on.

## Features worth turning off on battery

Each of these adds work per utterance. All are off by default unless noted —
check with `yazses features`:

- **Streaming** (`[streaming] enabled`) decodes overlapping windows *during* the
  hold, so it does substantially more decoding than one pass at the end. It buys
  perceived latency **only on `tiny.en`** — on `base.en` the rolling decode cannot
  keep up with the audio, so in most utterances no live text appears before you
  release the key and the final text still arrives 56 % *later* than with streaming
  off ([measured](../benchmarks.md#speech-end--text-what-you-actually-wait-for)).
  On battery it is the first thing to turn off; on `base.en` or larger it is worth
  turning off regardless.
- **LLM cleanup** (`[filters.disfluency] llm_enabled`) runs a second model over
  every dictation.
- **Gaze** (`[gaze] enabled`) runs a camera and a face-landmark model during each
  hold.
- **Cocktail Filter** (`[cocktail] enabled`) embeds every 0.5 s window.

```bash
yazses features            # what is on, and its recommendation tier
yazses features disable streaming
yazses restart
```

## Measuring it on your own machine

Do not take this page's numbers for your hardware:

```bash
yazses status     # p50/p95 decode latency per model, from your own dictation
```

That is wall-clock, which is what you feel. For CPU seconds, the script that
produced the tables above is a dozen lines around `time.process_time()` — see
[benchmarks](../benchmarks.md) for the method.

## What is not measured here

- **Actual battery drain in watt-hours.** CPU seconds are a proxy. Turning them
  into battery life depends on your CPU's power curve, and nothing on this page
  measured a battery.
- **GPU.** `[stt] device = "cuda"` exists and is untested for power.
- **Anything but Linux.** The numbers above are one Linux laptop.
