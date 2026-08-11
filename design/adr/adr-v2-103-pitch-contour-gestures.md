# ADR-v2-103 — Pitch-Contour Vocal Gestures

**Status:** Accepted (2026-07-02) · Wave L
**Context links:** [[adr-v2-095-vocal-joystick]] (analog vs symbolic), gesture (keyboard chords), commands (word-based), [[adr-011]]

## Context

Wave L research (#9) — assign short *pitch contours* (rising = confirm, falling = cancel, rise-fall =
undo, flat-hum = repeat) as a word-free, language-independent command vocabulary: hum a shape to fire
a command in a noisy room or without articulating words. Distinct from the Vocal Joystick (analog
*position* control) and from every word-based command: this is a **discrete symbolic** channel built
purely from F0 shape, robust in noise, usable by people who can phonate melody but not clear speech.
Anchor: the non-speech vocal-interaction line (Bilmes/UW Vocal Joystick) + whistled-language
phonetics (Meyer, *Whistled Languages*, Springer 2015) — pitch contour alone carries a full symbolic
channel.

## Decision

Add an opt-in **Pitch-Contour Vocal Gestures**: `[contour] enabled=false`. Pure cores in
`contour/gesture.py`: `normalize_contour(f0_series)` → a z-normalized voiced contour,
`classify_contour(f0_norm)` → `rise` | `fall` | `rise_fall` | `flat`, and `gesture_to_command(gesture,
profile)` → a command name (a default map, user-overridable). The F0 tracker is the lazy extra; the
sequence classifier is pure. OFF by default.

## Consequences

- A discrete, language-independent, noise-robust command channel for dysarthria/anarthria users who
  retain pitch control.
- Pure classifier over an F0 array → fully testable and deterministic.
- Distinct from Vocal Joystick (symbolic vs analog) and word commands.
- Privacy (ADR-011): local F0 only.
- Caveat: a small fixed gesture set (four contours); off by default.
