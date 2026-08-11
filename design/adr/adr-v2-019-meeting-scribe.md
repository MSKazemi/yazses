# ADR-v2-019 — Ambient Meeting Scribe (streaming diarization)

**Status:** Accepted (2026-07-02) · Wave D
**Context links:** [[adr-v2-000-interaction-layer]], [[adr-018-voice-biometric-guard]] (reuse voiceprint), [[adr-012-self-improvement-loop]], [[adr-011]]

## Context

The Wave D research (#1) proposes an on-device "who said what" meeting transcript with a
per-speaker breakdown — distinct from single-user hold-to-talk dictation. Anchor: NVIDIA
Streaming Sortformer (arXiv 2507.18446) for low-latency online diarization. YazSes can tag
the enrolled user as "You" by reusing the encrypted voiceprint (ADR-012/018); everyone
else becomes "Speaker N". All on-device (ADR-011).

## Decision

Add an opt-in **meeting scribe**: `[scribe] enabled=false, backend (sortformer|none),
max_speakers`. The value-carrying logic is **pure** and testable —
`label_speakers` (map raw cluster ids to stable display labels, enrolled → "You"),
`merge_turns` (coalesce consecutive same-speaker turns), `format_transcript` (render
"Label: text"). The streaming diarization + STT backend is lazy behind a `scribe` extra;
when absent the feature is dormant. Not a keyboard-injection path — it produces a saved
transcript, so it never competes with dictation.

## Consequences

- Reuses the enrolled voiceprint for the "You" label — no new biometric storage.
- Pure labelling/formatting layer → fully unit-tested with no model.
- On-device only (ADR-011); the transcript is a user artifact, not telemetry.
- Caveat: CPU real-time diarization on ≥3 speakers is demanding → `max_speakers` cap and a
  lighter clustering fallback are backend concerns, gated behind the extra.
