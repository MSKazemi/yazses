# ADR-v2-010 — Gaze-Routed Dictation & Point-and-Speak

**Status:** Accepted (2026-07-02) · Wave C (experimental)
**Context links:** [[adr-v2-000-interaction-layer]], [[adr-v2-004-context-primed-dictation]] (deixis), [[adr-011]] (frames in-RAM only)

## Context

The AR/wearables research (internal) shows gaze is
the fastest desktop pointing channel, and spatial OSes (visionOS) route input by gaze —
but only inside their own UI. YazSes already has a `gaze/` package (`zones.py` point→zone,
`l2cs.py` webcam backend, 9-point calibration) built for Glance-Type, currently mapping
gaze to a coarse screen zone. No privacy-first local daemon routes dictation *output* by
gaze across arbitrary windows.

## Decision

Extend the existing gaze intake so the pane you look at receives the next dictation, and
resolve deictic commands ("put this here", "close that") against the gaze target + the
Context-Primed accessibility signals (ADR-v2-004). Reuse `gaze/zones.py` (extend
zone→window-handle resolution) and `commands/grammar.py`. Consumer-webcam gaze is ~1–2°
(coarse), so keep zone granularity + a confirm for destructive routes. **EXPERIMENTAL**,
off by default, `--force` to enable; frames are processed in-RAM during a hold and never
stored (ADR-011).

## Consequences

- Adds spatial routing without new base deps (gaze extra already opt-in).
- Coarse accuracy is mitigated by zones + confirm; degrades to the focused window when
  confidence is low.
- Pure zone→window mapping stays testable; the webcam backend remains lazy.
