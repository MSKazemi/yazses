# ADR-v2-102 — Involuntary-Vocalization Auto-Excision

**Status:** Accepted (2026-07-02) · Wave L
**Context links:** disfluency (linguistic fillers), audioguard (environmental events), hallucination (STT artifacts), [[adr-011]]

## Context

Wave L research (#8) — automatically detect and delete involuntary self-produced sounds (cough,
throat-clear, sneeze, sniff) from the dictation stream so they never turn into garbage tokens or
trigger spurious commands. The Disfluency filter removes *linguistic* fillers ("um"); the Ambient
Audio-Event Guard handles *environmental* privacy events; the Hallucination Guard filters STT
artifacts. None excise the user's own **non-linguistic bodily sounds** — a real problem for
chronic-cough and medical dictation. Anchor: *Hyfe Cough Tracker* (F1000Research 11:730; validation
PMC11809693) — sub-0.5 s cough sounds classified on-device at 91% sensitivity / 98% specificity.

## Decision

Add an opt-in **Involuntary-Vocalization Auto-Excision**: `[involuntary] enabled=false`. Pure cores
in `involuntary/excise.py`: `is_involuntary_vocalization(seg_feats)` → `cough` | `throat_clear` |
`sneeze` | `None` from duration/energy/centroid/voicing/burst features, and
`excise_nonspeech_spans(tokens, token_spans, flagged_spans)` → the token list with any token
overlapping a flagged span removed. The span-removal is pure; the acoustic classifier is the lazy
extra. OFF by default.

## Consequences

- Cough/throat-clear/sneeze never corrupt the transcript — a win for chronic-cough and medical
  dictation.
- Pure overlap/removal logic → fully testable.
- Distinct from Disfluency (bodily vs linguistic), Audio-Guard (self vs environmental).
- Privacy (ADR-011): local audio only; excised, never stored.
- Caveat: coarse feature thresholds (a learned classifier is a later tier); off by default.
