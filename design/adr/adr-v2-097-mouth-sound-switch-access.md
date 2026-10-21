# ADR-v2-097 — Mouth-Sound Switch Access (non-verbal acoustic switches + scanning)

**Status:** Accepted (2026-07-02) · Wave L
**Context links:** wakeword, cmdspotter (few-shot commands), continuum (accessibility), [[adr-011]]

## Context

Wave L research (#2) — map short non-speech mouth sounds (pop, click, tongue-cluck, "sh") to
discrete switches that drive a **scanning selector**: "pop" = advance the highlight, "cluck" = select.
Distinct from Wake-Word, Few-Shot Command Spotter, and Gesture Chords: this is the **switch-scanning
AAC paradigm** (1–2 signals + a timed scan cursor), the standard access method for people who cannot
produce reliable speech at all. Nothing in the set implements scan-and-select. Anchor: Apple *Sound
Actions for Switch Control / AssistiveTouch* (iOS 15, 2021) — ships exactly this (click, cluck, "e",
"k", "pop", "sh"…) for non-speaking users with limited mobility.

## Decision

Add an opt-in **Mouth-Sound Switch Access**: `[mouthswitch] enabled=false, dwell_s=1.2`. Pure cores
in `mouthswitch/scan.py`: `classify_mouth_sound(features)` → `pop` | `click` | `sh` | `None` from
onset/spectral features, and `ScanSelector` — a pure timed state machine (`tick(now)` auto-advances
the highlight on a fixed dwell; `on_switch("advance"|"select", now)` moves or returns the chosen
item). The acoustic classifier is the lazy audio extra; the scan cursor + dwell timing (the
accessibility-critical part) is pure and testable with a fake clock. OFF by default.

## Consequences

- The switch-scanning access method for non-speaking, severely motor-impaired users.
- Pure scan cursor + debounce/dwell → fully testable with a fake clock.
- Distinct from wake-word/command-spotter (scan-and-select vs recognition).
- Privacy (ADR-011): local audio only.
- Caveat: single/dual-switch scanning is slower than speech (inherent to the paradigm); off by
  default.

## Implementation status (2026-10-21, WIRE-MOUTHSWITCH-001, #164)

**Still unwired.** `mouthswitch` remains in `_UNWIRED` in `system/features.py`; nothing in the
daemon constructs any of the code below, so `[mouthswitch] enabled = true` changes nothing yet.

- **Done — the producer.** `classify_mouth_sound` took `duration_ms` / `centroid_hz` / `zcr` /
  `burst` and nothing computed them. `mouthswitch/detect.py` now does, with numpy only (no
  extra, so nothing to skip on FreeBSD): `MouthSoundDetector.feed(chunk)` takes an idle audio
  stream in chunks of any size, finds isolated energy onsets against an adaptive noise floor,
  measures the four features (plus spectral flatness and a YIN voiced share from
  `audio/pitch.py`, as diagnostics and a guard), asks the existing classifier, and returns
  `MouthSoundEvent`s whose `action` is the ADR's mapping: `pop` → `advance`, `click` →
  `select`. `sh` is recognised but **unmapped by default** (a sustained hiss is the kind most
  easily confused with room noise); a caller opts it in by passing `actions=`. The classifier
  in `scan.py` is unchanged.
- **Guards (rule 9).** An event is emitted only when every specific check holds: ≥150 ms of
  quiet before the onset and after the sound; ≤500 ms long; unvoiced (≤25 % of 40 ms frames
  pitched *and* fewer than 2 pitched frames); fewer than 2 pitched frames in the 400 ms before
  the onset; classified; and outside a 300 ms refractory window. Two of these were added
  because the synthetic speech stand-in produced a false fire without them (a stop release
  just after a word; a long "sh" glued to a short quiet vowel).
- **Measured, synthetic only** (`tests/test_mouthswitch_detect.py` generators, 2026-10-21):
  0 events in 30 min of the speech stand-in (60 seeds × 30 s — voiced syllables with F0
  glides, plosive and fricative onsets, word-final stop releases, pauses); 0 events in 10 min
  of steady and amplitude-modulated noise at five levels (3e-4 to 3e-2 RMS); recall 40/40 for
  each of click, pop and sh over amplitudes 0.3×–2× and 10 seeds, no wrong kinds. The suite
  holds the 2-minute subset to zero. **Not measured:** real recorded mouth sounds, real speech,
  and the false-fire source most likely to dominate in practice — keyboard taps, mic bumps and
  desk knocks, which are impulses and will read as `click`.
- **Not done (wiring).** (1) An idle microphone stream: the daemon has none — today's
  `_on_audio_chunk` runs only while recording — so the detector needs its own
  `sounddevice` input opened while `[mouthswitch] enabled` and closed otherwise, feeding
  `MouthSoundDetector.feed`. (2) The scan-item UI: what `ScanSelector` scans (a phrase board,
  keys, tray menu) and how the highlight is shown (overlay). (3) Config keys for the action
  mapping / `sh` opt-in and sensitivity, in `config.py` plus regenerated docs. (4) Removing
  `mouthswitch` from `_UNWIRED` once (1)–(2) reach the daemon.
