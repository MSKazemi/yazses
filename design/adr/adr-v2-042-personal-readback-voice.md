# ADR-v2-042 — Personal Read-Back Voice

**Status:** Accepted (2026-07-02) · Wave F
**Context links:** [[adr-v2-035-speaking-coach]], Read-Back Loop (spec-read-back-loop), [[adr-v2-018-voice-biometric-guard]] (voiceprint), [[adr-011]]

## Context

The Wave F research (#6) proposes read-back proofreading in a clone of the user's *own* voice
from a short enrollment — hearing your own voice makes error-catching natural. Anchors: F5-TTS
(CC-BY-NC), OpenVoice V2 (permissive → default), XTTS-v2 (non-commercial). The existing
Read-Back Loop uses generic Kokoro voices; this personalizes and reuses `voiceprint/`
enrollment.

## Decision

Extend `[tts]` with `clone_voice=false` and `clone_backend="openvoice"`. The pure core
`clone_ready(reference_seconds, min_seconds)` decides whether enrollment has enough audio, and
`select_clone_backend(config)` returns the backend, **defaulting to the permissively-licensed
OpenVoice V2** (F5/XTTS are non-commercial and only used on explicit opt-in). The clone model
is lazy behind the existing `tts` extra path. The voice-clone reference embedding is biometric
→ stored ONLY in the encrypted corpus (same rule as Voice Guard), never plaintext. OFF by default.

## Consequences

- Personalizes read-back; reuses voiceprint enrollment + the tts path.
- Pure readiness/backend selection → fully testable with no model.
- Licensing honored: permissive OpenVoice V2 default; non-commercial backends explicit opt-in.
- Privacy (ADR-011/012): clone embedding biometric, encrypted-corpus only, never off-device.
- Caveat: voice cloning is sensitive → off by default, local-only, explicit enrollment.
