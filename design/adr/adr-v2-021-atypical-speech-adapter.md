# ADR-v2-021 — Atypical-Speech Personalization + Adapter Held-Out Gate

**Status:** Accepted (2026-07-02) · Wave D (research tier — gate now, fine-tune deferred)
**Context links:** [[adr-v2-009-personal-adapter]] (P1 n-gram bias), [[adr-014-tune-holdout-validation]] (held-out gate), [[adr-015-dysfluency-friendly]], [[adr-012-self-improvement-loop]], [[adr-011]]

## Context

The Wave D research (#11) proposes adapting the acoustic model to dysarthric/accented
speech via a corpus-trained LoRA — extending the Personal Adapter (ADR-v2-009, which only
biases the prompt) and Dysfluency Mode (ADR-015). Anchors: Universal Personalizer (arXiv
2509.15516), dysarthric LoRA 13.9% WER on Euphonia (arXiv 2505.12991). The fine-tune itself
is compute-heavy and out of scope to run in-loop; but the **decision to apply** a trained
adapter is safety-critical — a bad adapter must never silently degrade recognition.

## Decision

Adopt the ADR-014 held-out principle for adapters: a pure gate
`should_apply_adapter(baseline_wer, adapter_wer, min_improvement)` applies a LoRA adapter
**only** when it beats the un-adapted baseline on a held-out slice by at least
`min_improvement` (relative WER reduction). Config extends `[personalize]` with
`lora_min_improvement` (default `0.03`). The training + adapter load stay lazy/deferred
(gated on `personalize.lora`, `lora_min_events`, plugged-in/idle); this ADR ships the pure
gate + config now so the heavy path can never regress accuracy when it lands.

## Consequences

- Pure, testable safety gate → an adapter that doesn't measurably help is never applied.
- Reuses ADR-014's train/test-overlap discipline; on-device only (ADR-011/012).
- No new feature slug — this hardens the existing Personal Adapter path.
- Caveat: WER must be measured on a *held-out* slice (not training data) for the gate to
  mean anything — the caller owns that split, exactly as `yazses tune` does.
