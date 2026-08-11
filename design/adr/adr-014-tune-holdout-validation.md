# ADR-014 — Held-out validation for `yazses tune` proposals

**Status:** Accepted (2026-06-19)
**Context links:** [[adr-011]] (zero telemetry / offline), [[adr-012-self-improvement-loop]] (the learning corpus this builds on), [[adr-013-llm-cleanup]] (guarded-output philosophy)

## Context

ADR-012 introduced the opt-in learning loop: `learning/analysis.py` turns captured
events into `Proposal`s (vocabulary, VAD threshold, model upgrade, disfluency
fillers, SLM few-shots) and `yazses tune` lets the user approve and apply them.

A 2026 research pass over the *accountable-autonomy* corpus (10 domains, ~820
papers read in full; see `~/scratch/10-000papers/reports/`) flagged a concrete
defect in this design. The single most common failure mode of self-improvement
loops — documented at scale in domains D8 (autonomous science) and D9 (evaluation)
— is **evaluating a proposed change on the very data it was derived from.** The
canonical example: an "AI scientist" system produced an auto-accepted paper claiming
100% accuracy that, on audit, had ~57% train/test overlap (`arxiv-2504.08066`);
benchmark scores routinely fail to reproduce when the evidence is re-examined
(`arxiv-2605.10448`, which recommends *partial-identification bounds* and a
"prefer A over B only if A's lower bound > B's upper bound" support rule).

YazSes had exactly this shape: every `_propose_*` in `analysis.py` both *generates*
a proposal and *counts its evidence* from the same full event set. On one user's
small corpus a proposal can look compelling purely because it was fit to the
recordings it is then scored against. Applying it is a gamble, not an
evidence-backed improvement — which contradicts the module's own docstring promise
("every proposal is backed by counted evidence from real events").

This is a *local, offline, single-user* tool, so the rest of the corpus (provenance
attestation, cryptographic audit, liability, agent identity) does **not** apply.
Only the methodological lesson transfers — but it transfers cleanly and cheaply.

## Decision

Validate every proposal on a **chronological held-out split** of the corpus before
surfacing it, and show the user an explicit validation status.

1. **Chronological split.** Events are ordered by time. The most recent
   `holdout_fraction` (default 20%, ≥1 event) become the **held-out** set; the
   older remainder is the **fit** set. Proposals are generated from the fit set
   *only* (via the existing `analyze`).

2. **Leakage guard.** Held-out events whose normalized text duplicates a fit-set
   event are dropped from the held-out set before scoring, so a phrase the user
   repeats verbatim cannot inflate both sides of the split.

3. **Per-kind corroboration.** Each proposal is re-checked against the held-out set
   using the same signal that produced it (e.g. a vocabulary term must *still* be
   missed on unseen events; a model upgrade must *still* show re-transcription
   disagreement; a VAD drop must *still* have silent discards). The count of
   corroborating held-out events is recorded as `Proposal.holdout_support`, with
   `holdout_size` = the held-out denominator.

4. **Small-corpus fallback.** If the corpus is below `min_corpus` (default 20
   events) there is too little data to hold out meaningfully. Proposals are still
   produced from the full set, but marked `holdout_support = None` →
   status **"unvalidated (corpus too small)"** rather than silently presented as
   verified.

5. **Status surfaced, decision left to the user.** `Proposal.status` reports one of
   *validated (N/M held-out)* · *unverified — no held-out corroboration* ·
   *unvalidated (corpus too small)*. `yazses tune` prints it; validated proposals
   sort first. The loop never auto-applies — it stays propose→approve→apply
   (consistent with ADR-012), but the user now approves on honest evidence.

The new entry point is `analyze_validated(events, config, *, holdout_fraction,
min_corpus)`; the original `analyze` is unchanged and still used for the fit-set
generation, so existing tests and callers keep working.

## Alternatives rejected

- **Cross-validation / k-fold.** Statistically stronger but overkill and noisy on a
  single user's tiny corpus; a chronological holdout matches how the tool is used
  (recent speech is the real "future") and is trivially explainable.
- **Random split.** Rejected — dictation is temporally correlated (a session
  repeats jargon), so a random split leaks session context across the boundary.
  Time-ordering is the honest analogue of "predict the future from the past."
- **Hard auto-suppression of unverified proposals.** Rejected — on a small corpus
  that would hide every proposal. Surfacing status and letting the user decide
  preserves agency (and matches the "support rule" as guidance, not a gate).
- **A new metric model (WER via a reference engine on every proposal).** The
  re-transcription distance from ADR-012 already serves as the quality proxy;
  computing full WER per proposal adds cost without changing the decision. Deferred.

## Consequences

- Proposals now carry a trust signal: the user can distinguish "corroborated on
  recordings it never saw" from "fit to its own data." The module's
  evidence-backed promise becomes true rather than aspirational.
- On corpora < `min_corpus`, behavior is unchanged except for an honest
  "unvalidated" label — no regression for early users.
- `Proposal` gains two optional fields + a `status` property; `holdout_fraction`
  and `min_corpus` are tunable in code (not yet config-exposed — deferred until
  there is evidence a user needs to change them).
- Still fully offline / zero-telemetry (ADR-011): the split is computed locally
  over the already-captured corpus; nothing new is captured or transmitted.
- Deferred: exposing `holdout_fraction`/`min_corpus` via config; partial-
  identification interval display; applying the same held-out discipline to a
  future automated "did cleanup help" evaluation.
