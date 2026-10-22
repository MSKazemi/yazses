# ADR-v2-105 — Vocal Morse (two-tone timing-coded AAC)

**Status:** Accepted (2026-07-02) · Wave M
**Context links:** [[adr-v2-097-mouth-sound-switch-access]] (single event vs symbol alphabet), [[adr-v2-095-vocal-joystick]], [[adr-011]]

## Context

Wave M research (#1) — a user who can produce only two distinguishable vocal sounds (short grunt vs
long hum, or low vs high) emits *timed pulses* decoded to text/commands. Morse needs only two
symbols, so even one reliable vocalization suffices — the lowest-bandwidth input in the whole set.
Every excluded switch-access feature (Mouth-Sound Switch, Vocal Joystick, Breath) is a single-event
trigger or continuous controller; none is a **timing-coded symbol alphabet** that turns one vocal
gesture into full text. Adaptive timing (auto-calibrating dot/dash + gaps to the user's slowing,
fatiguing rhythm) is the studied research edge. Anchor: Google Gboard Morse keyboard (2018, built with
a cerebral-palsy user); *Adaptive Morse code recognition for disabled persons* (ScienceDirect, Math &
Computers in Simulation); ongoing Morse-AAC for ALS/locked-in.

## Decision

Add an opt-in **Vocal Morse**: `[morsevox] enabled=false, dot_max_ms=200, letter_gap_ms=600,
word_gap_ms=1400`. Pure cores in `morsevox/decode.py`: `classify_pulse(duration_ms, calib)` →
`dot`|`dash`, `classify_gap(silence_ms, calib)` → `gap_symbol`|`gap_letter`|`gap_word`, `MorseDecoder`
(feed dot/dash/gap tokens → emit decoded chars at letter/word boundaries via the international Morse
table), and `adapt_dot_threshold(durations, calib)` → an EMA-refit `MorseCalib`. Pulse timing comes
from the existing hold/mouth-sound stream. OFF by default.

## Consequences

- Full text entry from a single reliable vocalization — the highest-ceiling accessibility win here.
- Pure timing classifier + decoder + adaptive calibration → fully testable with synthetic durations.
- Distinct from Mouth-Switch (symbol alphabet vs single trigger).
- Privacy (ADR-011): local timing only.
- Caveat: Morse is slow and has a learning curve (inherent); off by default.

## Implementation status (2026-10-21, WIRE-MORSEVOX-001)

**Still unwired.** `morsevox` remains in `_UNWIRED` in `system/features.py`; nothing in the
daemon constructs any of the code below, so `[morsevox] enabled = true` changes nothing yet.

- **Done — the producer.** The "pulse timing from the existing stream" in the Decision had
  no code behind it. `morsevox/segment.py` now supplies it, pure and dependency-free:
  `PulseSegmenter` turns a `(timestamp_ms, level)` stream — the per-chunk `mean(|samples|)`
  that `daemon._on_audio_chunk` already computes — into pulse and gap durations, with
  hysteresis (`on_level`/`off_level`) and debounce (dropouts under `bridge_ms` are bridged;
  a pulse with under `min_pulse_ms` of voiced time is discarded as a click). `MorseStream`
  feeds those durations through `classify_pulse`/`classify_gap` into `MorseDecoder`, emits a
  letter as soon as the silence reaches `letter_gap_ms` (and a space at `word_gap_ms`), and
  can re-fit `dot_max_ms` with `adapt_dot_threshold` — only once the recent pulses form two
  clusters, so a run of dots cannot drag the threshold into the dots. Tested on synthetic
  level streams in `tests/test_morsevox_segment.py` (including jitter, noise floor, clicks
  and dropouts, each paired with a twin that fails with the guard switched off); the core's
  edges are pinned in `tests/test_morsevox_decode.py`.
- **Undecided — how a minimal-ability user starts and stops it.** `_on_audio_chunk` runs only
  while the recorder is capturing, which today begins in `_on_hold_start` — a hold or toggle
  of a hotkey. The users this ADR is for may be unable to press one. Whether Morse listening
  is latched on by a mouth-sound switch (ADR-v2-097), by a toggle, by an always-listening
  mode while the feature is enabled, or by something else is **not decided**, and neither is
  how it is latched off again. This is a UX decision for the owner, not a wiring detail.
- **Also undecided before wiring:** whether a Morse capture is kept away from speech-to-text
  (otherwise the same hums are transcribed), where `on_level` comes from (the obvious
  source is `accessibility.vad_threshold`, which is the same metric, but it is tuned for
  speech), and whether `adapt` is user-visible. No config keys were added for the
  segmenter's thresholds.
