# ADR-v2-121 — LoadGuard (cognitive-load-aware guardrails)

**Status:** Accepted (2026-07-03) · Wave N
**Context links:** cmdsafety (command risk), reask (confidence re-ask), coach (analytics),
voicehealth, [[adr-011]]

## Context

Wave N research (#7) — speech carries measurable cognitive-load signals: more/longer pauses,
higher filler rate, slowed speaking rate, more self-corrections. When a user is overloaded
(stress, ADHD, fatigue), that is exactly when a mis-fired destructive voice command hurts most.
The set gates *what* is risky (cmdsafety) and *how confident* the ASR is (reask), but not the
*user's state*. Anchor: cognitive-load-from-speech literature (arXiv 2606.12971); ADHD
"Understood" guidance.

## Decision

Add an opt-in **LoadGuard**: `[loadguard] enabled=false, threshold=0.7`. Pure cores in
`loadguard/policy.py`: `estimate_load(metrics)` — normalize whichever signals the pipeline
already computes (`pause_ratio`, `filler_rate` saturating at 0.15/word, slowdown below 160 wpm,
`self_corrections` saturating at 3) to 0..1 and average them (missing signals skipped);
`guard_policy(load, threshold)` — `high` (≥ threshold): widen confirmations + defer risky
actions; `elevated` (≥ 0.7·threshold): widen confirmations only; else `normal`. OFF by default.

## Consequences

- Destructive actions get harder to trigger exactly when the user is least reliable.
- Pure estimator + policy → fully testable; signals reuse existing pipeline metrics (no new
  audio processing, no new dependency).
- Distinct from cmdsafety (action risk) and reask (ASR confidence) — this models user state.
- Privacy (ADR-011): scalar features only, computed locally, never stored raw.
- Caveat: heuristic signal fusion (not a trained model); per-user baselines are a later tier;
  off by default.
