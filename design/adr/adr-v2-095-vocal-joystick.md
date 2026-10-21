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

## Implementation note (2026-10-21) — the producer

The tracker turned out not to need an extra. `vocaljoystick/formants.py` is pure numpy (a base
dependency): F1/F2 by autocorrelation LPC (pre-emphasis, Hamming window, Levinson-Durbin, root
bandwidth filter), loudness as RMS dBFS mapped onto `[0, 1]`, and pitch from the shared YIN
tracker in `audio/pitch.py` (no second pitch tracker). It emits one `VocalFrame` per 10 ms hop
whose `joystick_args()` are exactly `VocalJoystick.feed`'s arguments. Checked only on synthetic
source-filter vowels (Peterson & Barney 1952 male formants, F0 100-200 Hz); real speech, high
voices and per-speaker calibration are unmeasured. Connecting it to the producer exposed a core
defect, fixed alongside: a click was measured from the `0.0` pitch of an unvoiced frame, so any
voice at or above `click_pitch` clicked on onset; the jump is now measured from the last voiced
pitch within `click_gap_frames`. Pointer wiring (recorder → tracker → joystick → pointer
backend) remains open.

## Implementation note (2026-10-21) — the wiring

The chain is reachable: `vocaljoystick/runtime.py` owns a dedicated microphone stream, a worker
thread and the platform's `PointerSink` (ADR-v2-146), and the daemon builds it only while
`[vocaljoystick] enabled`. There is no new command and no implicit start: the stream is opened
by the existing hands-free re-arm, `yazses handsfree resume`, and closed by `yazses handsfree
pause`, the spoken stop phrase, a pause that begins at the `[handsfree_safety]` gate (when that
gate is on, e.g. a face switch's `pause_pointer`) and shutdown. Nothing is steered while dictation
is recording, transcribing or typing, and the device-change monitor does not reinit PortAudio
while the joystick's stream is open (the daemon stays IDLE, so it has to be told).

The joystick **reads** the gate's pause flag and is **not** a gate source: it never samples,
arms or re-arms the gate. Two reasons. ADR-v2-148 R-24 keeps re-arming with the human entry
points, and a source that closed itself on a fault would otherwise sit in the gate with a stale
sample and report the whole hands-free system as FAULTED while the Head-Pointer works. A fault
(pointer output failed, analysis error) is logged once and shown as a desktop notification that
names `yazses handsfree resume`; `handsfree resume` replies with the "clicks are off" caveat
when the pointer backend has no left button.

`vocaljoystick/drive.py` sits between the integrator and the pointer and holds the misfire
guards, each a specific signal (ADR-021): motion needs one direction held for 150 ms and a
loudness of at least 0.25 (about -50 dBFS); a click needs 150 ms of held voicing, then a pitch
that stays at or above `click_pitch` for 50 ms after the jump (a YIN octave error is dropped),
and clicks are at least 0.5 s apart. These values are tuned on synthetic source-filter vowels
only.

**Correction to the Context above.** "eee"→up was never what the mapping does. /i/ is close
(low F1 → up) *and* front (high F2 → left), so `vowel_to_direction` returns `nw`: "eee" moves
up-left, "ooo" (/u/, close and back) up-right, and "ahh" (/a/, open and back) down-right
(`tests/test_vocaljoystick_formants.py` pins all three). The registry and `docs/v2-features.md`
now say so.
