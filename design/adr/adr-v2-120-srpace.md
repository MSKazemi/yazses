# ADR-v2-120 — SRPace (screen-reader-paced injection)

**Status:** Accepted (2026-07-03) · Wave N
**Context links:** srpace↔brailleout (accessibility output), continuum, injection, [[adr-011]]

## Context

Wave N research (#6) — injecting a whole dictated paragraph as one burst floods a screen reader:
it either announces a wall of text at once or re-reads on every keystroke, so a blind user loses
the thread. Pacing injection to the reader's own words-per-minute rate, chunked at clause
boundaries, lets the screen reader announce each piece coherently. Nothing in the set controls
injection *timing* for assistive output. Anchor: screen-reader comprehensibility research.

## Decision

Add an opt-in **SRPace**: `[srpace] enabled=false, wpm=180.0`. Pure cores in
`srpace/schedule.py`: `chunk_clauses(text)` splits at sentence/clause punctuation (delimiter kept,
blanks dropped); `plan_injection_schedule(text, wpm, min_chunk_ms)` → `Chunk(text, delay_ms)`
list where each chunk's duration is `words / wpm` (floored at `min_chunk_ms`) and `delay_ms` is
the cumulative start time, so the injector announces chunks in sequence without overrunning the
reader. `wpm ≤ 0` disables pacing (single zero-delay chunk). OFF by default.

## Consequences

- Blind/screen-reader users get coherent, keep-up-able announcement of dictated text.
- Pure chunker + scheduler → fully testable, deterministic, dependency-free.
- Distinct from BrailleOut (output encoding) — this is output *timing*; the two compose.
- Privacy (ADR-011): local text only.
- Caveat: default wpm is a heuristic (users match it to their reader); the injector must honour
  the per-chunk delays; off by default.
