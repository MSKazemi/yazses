# ADR-v2-079 — Self-Learning Correction Dictionary

**Status:** Accepted (2026-07-02) · Wave J
**Context links:** [[adr-v2-026-phonetic-corrector]] (pronunciation vs edit history), [[adr-012-self-improvement-loop]], [[adr-v2-050-redaction-ink]], [[adr-011]]

## Context

Wave J research (#6) — reuse the opt-in `EditWatcher` read-back: when you fix the same ASR-output→
edit pair repeatedly ("yaz says" → "YazSes"), promote it to a boundary-guarded, longest-match
find→replace applied automatically to future output — a high-precision patch table mined from your
own accepted edits. Distinct from the Phonetic Corrector (pronunciation-based), the vocabulary
(biases `initial_prompt`), and tune (config diffs) — this rewrites *output* from edit history.
Anchor: arXiv 2406.07589 ("Tag and correct: high-precision post-editing of ASR errors").

## Decision

Add an opt-in **Self-Learning Correction Dictionary**: `[corrdict] enabled=false, min_support=3`.
Pure cores: `mine_substitutions(events, min_support)` counts (wrong→right) edit pairs and keeps
only those meeting `min_support` with an unambiguous dominant correction, and
`apply_corrections(text, table)` applies them longest-match, word-boundary-guarded. Dependency-free
and deterministic (it can only apply corrections it has actually seen — it can't hallucinate new
errors). A seq-tagger for generalization is deferred. OFF by default.

## Consequences

- Learns your recurring ASR errors and fixes them automatically; high precision by construction.
- Distinct from Phonetic Corrector / vocabulary / tune.
- Privacy (ADR-011/012): derived only from local edits, stored in the encrypted corpus, honours
  `redact_patterns`; no keystroke logging.
- Caveat: only exact seen substitutions (min-support, dominant) → generalization is the deferred
  tagger tier; off by default.
