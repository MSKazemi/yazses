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

## Amendment (2026-10-21) — PROPOSED, for the owner's review

**Status of this amendment: proposed, not accepted.** It records what was built toward wiring
(#164, WIRE-CONTOUR-001) and adds a decision the original text does not make. Nothing below is
wired; `[contour]` is still unreachable and off by default.

**What was missing.** The decision classifies an F0 contour, but nothing on main produced one.
A shared numpy YIN tracker now does (`src/yazses/audio/pitch.py`, also used by ADR-v2-101), and
`src/yazses/contour/burst.py` turns a finished burst into a smoothed voiced contour for the
classifier above. No optional extra is involved.

**The new decision: when is a burst a gesture at all?** Every voiced word has a contour — a
spoken "no" falls like the cancel hum — so classifying every burst would turn dictation into
commands. Proposed gate (`is_nonword_voiced_burst`), both halves required:

1. the transcript is empty or only hum spellings (`hmm`, `mm`, `mhm`, `uh`, `um`, `ah`, `er`…).
   Any other word, in any script, keeps the burst as dictation — including spellings that are
   also words or letters (`hum`, `err`, `em`, `m`, `u`, `n`);
2. at least 80% of the burst's active frames are voiced, and at least 400 ms of them are.

Open points for the owner: (a) the default map sends a *flat* hum to `repeat`, so a lone
thinking "hmm" would fire it unless 400 ms (a guess, unmeasured) separates deliberate hums
from reflexive ones — consider leaving `flat` unmapped by default; (b) the #598 speech-presence
check runs before transcription and may discard a hum, so the wiring must choose whether the
contour check runs before it; (c) the thresholds were checked on synthetic tones only, not on
recorded hums.
