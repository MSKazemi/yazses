# ADR-v2-072 — Per-Language Auto Model Switching

**Status:** Accepted (2026-07-02) · Wave I
**Context links:** [[adr-v2-040-true-code-switch]] (within-utterance vs between-utterance), [[adr-v2-034-polyglot-switch]] (fixed pair), [[adr-011]]

## Context

Wave I research (#4) — speak any of your languages and the daemon detects it (Whisper LID on the
first ~1-2 s) and hot-swaps to a language-specialized distil model plus language-appropriate
punctuation/ITN before decoding. Distinct from True Code-Switch (mixing *within* one utterance)
and Polyglot Switch (a fixed configured pair) — this is *between-utterance* whole-language routing
with a per-language model swap. Anchors: Whisper built-in LID + per-language distil/LoRA models.

## Decision

Add an opt-in **Per-Language Auto Model Switching**: `[langroute] enabled=false,
min_confidence=0.5`. The pure core `route_language(lang, confidence, registry)` returns a
`ModelChoice(language, model, itn)`: below `min_confidence` it routes to the registry default;
otherwise it maps the detected language to its specialized model + ITN locale, falling back to the
default for unregistered languages. Dependency-free. The extra per-language model files and the
live LID call are deferred. OFF by default.

## Consequences

- Seamless multilingual dictation with no manual toggle; pure selector, model files optional.
- Distinct from Code-Switch (within-utterance) and Polyglot (fixed pair).
- Privacy (ADR-011): LID runs on-device; no language-preference profile is uploaded.
- Caveat: routing quality depends on LID accuracy on the lead-in → the confidence gate falls back
  to default; off by default.
