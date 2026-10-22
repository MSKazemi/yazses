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

## Implementation status (2026-10-22, WIRE-MORSEVOX-001) — wired, experimental

**Wired, off by default, untested on a real voice.** `morsevox` is out of `_UNWIRED`. The
owner answered the open questions below on 2026-10-22:

- **Start, hands-free.** Either the spoken command "morse mode" (whole utterance, the voice
  stop word's matching rule, checked right after the stop word in `_on_hold_end`, so it is
  heard through the ordinary dictation path and never typed), or a **long steady hum**:
  `[morsevox] entry_hum_s` (default 1.5 s) of one unbroken tone above the voice threshold
  whose level coefficient of variation is at most 0.25. Per ADR-021 the trigger is a
  specific, checkable signal: speech dips below the threshold between syllables or words
  (rule 1), and running speech that does not dip is amplitude-modulated at the syllable
  rate (rule 2). A continuous sound fires it at most once. `entry_hum_s = 0` disables it.
- **Stop.** `[morsevox] exit_silence_s` (default 3 s) with no accepted pulse, raised above
  the word gap if set at or below it. The decoder defines no stop/cancel prosign, so there
  is no exit sequence. A hold-to-talk recording, `yazses handsfree pause` (and the spoken
  stop phrase), a pause of the hands-free gate, and shutdown also end it.
- **Kept away from STT.** Morse mode reads its own level-only stream
  (`morsevox/runtime.py`); no audio sample is kept and speech-to-text is never invoked.
  Decoded characters go through the daemon's normal injector.
- **Listening.** With the hum entry on, that stream is open while the daemon runs — the
  microphone indicator stays on — because a user who cannot press a key must be heard to
  start. With `entry_hum_s = 0` it opens only when "morse mode" enters and closes when
  the mode ends.
- **`on_level`** is `[accessibility] vad_threshold`, read at start; `off_level` is 0.6 × that.
  It is tuned for speech, not hums — the first thing a real-voice test should check.
- **`adapt`** is on and not user-visible: the dot/dash threshold refits once the recent
  pulses form two clusters.
- **Visible state.** `status` gains a `morse` block (flags and a count, never text);
  `yazses status` prints a `morse:` line; the overlay draws its rings while Morse mode is
  on; entering and leaving play the recording earcons and post a notification.

The pure state machine is `morsevox/mode.py`, tested in `tests/test_morsevox_mode.py`;
the runtime in `tests/test_morsevox_runtime.py`; the daemon glue in
`tests/test_morsevox_wiring.py`. **Every threshold is synthetic-only** — the steadiness
limit, the 1.5 s hum and the 3 s exit need measuring with the people this is for (#255).

## Implementation status (2026-10-21, WIRE-MORSEVOX-001) — superseded above

**Still unwired** (at that date). `morsevox` remains in `_UNWIRED` in `system/features.py`; nothing in the
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
