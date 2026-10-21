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

> The default map stated above (flat-hum = repeat) is superseded by owner decision 1 of the
> 2026-10-21 amendment below: a flat hum is unmapped by default.

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

## Amendment (2026-10-21) — Accepted (owner decisions, 2026-10-21)

**Status of this amendment: accepted 2026-10-21.** It was drafted as a proposal while building
toward wiring (#164, WIRE-CONTOUR-001); the owner then decided open points (a) and (b) below
(see *Owner decisions*), and the feature is now wired. `[contour]` stays off by default and is
marked experimental; point (c) stands as a known limitation.

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

### Owner decisions (2026-10-21)

1. **A flat hum is unmapped by default** (open point a). The default map is now rise → confirm,
   fall → cancel, rise-fall → undo; `flat` maps to nothing, so a reflexive thinking "hmm" does
   nothing. A user profile passed to `gesture_to_command` may still map it.
2. **With `[contour]` enabled, the hum check runs before the #598 no-speech discard** (open
   point b), so a hum is not thrown away first. With `[contour]` disabled the #598 gate is
   byte-for-byte unchanged.

### How it is wired

`Daemon._contour_gesture` calls `contour/wiring.py::run_hum_gesture` at two points in
`_on_hold_end`, and returns at once without importing anything while `[contour]` is off:

- **Before the #598 discard.** When the speech detector has found no speech in a burst, the burst
  gets the hum check before it is discarded. No transcript exists yet, so the detector's
  positive "no speech" finding stands in for the empty-transcript half of the gate; the
  mostly-voiced half applies in full. A burst that is not a recognised hum is discarded as
  before. This is the stricter reading of "before": a burst the detector takes for speech is
  never classified here, because without a transcript a spoken, mostly-voiced "no" would
  pass the gate as a falling hum.
- **After decoding, before the empty-transcript discard.** A burst that reached the decoder is a
  gesture only if the transcript is empty or hum spellings only and the audio is mostly voiced.

A recognised gesture runs an existing path and types nothing: `confirm` / `cancel` answer a held
confirmation through the same holder as the spoken "confirm" and the face switch (a no-op when
nothing is held); `undo` deletes the last burst YazSes typed, as "scratch that" does (refused
with no editable target, or with `[revise]` off). Anything else falls through unchanged.
Tested on synthetic tones only (`tests/test_contour_daemon_wiring.py`).
