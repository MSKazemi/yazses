# ADR-v2-054 — Sign-Language Input (SLR)

**Status:** Accepted (2026-07-02) · Wave G
**Context links:** [[adr-v2-043-gesture-chords]] (discrete commands vs linguistic signing), [[adr-v2-012-accessibility-continuum]], Modality Router, [[adr-011]]

## Context

Wave G research (#10) — Deaf and hard-of-hearing signers dictate by signing to the webcam; ASL
is recognized on-device and injected as text. The most inclusive reading of the Accessibility
Continuum — extends "voice dictation" to a non-vocal population entirely. Anchor: Google
**SignGemma** (announced I/O 2025, Gemma/Gemini-Nano family, **on-device**, ASL→English, signing
video never leaves the device).

Distinct from Gesture Chords (discrete command shortcuts) — this is a new *linguistic* modality.
It slots into the Modality Router alongside voice and lip-reading.

## Decision

Add an opt-in **Sign-Language Input**: `[sign] enabled=false, pause_frames=8`. Two pure cores:
`hands_present(num_hands)` and `SignSegmenter` — a state machine that detects sign-burst
start/end from per-frame hand-motion magnitude (motion onset → start; sustained stillness or
hands leaving → end), deciding *when* a sign burst begins/ends. The SignGemma/Uni-Sign model +
MediaPipe Hands are lazy behind a `sign` extra (the biggest model lift of Wave G). OFF by default.

## Consequences

- Extends dictation to a non-vocal population; a new linguistic modality in the router.
- Pure presence + segment-boundary logic → fully testable with no camera; gates the heavy model.
- Privacy (ADR-011): SignGemma is on-device; frames stay local.
- Caveat: SLR is hard and model-heavy → boundary gate ships now, recognition deferred; off by
  default.
