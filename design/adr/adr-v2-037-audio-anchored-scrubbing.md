# ADR-v2-037 — Audio-Anchored Scrubbing

**Status:** Accepted (2026-07-02) · Wave F
**Context links:** [[adr-v2-003-spoken-edit-mode]] (text edit), Punch-In (blind re-record), [[adr-011]], [[adr-012-self-improvement-loop]]

## Context

The Wave F research (#3) proposes keeping word-level timestamps with each dictation so the
user can "replay what I said" or pick a word to hear that exact audio slice and re-dictate
just that word. faster-whisper `word_timestamps=True` (already used on the prosody/confidence
path) and sounddevice playback (already a dep) make this dependency-free. Distinct from Spoken
Edit (text editing) and Punch-In (blind re-record) — this is *word→audio alignment* for
verification and pinpoint correction.

## Decision

Add an opt-in **Audio-Anchored Scrubbing**: `[scrub] enabled=false`. The pure core indexes
timed words and resolves selections: `find_word(words, query)` (last word matching a spoken
target), `slice_bounds(words, i)` and `range_bounds(words, i, j)` (audio start/end for a word
or span). Playback and re-dictation reuse existing sounddevice + the correction path. The
audio slice is held in RAM for the session; it is persisted only if `[learning] capture_audio`
is already on (encrypted, ADR-012). OFF by default.

## Consequences

- Ship-now with **no new dependency** — word-timestamp index + slice selection is pure.
- Distinct from Spoken Edit / Punch-In — verification + pinpoint audio correction.
- Privacy (ADR-011/012): audio slice in RAM only; persisted only under the existing encrypted
  opt-in.
- Caveat: alignment quality is bounded by Whisper's word timestamps → best-effort, off by default.
