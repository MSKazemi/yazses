# ADR-v2-015 — Real-time Noise-Suppression Front-End

**Status:** Accepted (2026-07-02) · Wave D
**Context links:** [[adr-v2-000-interaction-layer]], [[adr-v2-012-accessibility-continuum]] (quiet speech), [[adr-011]]

## Context

YazSes has only an energy-VAD gate and no learned speech enhancement, so noisy/echoey
rooms and quiet speech trip the "Silent audio — discarding" failure mode. The Wave D
research (#3) points to DeepFilterNet3 (112K–3.58M params, real-time low-latency full-band
enhancement, existing live plugin) as a drop-in denoise/dereverb stage.

## Decision

Add an opt-in **denoise front-end** between mic capture and STT: `[denoise] enabled`,
`backend` (`deepfilternet` | `none`), `strength` (graded). The backend is a pure
audio-in → audio-out transform, lazy-imported behind a `[denoise]` extra; when off or
absent it is a passthrough (identity), so the pipeline is unchanged. Pairs with
Whisper/Low-Effort Mode (ADR-v2-012) to make quiet speech reliably clear the VAD gate.

## Consequences

- Directly attacks the recurring low-mic-level / discard failure mode.
- Passthrough-when-off guarantees zero impact on the default path.
- Caveat: over-aggressive suppression clips soft consonants → graded strength + advise
  re-running `yazses mic-level` after enabling. On-device only (ADR-011).
