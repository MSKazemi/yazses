# ADR-v2-035 — Speaking Coach (private self-analytics)

**Status:** Accepted (2026-07-02) · Wave F
**Context links:** [[adr-v2-034-vocal-strain-guard]] (distinct: physical vs style), [[adr-012-self-improvement-loop]] (encrypted corpus), [[adr-011]]

## Context

The Wave F research (#2) proposes an on-device dashboard of *communication style*: filler-word
rate (um/uh/like), words-per-minute, pause ratio, and vocabulary diversity, trended over time.
Products like Yoodli/Poised do this in the **cloud**; YazSes can own the fully-local niche.
This is distinct from Vocal-Strain Guard (ADR-v2-034, physical jitter/shimmer/HNR) and
Confidence Ink (STT confidence) — it analyses *how you speak*, not the voice signal or the
model's certainty.

## Decision

Add an opt-in **Speaking Coach**: `[coach] enabled=false`. The value-carrying logic is a
**pure** analytics core over transcript text (+ optional duration): `filler_rate`,
`words_per_minute`, `type_token_ratio`, and an `analyze(text, duration_s)` that returns a
`SpeechStats` summary. Aggregation/trends are computed from the opt-in encrypted corpus
(ADR-012); a richer prosodic pause-ratio can reuse the already-present parselmouth dep later.
OFF by default.

## Consequences

- Fully ship-now with **no new dependency** — pure text + timestamp statistics.
- Distinct from Vocal-Strain (physiology) and Confidence Ink (STT) — communication-style metrics.
- Privacy (ADR-011/012): derived only from the opt-in encrypted corpus, aggregates never leave
  the machine, and the existing `corpus destroy` path already provides a forget button.
- Caveat: filler lists are language/register-specific → a conservative default set, tunable.
