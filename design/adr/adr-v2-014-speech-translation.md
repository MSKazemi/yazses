# ADR-v2-014 — Real-time Offline Speech Translation

**Status:** Accepted (2026-07-02) · Wave D
**Context links:** [[adr-v2-000-interaction-layer]], [[adr-v2-008-code-switch]] (distinct: keep-native vs translate), [[adr-011]]

## Context

The Wave D research (the Wave d research note (internal) #2) notes that Whisper
already carries X→English translation latently via `task=translate` (zero new deps), and
Meta SeamlessM4T v2 (arXiv 2312.05187) offers N-to-M. This is distinct from Code-Switch
routing (ADR-v2-008), which keeps each span in its own language; translation emits the
*other* language. No offline, privacy-first dictation tool ships translate-as-you-dictate.

## Decision

Add an opt-in **translate mode**: `[translate] enabled`, `target` (default `en`),
`backend` (`whisper` X→English, zero-dep, default | `seamless` N-to-M behind an extra).
The daemon passes `task="translate"` to faster-whisper when the whisper backend + target
`en` are set; Seamless is lazy behind a `[translate]` extra and dormant until installed.
Pure config/decision layer decides *whether* to translate and *which* backend; the STT
call carries the task. OFF by default.

## Consequences

- X→English works immediately with the existing model (no download, no new dep).
- Full N-to-M is gated behind an explicit heavy opt-in; faster-whisper stays the default.
- Honours ADR-011: translation is on-device; nothing leaves the machine.
- Caveat: Whisper translate is X→English only; other targets require the Seamless backend.
