# ADR-v2-029 — Semantic Auto-Stop (hands-free tap-and-speak)

**Status:** Accepted (2026-07-02) · Wave E
**Context links:** [[adr-v2-012-accessibility-continuum]], [[adr-v2-000-interaction-layer]], [[adr-011]]

## Context

Every YazSes activation path assumes the hotkey defines the utterance boundary (hold to
talk). The Wave E research (#4) proposes an alternative for users who cannot hold a key: tap
to start, and the daemon auto-stops when you've *finished the sentence*. Anchor: Smart Turn v2
(Pipecat, HF open weights, wav2vec2, ~60MB/~400ms/14 langs) — semantic end-of-turn from
prosody, not transcript. This is a new activation axis (motor impairment) untouched by the 24
prior features and distinct from the Ghost-Ahead `[endpoint]` pre-warm (which anticipates a
manual release, never ends recording).

## Decision

Add an opt-in **auto-stop**: `[autostop] enabled=false, mode (silence|semantic),
silence_timeout_ms, max_duration_ms`. The pure core `should_stop(silence_ms, elapsed_ms,
config)` ends a hands-free turn when trailing silence exceeds `silence_timeout_ms` **or** the
turn hits `max_duration_ms` (a hard safety cap). This ships now with zero ML and already makes
tap-and-speak usable; the Smart Turn v2 ONNX model (true semantic end-of-utterance) is opt-in
behind a `turn` extra and refines the silence decision when present. OFF by default.

## Consequences

- New activation modality for users who can't hold a key; complements Wake-Word (#8).
- Pure timeout/cap decision → fully testable; the semantic model stays deferred.
- On-device only (ADR-011); audio never leaves RAM (same as existing VAD).
- Caveat: a too-short silence timeout clips slow speakers → conservative default + hard
  max-duration cap; off by default.
