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

## Wiring (2026-10-15) — folded into vocab_correct, N-best rescorer retired

The N-best design has no producer: faster-whisper 1.2.1 exposes no N-best list, so
`rescore_nbest` can never receive input, and a second decode path (CTranslate2
`generate(num_hypotheses=k)`) would put the default decode path at risk for one opt-in feature.
The user-facing promise (a name or term from your vocabulary stops being mis-heard) is already
kept by `postprocess/vocab_correct.py` (#73), which repairs mis-heard vocabulary words after
decoding behind four guards: identical phonetic key, a small edit distance, no token under four
characters, and a word that is already correct is a fixed point. Decisions:

- **`hotwords` keeps its slug and becomes a second switch for that one corrector** (`[hotwords]
  enabled`, same effect as `[stt] vocab_correction`), plus `[hotwords] terms` as extra terms read
  only while it is on. One corrector means one guard to tune and one false-alarm profile; no new
  rewriting rule was added, so ADR-021 (guards fire rarely) is met by the existing four.
- **Tier is optional**, not recommended: it rewrites transcribed text, so first-run seeding must not
  turn it on. Disabled, the daemon imports nothing new.
- **Honest naming.** It does not bias the decoder, so the registry name is "Hotwords", not "Hard
  Contextual Biasing", and the description says so.
- **Retired:** the N-best rescorer and `[hotwords] boost` (read by nothing, kept only so an existing
  config still loads). `biasing/trie.py` stays as a tested pure reference, reachable from no entry
  point. In-decoder biasing (sherpa-onnx / WFST) is still deferred and would replace the mechanism,
  not the vocabulary source.
