# ADR-v2-044 — Two-Way Live Interpreter

**Status:** Accepted (2026-07-02) · Wave F
**Context links:** [[adr-v2-014-live-translation]] (one-way sibling), [[adr-v2-039-acoustic-profiles]] (polyglot pair), [[adr-011]]

## Context

The Wave F research (#10) proposes a face-to-face interpreter mode: two speakers of different
languages take turns; YazSes detects each turn's language and translates into the other,
speaking or displaying the result. Anchors: SeamlessM4T v2 / Meta's on-device speech-to-speech,
Whisper `translate` (already wired for Live Translation, ADR-v2-014), the existing TTS path.
Distinct from Live Translation (one-way dictation→English) — this alternates direction per turn.

## Decision

Add an opt-in **Two-Way Live Interpreter**: `[interpret] enabled=false, pair="en-es"`. The pure
core routes turns: `parse_pair("en-es")` → `("en","es")`, and `route_turn(detected_lang, pair)`
returns the `(source, target)` direction for a turn (or None when the detected language is
outside the pair). The heavy S2S/translation model reuses the Whisper `translate` path + TTS,
lazy-loaded. OFF by default.

## Consequences

- Extends one-way translation into alternating two-way interpreting; reuses translate + TTS.
- Pure pair-parsing/turn-routing → fully testable with no model.
- Privacy (ADR-011): fully offline; nothing leaves the machine.
- Caveat: LID errors misroute a turn → route only within the configured pair, None otherwise;
  off by default.
