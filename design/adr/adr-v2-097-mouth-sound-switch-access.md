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
