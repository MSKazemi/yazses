# ADR-v2-034 — Vocal-Strain Guard

**Status:** Accepted (2026-07-02) · Wave E (advisory)
**Context links:** [[adr-v2-002-prosody-autoformat]] (parselmouth acoustics), [[adr-v2-012-accessibility-continuum]], [[adr-011]]

## Context

The Wave E research (#9) proposes an ergonomic/health guardrail for heavy voice users: detect
rising vocal fatigue/strain (jitter, shimmer, HNR drift over a session) and suggest a break —
especially valuable for users with voice disorders. YazSes already ships parselmouth (Praat)
for Prosody Ink, so the analysis primitives are present. This is a *longitudinal well-being*
signal, distinct from Prosody Ink (acoustics → text) and Accessibility Continuum (effort mode).

## Decision

Add an opt-in **Vocal-Strain Guard**: `[voicehealth] enabled=false, threshold, min_samples`.
Two pure cores: `strain_level(jitter, shimmer, hnr)` folds per-utterance biomarkers into a
normalized 0–1 strain estimate (high jitter/shimmer + low HNR = strain), and
`should_suggest_break(samples, config)` fires when the recent mean strain exceeds `threshold`
over at least `min_samples`. Biomarkers are computed on-device via the existing parselmouth
dep; only trend counters are kept (no audio retained). **Advisory only, never diagnostic**;
OFF by default.

## Consequences

- Fills a genuine ergonomic gap using an existing dependency; longitudinal, not per-utterance.
- Pure scoring + trend decision → fully testable with no audio.
- On-device only (ADR-011); no health data leaves the machine, no medical claims.
- Caveat: thresholds need empirical calibration and healthy-baseline personalization → ship
  advisory-only, conservative defaults, off by default.
