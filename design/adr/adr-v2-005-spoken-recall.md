# ADR-v2-005 — Spoken Recall & Ambient Scratch

**Status:** Accepted (2026-07-02) · Wave B
**Context links:** [[adr-v2-000-interaction-layer]], [[adr-011]] (offline), [[adr-012-self-improvement-loop]] (encrypted corpus)

## Context

The ambient research (internal) shows the market
retreating from cloud lifelogging (Microsoft Recall backlash; Rewind→Limitless→Meta
collapse with EU/UK shutdown). Nobody credibly owns "ambient personal memory that
provably never leaves your machine." YazSes already has the exact asset: an encrypted,
machine-bound corpus (ADR-012) and a no-telemetry stance — and it is the only process
that already sees what you deliberately dictate.

## Decision

Two opt-in capabilities over the existing encrypted corpus:
1. **Ambient Scratch** — a dedicated hotkey transcribes speech straight into the corpus
   as a timestamped, app-tagged "note to self" **without injecting** into any app.
2. **Spoken Recall** — a hold-to-talk query answered from that corpus, offline: retrieve
   passages by semantic similarity (sqlite-vec over a local embedder, reusing the
   voiceprint/embedding infra) or, initially, the Karpathy plain-text/agent-read pattern
   over decrypted text. A distinct "recall mode" ensures a query is never typed into the
   focused app; results surface via overlay/read-back.

Config: `[recall] enabled=false`, `scratch_hotkey`, `index=embedding|plaintext`,
`max_results`. New package `recall/` (query + index); capture reuses `learning/capture`.
Strictly push-to-talk (no always-on mic); honors ADR-012 redaction/retention.

## Consequences

- **+** Fills the post-Recall trust vacuum with a consent-first, on-device memory of your
  own words; strong differentiator.
- **+** Reuses corpus + crypto + embedder; capture path already exists.
- **−** Retrieval quality on a sparse personal corpus is uncertain → start with plaintext/
  recency, add embeddings once corpus grows; clear recall-mode UX so queries don't leak
  into apps.
- **−** Scope-creep risk toward "always listening" → strictly push-to-talk, opt-in.
