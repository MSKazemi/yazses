# ADR-v2-108 — Interruptible Read-Back Proofreading (barge-in alignment)

**Status:** Accepted (2026-07-02) · Wave M
**Context links:** [[project_readback_loop]] (playback only), spoken-edit, [[adr-011]]

## Context

Wave M research (#4) — the draft is read aloud (TTS); the moment the user speaks ("stop — change
that to…"), the system maps the barge-in *timestamp* to the exact word being spoken and drops the
edit cursor there. Read-Back only *plays*; Spoken Edit edits whatever is current. The new primitive
is **time→word-index alignment of a barge-in during playback** — hearing-driven eyes-free
proofreading, which the excluded set lacks. Anchor: barge-in is a studied spoken-dialogue capability
(Interspeech/ICASSP); "hearing mistakes is easier than seeing them" is the canonical dyslexia-TTS
finding.

## Decision

Add an opt-in **Interruptible Read-Back Proofreading**: `[proofback] enabled=false`. Pure cores in
`proofback/align.py`: `build_schedule(words, per_word_ms)` → a cumulative `[Span(index, start_ms,
end_ms)]` playback timeline, `word_at(schedule, t_ms)` → the word index at a barge-in timestamp
(clamped to the ends), and `resolve_target(index, intent)` → the edit target. Pure arithmetic; the
TTS/barge-in capture is the existing infra. OFF by default.

## Consequences

- Eyes-free proofreading: interrupt the read-back and land the cursor on the exact word.
- Pure timeline/alignment → fully testable.
- Distinct from Read-Back (alignment vs playback) and Spoken Edit (barge-in-located vs current).
- Privacy (ADR-011): local audio/text only.
- Caveat: fixed/estimated per-word durations (true forced alignment is a later tier); off by default.
