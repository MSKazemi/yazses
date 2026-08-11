# ADR-v2-064 — Few-Shot Personal Command Spotter

**Status:** Accepted (2026-07-02) · Wave H
**Context links:** [[adr-v2-033-wake-word]] (single activation vs a set of triggers), [[adr-012-self-improvement-loop]] (encrypted enrollment), [[adr-011]]

## Context

Wave H research (#10) — enroll a handful of examples of short personal commands ("send", "stop",
"newline") that fire actions without a full Whisper decode, cutting latency/CPU. Anchors:
EdgeSpot few-shot KWS (arXiv 2601.16316), few-shot open-set on-device KWS (2306.02161), GE2E-KWS
zero-shot (2410.16647).

Distinct from Wake-Word (a *single* activation phrase) — this is a *set of action triggers*
running alongside dictation, personalized from few-shot enrollment.

## Decision

Add an opt-in **Few-Shot Command Spotter**: `[cmdspotter] enabled=false, threshold=0.75`. The
pure core is `CommandSpotter` — an enrollment store keyed by label with prototype embeddings,
and `match(embedding)` returning the best label by cosine similarity above the threshold (else
None). Dependency-free logic; the KWS embedding encoder that turns audio into vectors is deferred
behind a `kws` extra. Enrollment embeddings live in the existing encrypted corpus (ADR-012). OFF
by default.

## Consequences

- Low-latency personalized micro-commands; pure cosine dispatch, no model.
- Distinct from Wake-Word (a trigger set vs one phrase).
- Privacy (ADR-011/012): enrollment embeddings biometric-adjacent, encrypted-corpus only, never
  leave the machine.
- Caveat: false triggers → the cosine threshold + off-by-default; the encoder is the deferred tier.
