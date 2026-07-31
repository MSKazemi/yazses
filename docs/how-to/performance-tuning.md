---
title: Tune for speed and accuracy
description: Choose the STT model, set the VAD threshold, and manage CPU load for the best speed/accuracy trade-off.
---

# Tune for speed and accuracy

YazSes runs entirely on your CPU with no cloud. The main trade-off is **model
size vs. latency**: bigger models are more accurate but take longer to decode.
This guide covers the knobs that matter — the STT model, the microphone gate, and
CPU-load handling.

## Choose the STT model

The transcription model is set in `config.toml` under `[stt]`:

```toml
[stt]
model = "base.en"       # default — good accuracy/latency balance
device = "cpu"
compute_type = "int8"   # 8-bit quantization keeps CPU decode fast
```

| Model | Speed | Accuracy | Use it when |
|---|---|---|---|
| `tiny.en` | fastest | lowest — frequent word errors | a very slow CPU, or short casual dictation |
| `base.en` | fast | good (the default) | most machines and everyday dictation |
| `small.en` | slower | best of the CPU-friendly set | you have CPU headroom and want fewer errors |

Guidance:

- Start on `base.en`. Only drop to `tiny.en` if decode latency is genuinely
  painful — it produces noticeably more word errors.
- Move up to `small.en` when accuracy matters more than the extra decode time.
- The `.en` (English-only) variants are faster and more accurate for English than
  the multilingual models of the same size; use a multilingual model only if you
  dictate in other languages.
- `compute_type = "int8"` is the fast default. `int8_float16` or `float16` can be
  slightly more accurate on capable hardware; `float32` is slowest.
- `device = "cpu"` is the tested path. YazSes is designed for CPU int8; GPU is not
  the supported default.

**Downloading a model:** faster-whisper fetches the model automatically the first
time the daemon starts with it configured, caching it in the Hugging Face cache.
Check whether the configured model is present with:

```bash
yazses doctor
```

which reports the STT model as cached, local, or not yet downloaded. Restart the
daemon after changing the model:

```bash
yazses restart
```

## Set the microphone gate (VAD threshold)

If dictation logs `Silent audio -- discarding`, your speech is falling below the
voice-activity threshold and being dropped. If spurious transcripts appear when
you are silent, room noise is above it. Calibrate the threshold to your voice and
room:

```bash
yazses mic-level              # measure and recommend a threshold
yazses mic-level --set        # measure and write it to config.toml
yazses mic-level -s 6         # record for 6 seconds instead of 4
```

Speak in a normal voice for the whole countdown. `--set` writes the recommended
value to `[accessibility] vad_threshold` (default `0.01`). Lower it for quiet
speech; raise it if background noise triggers false transcripts.

`yazses doctor --mic` records a short ambient clip and warns when the room level
already meets or exceeds your threshold (which would cause spurious triggers).

## Manage CPU load

Two features help when the CPU is busy — both are **off by default**:

- **Adaptive Latency Governor (`latency`)** — keeps dictation responsive when your
  CPU is loaded and lets it run faster when the machine is idle, by adapting decode
  behaviour to current load (`[latency] high_load = 85.0`, `low_load = 40.0`):

  ```bash
  yazses features enable latency
  yazses restart
  ```

- **Ghost Ahead (`ghost-ahead`)** — pre-warms the decoder so the *first* word comes
  out slightly faster (it eagerly decodes the buffer when it detects you've
  stopped; the authoritative transcript still happens on hold-release). Config
  lives under `[endpoint]` (`prewarm = true`):

  ```bash
  yazses features enable ghost-ahead
  yazses restart
  ```

## Let the learning loop tune for you

If you opt into the local, encrypted learning corpus (`[learning] enabled`), the
`yazses tune` command analyses your dictation history and proposes concrete config
diffs — vocabulary additions, a better VAD threshold, even a model change — that
you approve before they are written. Everything stays on your machine.

```bash
yazses tune            # propose changes
yazses tune --apply    # write the approved changes
```

## See also

- [Configuration reference — `[stt]`, `[accessibility]`, `[endpoint]`, `[latency]`](../configuration.md)
- [Feature reference](../features.md)
- [Add words to your personal dictionary](personal-vocabulary.md) — the other half of accuracy.
