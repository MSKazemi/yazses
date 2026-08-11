# ADR-v2-038 — Dictation Reflow (Voice Outliner)

**Status:** Accepted (2026-07-02) · Wave F
**Context links:** [[adr-013-llm-cleanup]] (guard pattern), [[adr-v2-019-meeting-scribe]] (distinct: capture), [[adr-011]]

## Context

The Wave F research (#1) proposes: after a long ramble, say "structure this" and the last
burst is rewritten in place into headings, bullets, and action items. Anchor: on-device SLMs
(Gemma 3n E2B/E4B, Qwen3 local; arXiv 2604.07035). This is distinct from Meeting Scribe
(streaming diarization capture) and Spoken Recall (RAG/memory) — it is *post-hoc restructuring
of your own monologue on command*.

## Decision

Add an opt-in **Dictation Reflow**: `[reflow] enabled=false`. The pure core `reflow(text)`
segments a monologue at discourse markers ("first/next/then/finally/in conclusion") into
bullets and flags action items ("action item / to do / I need to") as checkboxes — a heuristic
outline that ships now with no ML. The higher-quality SLM reflow is deferred behind a `reflow`
extra (reuse llama.cpp + the ADR-013 length/token-preservation guard so a rewrite can't drop
content). OFF by default.

## Consequences

- Ship-now with **no new dependency** — discourse-marker segmentation + outline builder.
- Distinct from Meeting Scribe (capture) and Recall (memory) — on-command restructuring.
- Privacy (ADR-011): operates only on the just-dictated text in RAM; SLM (when added) is local.
- Caveat: heuristic segmentation is coarse → the SLM path (guarded) is the quality upgrade; off
  by default.
