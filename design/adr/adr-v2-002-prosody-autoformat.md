# ADR-v2-002 — Prosody Auto-Formatting (pauses → punctuation, stress → emphasis)

**Status:** Accepted (2026-07-02) · Wave A
**Context links:** [[adr-v2-000-interaction-layer]], existing Prosody Ink work (`postprocess/`, `[prosody]` config)

## Context

Every dictation path collapses the prosodic layer (pitch/pause/energy) to flat text, so
users must *say* "new paragraph" / "bold" (voice punctuation, v1.4.0). The voice-HCI
research (internal) shows prosody is recoverable
on-device and is "the discarded signal." YazSes already has partial **Prosody Ink** wiring;
this ADR finishes it as a coherent auto-formatting feature.

## Decision

Infer formatting from prosody, opt-in and conservative:
1. **Pause → punctuation/paragraph** (high confidence, cheap): use Whisper word timestamps —
   long inter-word gaps insert sentence punctuation; very long gaps or breath insert a
   paragraph break. Threshold-driven, tunable.
2. **Stress/pitch → emphasis** (lower confidence): optional `parselmouth`-based pitch/energy
   analysis marks emphasized spans (e.g. markdown `**bold**`) — behind a separate sub-flag
   and the `prosody` extra, so the DSP dependency stays optional.

Config: extend `[prosody]` — `autoformat=false`, `pause_sentence_ms`, `pause_paragraph_ms`,
`emphasis=false`. Applied on the dictation path after `clean_text`, before injection; must
compose with existing voice-punctuation and continuation spacing.

## Consequences

- **+** Clean prose from stream-of-consciousness speech; less spoken markup.
- **+** Pause→punctuation reuses data already in hand (timestamps) — nearly free.
- **−** Over-formatting is annoying → ship conservative defaults, opt-in, easy to disable.
- **−** Pitch→emphasis needs a DSP lib and is error-prone → separate flag, optional extra,
  default off; validate on real dictation before recommending.
