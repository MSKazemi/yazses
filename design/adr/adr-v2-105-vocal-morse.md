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
