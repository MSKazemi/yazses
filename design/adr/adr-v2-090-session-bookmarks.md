# ADR-v2-090 — Session Bookmarks & Resume

**Status:** Accepted (2026-07-02) · Wave K
**Context links:** [[adr-v2-089-voice-undo-redo-timeline]] (positions build on the timeline), [[adr-v2-020-voice-grounded-rag]] (recall content vs positions), [[adr-011]]

## Context

Wave K research (#8) — drop named anchors in a long dictation session and re-navigate/resume after
interruption or fatigue; anchors map to injection-timeline positions (builds on #3). Distinct from
Spoken Recall & Scratch (which recalls *content*, not *positions*). An accessibility win for
fatigue/interruption (RSI, cognitive load). Anchor: eyes-free voice text-editing / navigation
research (VoiceRev, "Just Speak It" UIST).

## Decision

Add an opt-in **Session Bookmarks**: `[bookmarks] enabled=false`. Pure cores: `BookmarkStore`
(add/goto/names/last, insertion-ordered), and `parse_bookmark_command(text)` → `("add", name|None)`
or `("goto", name|None)` (None on goto = the most recent bookmark), recognizing "bookmark here [as
X]" and "jump to [my last] bookmark [X]". Dependency-free, in-memory. OFF by default.

## Consequences

- Voice checkpoints/resume in long sessions; a fatigue/interruption accessibility win.
- Pure store + command grammar → fully testable.
- Distinct from Spoken Recall (positions vs content).
- Privacy (ADR-011): in-memory local labels only.
- Caveat: positions are session-scoped and in-memory (cleared on stop); off by default.
