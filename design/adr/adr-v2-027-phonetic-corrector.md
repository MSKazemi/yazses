# ADR-v2-027 — Phonetic Corrector (fix mis-heard names by sound)

**Status:** Accepted (2026-07-02) · Wave E
**Context links:** [[adr-v2-004-context-primed]] (biases prior), [[adr-v2-009-personal-adapter]] (biases prior), [[adr-011]]

## Context

The Wave E research (#2) notes that prompt-biasing (Context-Primed, Personal Adapter) shapes
the decoder's *prior* but can't recover a proper noun the model already got wrong ("Cuber
Netties" for "Kubernetes"). A post-hoc corrector that matches transcript tokens against the
personal lexicon in *sound* space fixes these. Anchors: G2P (espeak-ng/phonemizer), phonetic
edit distance; the post-hoc ASR-correction pattern of MathSpeech (arXiv 2412.15655).

## Decision

Add an opt-in **Phonetic Corrector** operating on the *output*: for each transcript token,
if it isn't already a known word, compare its **phonetic key** to each personal-vocabulary
term's key and, when the normalized key-distance is within `max_distance`, replace it. The
pure core ships a compact, documented phonetic key (a deterministic consonant-skeleton
reduction — *not* a claim to be Metaphone) + normalized Levenshtein; a stronger G2P/neural
phonetic backend is opt-in behind a `phonetic` extra. `[filters.phonetic] enabled=false,
max_distance`. OFF by default.

## Consequences

- Corrects the *output* (a different stage than prior-biasing) → recovers already-wrong words.
- Pure key + distance → fully testable with no model; the vocab is the user's local list.
- On-device only (ADR-011).
- Caveat: over-eager correction could rewrite a correct rare word → conservative distance
  floor, only correct tokens not already in a known-word set, off by default.
