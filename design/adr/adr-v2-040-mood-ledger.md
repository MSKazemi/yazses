# ADR-v2-040 — Mood Ledger (speech-sentiment journal)

**Status:** Accepted (2026-07-02) · Wave F
**Context links:** [[adr-v2-034-vocal-strain-guard]] (distinct: physiology), [[adr-v2-035-speaking-coach]], [[adr-012-self-improvement-loop]], [[adr-011]]

## Context

The Wave F research (#7) proposes tagging each dictation burst with an emotion label and
building a private, local mood-over-time view. Anchors: emotion2vec+ (ACL 2024, ~19 M, edge)
and SenseVoice SER (GGUF q8 ~254 MB, CPU). Distinct from Vocal-Strain Guard (physical vocal
health) — this is *affective self-tracking* for wellbeing/journaling.

## Decision

Add an opt-in **Mood Ledger**: `[sentiment] enabled=false`. The pure core aggregates emotion
labels over history: `aggregate(labels)` (label → count distribution), `dominant_mood(labels)`
(most frequent), and `mood_shift(earlier, later)` (valence comparison → `improved | declined |
stable | unknown`). The emotion2vec/SenseVoice SER model is lazy behind a `sentiment` extra.
Affective inference is sensitive, so labels live **only** in the encrypted corpus (ADR-012),
OFF by default.

## Consequences

- Longitudinal affective journaling, distinct from Vocal-Strain (physiology).
- Pure aggregation/trend → fully testable with no model.
- Privacy (ADR-011/012): affective labels only in the encrypted corpus; existing `corpus
  destroy` is the forget button; off by default.
- Caveat: SER is speaker/culture-variable → treated as a private journal signal, never shared
  or acted on automatically.
