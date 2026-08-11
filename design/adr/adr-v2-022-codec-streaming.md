# ADR-v2-022 — Neural-Codec Ultra-Low-Latency Streaming STT

**Status:** Accepted (2026-07-02) · Wave D (seam now, engine deferred)
**Context links:** [[adr-v2-000-interaction-layer]], [[adr-011]], streaming.py (existing LocalAgreement path)

## Context

The Wave D research (#7) points to streaming-native STT with a neural audio codec for
~80 ms latency — Kyutai STT + the Mimi codec (Jun 2025), on-device via MLX. YazSes already
has a background LocalAgreement streaming path (`stt/streaming.py`) over faster-whisper;
the codec engine is a different, heavier backend (English/French-centric today). The
selection of *which* engine decodes a burst is a small pure decision; the engine itself is
compute-heavy and out of scope to run in-loop.

## Decision

Add an opt-in **codec engine seam**: `[codec] enabled=false, backend (kyutai|none),
max_delay_ms`. A pure `select_engine(config) → "codec" | "whisper"` returns the codec
engine only when it's enabled with a real backend, otherwise keeps the default
faster-whisper (so an unconfigured or heavy-backend setup never changes decoding). The
Kyutai/Mimi engine is lazy behind a `codec` extra and dormant unless installed. faster-
whisper stays the default multilingual engine.

## Consequences

- Pure engine-selection layer → fully testable; the codec engine stays opt-in/deferred.
- Default path unchanged (faster-whisper) — English/French-centric codec never forced on.
- On-device only (ADR-011).
- Caveat: the codec backend's language coverage is narrower than Whisper's → keep it opt-in
  and per-user, never a global default.
