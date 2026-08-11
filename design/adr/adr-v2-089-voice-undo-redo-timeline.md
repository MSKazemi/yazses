# ADR-v2-089 — Voice Undo/Redo Timeline

**Status:** Accepted (2026-07-02) · Wave K
**Context links:** [[adr-v2-035-spoken-edit]] (within-utterance vs across-bursts), [[adr-v2-058-mid-utterance-self-repair]], [[adr-011]]

## Context

Wave K research (#3) — a persistent ring of YazSes's *own* injection events (text + delta) so you
can undo/redo its output across bursts by voice ("undo the last sentence", "redo", "go back before
I said X") — including apps with no reliable Ctrl+Z. Distinct from Spoken Edit / Mid-Utterance
Self-Repair, which operate *within* an utterance; app Ctrl+Z is app-dependent and one-level for
voice. This is a YazSes-owned, multi-step, semantic (last word / last sentence / last burst)
injection history — impossible for a cloud tool that doesn't track your local injections. Anchor:
VoiceRev / "Commanding and Re-Dictation" (ACM TOCHI). The highest-leverage core (also unlocks #8
bookmarks).

## Decision

Add an opt-in **Voice Undo/Redo Timeline**: `[timeline] enabled=false`. The pure core
`InjectionTimeline` records each injection and computes an `UndoOp(backspaces, insert)`: `undo(scope)`
reverses the last word / sentence / burst (removing trailing chars from the most recent event) and
pushes the removed fragment onto a redo stack; `redo()` re-inserts it; `record()` clears the redo
stack. Dependency-free, in-memory. OFF by default.

## Consequences

- Multi-step semantic undo/redo of YazSes output, even where app Ctrl+Z is unreliable.
- Pure list logic → fully testable; reuses the existing injector for the backspace/retype.
- Distinct from Spoken Edit (across-bursts vs within-utterance).
- Privacy (ADR-011): in-memory local history, cleared on daemon stop; never persisted or sent.
- Caveat: word/sentence scoping operates on the most recent event (not a full document model); off
  by default.
