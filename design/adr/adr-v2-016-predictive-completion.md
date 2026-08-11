# ADR-v2-016 — Predictive Dictation Completion

**Status:** Accepted (2026-07-02) · Wave D
**Context links:** [[adr-v2-000-interaction-layer]], [[adr-v2-009-personal-adapter]] (n-gram bias), [[adr-013-llm-cleanup]] (llama.cpp), [[adr-011]]

## Context

The Personal Adapter (ADR-v2-009) only mines n-grams into Whisper's `initial_prompt`
(biasing recognition). The Wave D research (#4) proposes generative next-text prediction:
a tiny on-device LLM (Gemma 3 270M INT4 ≈125 MB, or SmolLM3) proposes the rest of a
sentence on a pause, accepted by voice ("accept"/"take it"). No offline dictation tool
offers voice-accepted completions; great for boilerplate and low-effort/accessibility use.

## Decision

Add an opt-in **predictive completion**: `[predict] enabled`, `model_path`,
`max_tokens`, `accept_phrases`. A pure layer parses accept/decline phrases and merges an
accepted suggestion into the buffer; the generator is lazy behind a `[predict]` extra
(reuse the existing `llama-cpp-python` dep from ADR-013) and fed the corpus n-grams for
personalization. Runs in a background thread and only surfaces on a pause — never blocks
injection. OFF by default.

## Consequences

- Reuses the llama.cpp path already present for LLM cleanup; no new base dep.
- Background-thread + pause-gated so the hold-to-talk latency budget is untouched.
- Caveat: suggestions can be wrong → always explicit voice-accept, never auto-commit.
  On-device only (ADR-011); the model sees only local text.
