# ADR-v2-069 — Hard Contextual Biasing (hotword trie)

**Status:** Accepted (2026-07-02) · Wave I
**Context links:** [[adr-v2-039-context-primed-dictation]] (soft prompt), [[adr-v2-041-personal-speech-adapter]] (LoRA training), [[adr-011]]

## Context

Wave I research (#1) — make names/jargon/personal vocab *actually* get recognized, not just softly
hinted. `initial_prompt` priming is soft and unreliable for OOV words; LoRA needs training. A
prefix-trie built from the user's vocabulary can bias decoding (logit boosting) or rescore the
N-best so rare terms win — retraining-free. Anchors: WCTC-Biasing (arXiv 2506.01263), trie K-step
biasing (2509.09196), sherpa-onnx hotwords, Whisper zero-shot rare-word biasing (2502.11572).

Distinct from Context-Primed (soft prompt) and Personal Adapter (LoRA fine-tune).

## Decision

Add an opt-in **Hard Contextual Biasing**: `[hotwords] enabled=false, boost=2.0`. Pure cores:
`HotwordTrie` (char-level insert / `is_term` / `has_prefix`), `build_hotword_trie(terms)`, and
`rescore_nbest(hypotheses, trie, boost)` — a post-hoc N-best rescorer that adds `boost` per
hotword hit and re-ranks, needing **no model internals**. The deeper CTC/attention logit-biasing
hook (sherpa-onnx / WFST) is deferred behind a `biasing` extra. OFF by default.

## Consequences

- Retraining-free rare-word recognition; the pure rescorer already helps, the deferred hook adds
  in-decoder biasing.
- Distinct from soft-prompt priming and LoRA.
- Privacy (ADR-011): trie built locally from the user's own words; nothing transmitted.
- Caveat: the pure rescorer is token-level (single-word terms); multi-word phrase biasing is the
  deferred decoder tier. Off by default.
