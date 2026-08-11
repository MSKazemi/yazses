# ADR-v2-111 — Semantic Line Breaks (version-control-friendly prose)

**Status:** Accepted (2026-07-02) · Wave M
**Context links:** reflow (on-screen wrapping), markup, [[adr-v2-104-prosodic-auto-punctuation]], [[adr-011]]

## Context

Wave M research (#7) — in Markdown/LaTeX/AsciiDoc files, dictated prose broken **one clause/thought
per source line** keeps git diffs and merges clean (rendered output is unchanged). Dictation Reflow
targets on-screen wrapping/readability; semantic line breaks target **source-diff granularity** for
VCS — an orthogonal, spec'd convention not present in the set. Anchor: Semantic Line Breaks
Specification (sembr.org); "ventilated prose" (Fuller; popularized via Kernighan's *UNIX for
Beginners*, 1974) — breaking after sentence and major-clause boundaries reduces merge conflicts.

## Decision

Add an opt-in **Semantic Line Breaks**: `[sembr] enabled=false`. Pure core in `sembr/breaks.py`:
`semantic_breaks(text, max_len=None)` inserts a newline after sentence terminators (`. ! ?`), after
`;`/`:`, and before a coordinating conjunction/clause word that follows a comma; an optional
`max_len` soft-wraps any still-too-long line at a space. Pure regex/string transformation; no model.
OFF by default.

## Consequences

- Clean line-granular diffs/merges for prose versioned in git, without hand-reformatting.
- Pure string transformation → fully testable.
- Distinct from Reflow (source-diff vs on-screen wrapping).
- Privacy (ADR-011): local text only.
- Caveat: rule-based clause detection (a parser is a later tier); off by default.
