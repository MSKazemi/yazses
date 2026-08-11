# ADR-v2-041 — Pronunciation Feedback (L2 practice mode)

**Status:** Accepted (2026-07-02) · Wave F
**Context links:** [[adr-v2-021-atypical-speech-adapter]] (distinct: adapts model vs scores you), [[adr-011]]

## Context

The Wave F research (#8) proposes a practice mode: dictate a target phrase and get per-phoneme
goodness-of-pronunciation (GOP) scoring for accent/second-language training. Anchors: wav2vec2
GOP/MDD — "Enhancing GOP with Phonological Knowledge" (arXiv 2506.02080), "Segmentation-free
GOP" (arXiv 2507.16838). Distinct from Atypical-Speech LoRA (ADR-v2-021), which adapts the
*model to you*; this *scores you against a target* — opposite direction, learner audience.

## Decision

Add an opt-in **Pronunciation Feedback**: `[pronunciation] enabled=false, good_threshold,
poor_threshold`. The pure core scores and formats: `classify(gop, ...)` → `good|fair|poor`,
`overall_score(scores)` (mean), and `problem_phonemes(scores, config)` (phonemes below the
poor threshold → practice list). The wav2vec2 GOP model that produces per-phoneme scores is
lazy behind a `pronunciation` extra. OFF by default; practice audio processed in RAM.

## Consequences

- Distinct audience/direction from Atypical LoRA — a learner scoring tool.
- Pure classification/aggregation → fully testable with no model.
- Privacy (ADR-011): practice audio in RAM; no persistence unless the user saves a local log.
- Caveat: GOP is noisy on short clips → report bands (good/fair/poor), not false precision.
