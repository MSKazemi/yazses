# ADR-v2-095 — Vocal Joystick (continuous non-speech analog control)

**Status:** Accepted (2026-07-02) · Wave L
**Context links:** [[adr-v2-093-local-voice-timer]], mousegrid (discrete cell selection vs analog), headpointer, [[adr-011]]

## Context

Wave L research (#1) — the existing 105 features cover discrete *word* commands, Voice Mouse Grid
(say a cell number), and Head-Pointer, but nothing offers **continuous analog** control from the
acoustic-phonetic signal. Sustaining a vowel ("ahh"→right, "eee"→up), with loudness = speed and a
sharp pitch rise = click, is a fundamentally different modality (velocity, not selection) — the core
accessibility interaction for users who can phonate but cannot type, click, or articulate discrete
words reliably. Anchor: Bilmes et al., *The Vocal Joystick* (ACM ASSETS 2006; *Disability &
Rehabilitation: Assistive Technology* 3(1-2), 2008, PMID 18416516) — vowel quality/pitch/loudness →
cursor direction/velocity at ~100 Hz.

## Decision

Add an opt-in **Vocal Joystick**: `[vocaljoystick] enabled=false, max_speed=20.0, click_pitch=250.0`.
Pure cores in `vocaljoystick/control.py`: `vowel_to_direction((F1,F2))` → an 8-way direction (or
`None` in a formant-space deadzone), `vocal_control_vector(dir, loudness, pitch, max_speed)` → a
`(vx, vy)` velocity, and `VocalJoystick` — a pure state machine that integrates frames into a
position and emits `ControlEvent(kind=move|click|idle, dx, dy)` (click on a sharp upward pitch jump).
Formant/pitch extraction is the optional lazy audio extra; the mapping + integrator are pure. OFF by
default.

## Consequences

- A genuinely new continuous-control modality for severe motor impairment (ALS, high SCI, CP).
- Pure mapping + state machine → fully testable with synthetic frames; DSP is isolated behind the
  extra.
- Distinct from Mouse Grid (analog velocity vs discrete cell) and Head-Pointer (vocal vs head).
- Privacy (ADR-011): local audio only; nothing stored or sent.
- Caveat: needs a formant/pitch tracker for live use; the direction thresholds are speaker-general
  (per-speaker calibration is a later tier); off by default.
