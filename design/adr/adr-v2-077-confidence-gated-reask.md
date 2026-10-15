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

## Wiring (2026-10-15)

Wired by `reask/gate.py` and one gate call in `core/daemon.py` (`_reask_gate`), tier `optional`.
Decisions made while wiring, because the pure cores alone do not say what the interaction is:

- **Hold granularity is the burst, not the span.** The daemon types a burst as one string, so the
  gate holds the whole burst and patches the one word on resolution.
- **Fire only on a specific signal** (ADR-021): exactly one uncertain word, in the confusion table,
  appearing exactly once in the text. Unreported per-word probability (`0.0`) reads as certain.
- **The reply is an anchored grammar**, not `parse_choice`'s search: the next dictation is arbitrary
  prose, and a search would pick "one" out of "I want one coffee". A bare number word is not an
  ordinal because `two` is itself an option.
- **Nothing is lost.** A non-pick reply releases the held text and then types the reply; an
  unanswered hold expires after ten seconds to the **clipboard**, never to the keyboard, because
  typing later lands in whatever has focus by then.
- Replies are recognised in dictation mode only; a reply spoken on the command key is not a pick,
  and the hold then expires to the clipboard.
