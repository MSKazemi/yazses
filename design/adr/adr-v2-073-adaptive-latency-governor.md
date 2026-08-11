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
