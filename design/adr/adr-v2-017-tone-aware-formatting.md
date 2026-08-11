# ADR-v2-017 — Emotion / Tone-Aware Formatting

**Status:** Accepted (2026-07-02) · Wave D
**Context links:** [[adr-v2-000-interaction-layer]], [[adr-v2-002-prosody-autoformat]] (pause→sentence), [[adr-011]]

## Context

Prosody→sentence punctuation (ADR-v2-002) formats from *timing* only. The Wave D research
(#6) proposes affect-driven formatting: detect paralinguistic tone (excitement, question
intonation, emphasis) and reflect it — auto `!`, emphasis on stressed words — using
emotion2vec / SER front-ends (arXiv 2511.08723). Commercial dictation formats words but
never tone.

## Decision

Add an opt-in **tone-aware formatting** pass: `[affect] enabled`, `mode`
(`conservative` default = emphasis + `!` only | `expressive`), `min_confidence`. The
formatting itself is a **pure** function `(text, affect_label, confidence) → text`
(fully testable); the SER model is lazy behind an `[affect]` extra and, when absent,
yields a neutral label so the pass is a no-op. Composes after Prosody Ink on the dictation
path. OFF by default.

## Consequences

- The value-carrying logic (label→formatting) is pure and testable with no model.
- Conservative default (emphasis + `!`) avoids mis-formatting neutral speech.
- Caveat: SER is speaker/culture-variable → high `min_confidence` and conservative mode by
  default; expressive mode is explicit opt-in. On-device only (ADR-011).
