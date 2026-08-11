# ADR-v2-099 — Breath-Paced Dictation

**Status:** Accepted (2026-07-02) · Wave L
**Context links:** autostop (silence), prosody (pause→¶), [[adr-v2-101-hesitation-hold-endpointing]], [[adr-011]]

## Context

Wave L research (#4) — Hands-Free Auto-Stop and the Adaptive Latency Governor key off *silence*;
Prosody Ink keys off pause→¶. Breath is a *different physiological signal* (the inhalation envelope):
using natural breath groups as sentence/paragraph boundaries and injection cadence — you breathe,
YazSes commits a chunk — gives segmentation that matches how people actually chunk spontaneous
speech, and it works even when the user doesn't pause silently. Anchor: Chauhan et al., *BreathPrint*
(ACM MobiSys 2017); in-ear breathing-phase classification (MDPI Sensors 24(20):6679, 2024) — breath
onsets are recoverable from a microphone envelope by peak/envelope detection.

## Decision

Add an opt-in **Breath-Paced Dictation**: `[breath] enabled=false, min_gap_s=1.0,
onset_threshold=0.6`. Pure cores in `breath/segment.py`: `breath_envelope(audio, fs)` → a smoothed
rectified envelope (pure numpy), `detect_breath_onsets(env, fs, min_gap_s, rel_threshold)` → onset
times via a debounced threshold crossing, and `segment_by_breath(tokens, token_times, breath_onsets)`
→ breath-group chunks (a breath before a token starts a new group). The envelope/onset math is pure
numpy; no model. OFF by default.

## Consequences

- Segmentation that matches natural breath groups, even without silent pauses.
- Pure numpy envelope + peak-pick → fully testable with synthetic signals.
- Distinct from Auto-Stop/Prosody Ink (breath signal vs silence/pause).
- Privacy (ADR-011): local audio only.
- Caveat: mic-envelope breath detection is coarse (a dedicated respiration sensor is a later tier);
  off by default.
