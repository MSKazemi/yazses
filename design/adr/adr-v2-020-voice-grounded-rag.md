# ADR-v2-020 — Voice-Grounded RAG over Personal Notes

**Status:** Accepted (2026-07-02) · Wave D
**Context links:** [[adr-v2-000-interaction-layer]], [[adr-v2-005-spoken-recall]] (distinct: search past dictation), [[adr-013-llm-cleanup]] (llama.cpp), [[adr-011]]

## Context

The Wave D research (#8) proposes asking a question by voice and getting an answer grounded
in — and citing — the user's own local notes/documents. This is distinct from Spoken Recall
(ADR-v2-005), which searches *past dictations*; RAG retrieves and cites *arbitrary local
docs* and composes a generated, sourced answer. Anchors: EmbeddingGemma (308M, Sep 2025) +
`sqlite-vec` + Gemma 3 270M — all small enough to run on-device (ADR-011).

## Decision

Add an opt-in **voice-grounded RAG**: `[rag] enabled=false, top_k, min_score, embed_model,
store_path`. The value-carrying retrieval logic is **pure** and testable —
`cosine` (similarity), `rank_chunks` (filter by `min_score`, sort, take `top_k`),
`format_context` (numbered snippets + a Sources list for inline citation). The embedding
model, the `sqlite-vec` index, and the answer LLM (reuse ADR-013 llama.cpp) are lazy behind
a `rag` extra. Answers must carry citations; extractive fallback when generation is off.

## Consequences

- Retrieval ranking + citation formatting are pure → fully unit-tested with no model/index.
- Distinct from Spoken Recall; reuses the existing llama.cpp path for generation.
- On-device only (ADR-011); documents never leave the machine.
- Caveat: hallucination risk → require inline `[n]` citations and support an extractive
  (no-LLM) mode that just returns the ranked snippets.
