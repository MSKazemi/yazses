# ADR-v2-077 — Confidence-Gated Re-Ask

**Status:** Accepted (2026-07-02) · Wave J · **flagship**
**Context links:** [[adr-v2-036-confidence-ink]] (marks only vs repairs), [[adr-v2-032-semantic-auto-stop]], [[adr-011]]

## Context

Wave J research (#1) — two independent streams converged on this. Instead of silently injecting a
low-confidence guess, hold only the uncertain span and interactively resolve it: an A/B
disambiguation of a confusable set (their/there) or "say that one word again," patching only the
placeholder. Distinct from Confidence Ink, which only *marks* uncertainty — this *repairs* it and
closes the loop. faster-whisper already emits token log-probs, so the gate is pure arithmetic.
Anchors: arXiv 2503.15124 (ASR confidence for user-assisted correction, 2025), 2502.13446
(Whisper confidence estimation, 2025), 2402.06509 (uncertainty-gated clarification, EACL 2024).

## Decision

Add an opt-in **Confidence-Gated Re-Ask**: `[reask] enabled=false, threshold=-1.0`. Pure cores:
`low_confidence_spans(tokens, logprobs, threshold)` groups consecutive below-threshold tokens into
`Span`s, `confusion_set(word)` returns the known confusable options for a word, and
`parse_choice(text, options)` resolves a spoken pick (ordinal or literal) to one option.
Dependency-free (faster-whisper already returns the log-probs). A fine-tuned confidence-estimator
head is deferred. OFF by default.

## Consequences

- Closes the correction loop instead of just flagging — the flagship interaction upgrade.
- Pure math on the local transcript; re-ask audio is transient.
- Distinct from Confidence Ink (marks vs repairs).
- Privacy (ADR-011): all local; nothing transmitted.
- Caveat: the pure layer uses raw log-probs + a curated confusion table → a learned estimator is
  the deferred quality tier; off by default.
