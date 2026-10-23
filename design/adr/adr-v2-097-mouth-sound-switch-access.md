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

## Wiring (2026-10-22, WIRE-MOUTHSWITCH-001, #164) — untested on real hardware

**Wired; experimental; off by default.** `mouthswitch` is no longer in `_UNWIRED`. Owner
decision (2026-10-22): **single-switch scanning**, not the pop-advance / cluck-select pair
above. The mapping the runtime passes to the detector is `pop` → `toggle`, `click` → `select`;
`sh` stays unmapped.

- **Scan items and timing** — `mouthswitch/scanner.py`, pure, every method takes `now`.
  `SwitchScanner` lights item `floor((t - start) / dwell_s) mod n`; a pop starts or stops the
  scan; a click selects the item lit **at the click's onset**, not at the moment the detector
  reports it (≥150 ms later). Each scan selects at most once, then stops. A click outside the
  scan, or reported more than 2 s after its onset, selects nothing. A scan stops by itself
  after three passes. `dwell_s` is clamped to 0.5–10 s.
- **Items** — new key `[mouthswitch] scan_items`, default `enter, undo, scroll up, scroll
  down, click`. A command item is a phrase that must classify in the existing grammar
  *and* be in the activation policy's reversible set. Otherwise the policy would ask for a
  confirmation that a single switch cannot give, so the item is dropped at build time with
  a log line. `click` / `scroll up` / `scroll down` are one call each on the platform's
  existing `PointerSink` (`click(LEFT)`, `scroll(0, ∓3)`), offered only if the backend can
  do them. No new action exists.
- **Runtime** — `mouthswitch/runtime.py`, modelled on `vocaljoystick/runtime.py`: the
  runner's own `AudioRecorder` stream (wiring item (1) above), opened by `yazses handsfree
  resume` and closed by `handsfree pause`, the stop phrase, a pause of the global gate
  (read-only) and shutdown. Chunks are dropped, the detector reset and the scan stopped
  while dictation is busy. A selected command runs through
  `activation/pipeline.handle_intent` → `commands.grammar.classify` → `commands.dispatch`
  (the Gesture Chords path, with the no-echo injector).
- **Highlight** — the overlay draws a click-through strip (`overlay/scanstrip.py` pure layout,
  `overlay/scan_widget.py` Qt). It reads the scan from a new `mouthswitch` block in the
  existing `status` reply, which it already polls, and it polls fast (50 ms) while a scan
  runs. **No new IPC method.** Without the overlay (`[overlay]` off, no `desktop` extra, or a
  native Wayland session, where the overlay is not started) the runtime refuses to build,
  and `handsfree resume` reports why. A switch must never select an item nobody can see.
- **Still not done:** sensitivity / mapping config keys (item (3) above); an earcon or
  spoken cue for auditory scanning; any measurement on recorded mouth sounds, keyboard taps or
  desk knocks. All thresholds remain synthetic-only.

### Amendment (2026-10-23, owner-approved; written untested in code-only wave 5)

Two changes to the wiring above. The bullets above are kept as the record of what shipped
in 2.44.0.

- **Auditory scanning where the overlay will not run.** The "no overlay, no switch" rule
  becomes "seen or heard, never neither". Without the overlay, `mouthswitch/announce.py`
  announces each step with the earcon player (`scan_step`, and `scan_first` on the first
  item) when `[earcon]` is on, and speaks the item's label in the read-back voice when
  `[tts]` is on and not degraded to the null backend. With neither, the runtime still
  refuses. `SwitchScanner` takes an injected announcement duration and holds an item lit
  for `max(dwell_s, duration)`, so the highlight never advances mid-word. Announcements read
  the same timeline the select-at-onset rule reads. The spoken-duration estimate is
  provisional, and speaker output reaching the scan microphone is unmeasured.
- **A selection no longer ends the scan.** It re-anchors the timeline on the selected item
  at the moment of selection: that item stays lit for a full dwell, then the scan steps on.
  The inactivity stop counts three passes from the last selection. "Each scan selects at
  most once" becomes "each click selects at most once": a click whose onset is not later
  than the last selection's selects nothing. The stale-click guard (2 s) is unchanged. The
  trade-off against ADR-021: a stray click-like sound can now run an item while a scan the
  user has already used is still running. The scan still stops on a pop, so the user ends it.

### Before the wiring (2026-10-21)

**Unwired then.** `mouthswitch` was in `_UNWIRED` in `system/features.py`; nothing in the
daemon constructed any of the code below.

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
  holds the 2-minute subset to zero.
- **Noise-floor step (fixed 2026-10-21, review finding).** The floor was updated from quiet
  frames only, so a background step of more than 3× (a fan switching on, or a stream that opens
  with digital zeros, which seed the floor at 1e-5) made every frame "sounding" and the
  detector went deaf for good, silently: the recall above covered only streams already at the
  noise level from the first sample. After `FLOOR_RESEED_MS` (1 s) with no floor update the
  floor is now re-seeded from the quietest 5 ms frame of that window — every frame there
  sounded, so the re-seed can only raise the floor. Sounds in the first ~1 s after the step are
  still missed. Re-measured after the fix with the same generators (my own reconstruction of
  the harness, not the original script): 0 events over the 60 × 30 s speech stand-in; 0 over
  10 min of steady and modulated noise at the five levels; 0 over 20 step-only streams (zeros,
  then steps of 2×–100×); click, pop and sh each 40/40 with no wrong kinds. After a 4× step,
  click and pop are detected; after a 10× step only the click is, exactly as over steady noise
  at that level (the pop is then under the onset level). **Not measured:** real recorded mouth sounds, real speech,
  and the false-fire source most likely to dominate in practice — keyboard taps, mic bumps and
  desk knocks, which are impulses and will read as `click`.
- **Not done (wiring).** (1) An idle microphone stream: the daemon has none — today's
  `_on_audio_chunk` runs only while recording — so the detector needs its own
  `sounddevice` input opened while `[mouthswitch] enabled` and closed otherwise, feeding
  `MouthSoundDetector.feed`. (2) The scan-item UI: what `ScanSelector` scans (a phrase board,
  keys, tray menu) and how the highlight is shown (overlay). (3) Config keys for the action
  mapping / `sh` opt-in and sensitivity, in `config.py` plus regenerated docs. (4) Removing
  `mouthswitch` from `_UNWIRED` once (1)–(2) reach the daemon.
