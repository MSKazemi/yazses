# ADR-v2-073 — Adaptive Latency Governor

**Status:** Accepted (2026-07-02) · Wave I
**Context links:** [[adr-v2-025-ghost-ahead-prewarm]] (pre-warm only), [[adr-v2-032-semantic-auto-stop]], [[adr-011]]

## Context

Wave I research (#3) — keep dictation responsive when the CPU is busy and losslessly faster when
it isn't. Sample machine load and pick a decode policy (model size, beam width); on capable
machines use a distil draft model for **speculative decoding** — mathematically identical output
at ~2×. Anchors: HF "Speculative Decoding for 2× Faster Whisper"; `distil-whisper/distil-large-
v3.5`; Distil-Whisper (arXiv 2311.00430) shares the encoder → cheap draft. Distinct from Ghost-
Ahead (pre-warm only; doesn't govern the decode).

## Decision

Add an opt-in **Adaptive Latency Governor**: `[latency] enabled=false, high_load=85,
low_load=40`. The pure core `pick_policy(cpu_percent, config)` returns a
`DecodePolicy(model, beam_size, speculative)`: at/above `high_load` → the light model, beam 1, no
speculation; at/below `low_load` with a draft model configured → base model, beam 5, speculative;
otherwise the balanced middle. Dependency-free (a plain function over a load sample). The `psutil`
metric read, the draft model, and the speculative-decode loop are deferred behind a `latency`
extra. OFF by default.

## Consequences

- Compute adapts to system load; the pure policy is trivially testable, the draft/spec-decode is
  the deferred tier.
- Distinct from Ghost-Ahead (pre-warm vs govern).
- Privacy (ADR-011): only local CPU telemetry; nothing leaves the machine.
- Caveat: speculative decoding needs a compatible draft model → gated on `draft_model` being set;
  off by default.

## Amendment (2026-08-24) — both beam widths were chosen by argument; they are now measured

The decision above names three constants: the light model, **beam 1** under load, and **beam 5**
on the two base paths. The model was reasoned about; the two beam widths were not measured at all,
and measuring them changed both.

**The base paths must not name a width.** `beam_size=5` there is wrong twice over. It is the
user's `[stt] beam_size` — a documented key — and a governor that silently replaces it is worse
than one that does nothing. And `EnginePool` is keyed on `(model, beam_size)` and is handed the
daemon's already-loaded engine under `(stt.model, stt.beam_size)`, which for the shipped config is
`(model, 0)`, meaning "pass nothing and let the engine choose". A base policy answering `(model, 5)`
missed that key on **every normal-load burst**, so the pool began a background load of a second
copy of the model already in memory — the exact outcome `pool.py`'s own docstring says its design
prevents. Nothing failed and nothing logged; the process simply held two engines. The base paths
now return `config.base_beam`, which the daemon fills from `[stt] beam_size`.

**The light path is beam 2, not beam 1.** The `[stt] beam_size` sweep in `docs/benchmarks.md`
could not settle this: it scores `base.en`, and the light policy runs `tiny.en`, so it measures a
combination the product never executes. Scored directly on `tiny.en`, 200 LibriSpeech utterances
per split (`paper/results/beam-governor-test-{clean,other}.json`):

| Split | beam 1 | beam 2 | beam 5 |
|---|---|---|---|
| test-clean | 5.53 % / RTF 0.0236 | 5.12 % / 0.0241 | 4.95 % / 0.0271 |
| test-other | 12.42 % / 0.0283 | 12.04 % / 0.0295 | 11.82 % / 0.0341 |

The two grids disagree, and that is the finding rather than a nuisance: on `base.en` beam 1 loses
to beam 2 significantly (p = 0.0026 hard, p = 0.024 clean); on `tiny.en` it does not (p = 0.41,
p = 0.099). The earlier result could not be carried across. What decides it is the ceiling —
paired on the same utterances, beam 2 is **indistinguishable from beam 5** on both splits (p = 0.27,
p = 0.62) while beam 1 **loses to beam 5 on clean audio** by 0.58 points (95 % CI [+0.09, +1.14],
p = 0.023). Beam 2 reaches the best accuracy the three widths show; beam 1 demonstrably does not.

It costs 2.1 % more decode on clean and 4.2 % on hard. The beam was never where this policy's
saving came from: `base.en` at beam 5 decodes the hard split at RTF 0.0426, so `tiny.en` at beam 2
is still 31 % less decode time. Widening 1 → 2 hands back a twelfth of that saving on hard audio
and a twenty-seventh on clean, to remove the one accuracy loss the grid actually measured.

The constant lives in `governor.LIGHT_BEAM` with the numbers beside it, and the tests assert
through the symbol rather than the literal — its value is a measurement and has already moved once.
