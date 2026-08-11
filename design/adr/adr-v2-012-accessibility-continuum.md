# ADR-v2-012 — Accessibility Continuum

**Status:** Accepted (2026-07-02) · Wave C (experimental)
**Context links:** [[adr-v2-000-interaction-layer]], [[adr-v2-009-personal-adapter]] (atypical-speech personalization), [[adr-015-dysfluency-friendly]] (existing), [[adr-011]]

## Context

The accessibility research (internal) documents a
continuum of speech abilities poorly served by mainstream dictation: quiet/whispered
speech (fatigue, shared spaces), atypical/dysarthric speech, and users who need semantic
rather than literal capture. YazSes already ships Dysfluency-Friendly Mode (ADR-015) and
the Personal Adapter (ADR-v2-009); the gap is a coherent, opt-in *continuum* rather than
scattered flags.

## Decision

Group three opt-in accessibility capabilities under one continuum:
- **Low-Effort / Whisper Mode** — a quiet-speech STT profile (lower VAD threshold,
  whisper-tuned decode) so whispered dictation is captured without shouting.
- **Semantic Capture** — an opt-in "capture the meaning, not the exact words" pass (reuses
  the LLM-cleanup path, ADR-013) for users whose speech is effortful.
- **Adaptive pacing** — endpoint/hold timings that widen for slower speakers.

Each is off by default and composes with the Personal Adapter. **EXPERIMENTAL** where it
depends on the LLM path; `--force` to enable those. No new base deps; honours ADR-011.

## Consequences

- Turns scattered accessibility flags into a discoverable, documented set.
- Reuses existing VAD, LLM-cleanup, and personalization machinery — little new surface.
- Whisper Mode is pure config (VAD/threshold); Semantic Capture inherits the LLM extra.
