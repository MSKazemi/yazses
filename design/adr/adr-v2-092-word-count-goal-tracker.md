# ADR-v2-092 — Word-Count & Writing-Goal Tracker

**Status:** Accepted (2026-07-02) · Wave K
**Context links:** [[adr-v2-042-speaking-coach]] (session analytics), [[project_readback_loop]] (spoken answer), [[adr-011]]

## Context

Wave K research (#9) — count YazSes-injected words this session, set a goal ("goal 500 words"), and
answer spoken progress queries by read-back — for writers who can't glance at a word-counter. No
counting/goal surface exists in the current set; the spoken answer reuses Read-Back. A genuine
eyes-free accessibility utility. Anchor: eyes-free editing / read-back line of research (Google
Dictation editing commands; "Just Speak It," UIST).

## Decision

Add an opt-in **Word-Count/Goal Tracker**: `[wordgoal] enabled=false, goal=0`. Pure cores:
`count_words(text)`, `WordGoalTracker` (accumulate injected tokens, `set_goal`, `count`, `reset`,
and `progress()` → a spoken-ready string with or without a goal), and `parse_goal_command(text)` →
an int goal from "goal 500 words" / "set my goal to 500". Dependency-free; the spoken answer reuses
the existing TTS. OFF by default.

## Consequences

- Eyes-free word-count and goal progress; pure counters.
- Reuses Read-Back only for the answer.
- Privacy (ADR-011): local counters only.
- Caveat: counts YazSes-injected words (not edits made elsewhere); off by default.
