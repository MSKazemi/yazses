# ADR-v2-050 — Grammar Repair (minimal-edit GEC)

**Status:** Accepted (2026-07-02) · Wave G
**Context links:** [[adr-013-llm-cleanup]] (disfluency, not grammar), [[adr-v2-017-tone-formatting]] (register, not grammar), [[adr-011]]

## Context

Wave G research (#9) — fix article/agreement/preposition errors in dictated text with **minimal
edits**, tuned for L2/ESL speakers, register-preserving: "I go to meeting yesterday and discuss
with he" → "I went to the meeting yesterday and discussed with him", without rewriting the
user's style. Anchors: minimal-edit GEC (arXiv 2506.13148, BEA-2025 SOTA), CoEdIT
(2305.09857; grammarly/coedit-large, CPU-runnable, ~60× smaller than large LLMs).

Distinct from LLM Cleanup (removes *disfluencies*) and Tone Formatting (changes *register*) —
neither corrects grammatical errors, and no existing feature targets the L2 population.

## Decision

Add an opt-in **Grammar Repair**: `[gec] enabled=false`. Two pure cores: the crucial safety
primitive `is_minimal_edit(src, out)` (token-overlap + bounded length change → rejects a model
that paraphrases instead of minimally correcting), and a small dependency-free rule tier
`fix_articles(text)` (a/an agreement using a vowel-sound heuristic with the standard
exception sets: "an hour", "a university"). The CoEdIT-small minimal-edit LM is lazy behind a
`gec` extra, gated by `is_minimal_edit` so it can never over-rewrite. OFF by default.

## Consequences

- Fills the grammar-correction gap for L2 dictation; distinct from disfluency/tone.
- Pure guard + article rules → fully testable with no model; the guard makes the deferred LM safe.
- Privacy (ADR-011): local GEC only, unlike Grammarly (no text sent to a server).
- Caveat: the article heuristic is imperfect → exception sets + off-by-default; the neural tier
  is the quality path, always behind the minimal-edit guard.
