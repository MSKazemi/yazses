# ADR-v2-088 — Auto-Pairing & Wrap-Selection for Code Dictation

**Status:** Accepted (2026-07-02) · Wave K
**Context links:** [[adr-v2-029-spoken-code-mode]] (literal symbols vs balancing), [[adr-v2-067-structured-markup-dictation]], [[adr-011]]

## Context

Wave K research (#5) — when dictating code, auto-close and balance `() [] {} "" '' `` ` and support
"wrap this in parens". Prevents the classic voice-coding unbalanced-delimiter failure. Distinct from
Spoken Code Mode (transcribes symbols literally) and Structured-Markup (prose markup) — this adds
*balancing/wrapping* semantics literal dictation lacks. Anchor: Serenade enclosure handling (a
documented pain point), Cursorless "wrap".

## Decision

Add an opt-in **Auto-Pairing & Wrap**: `[autopair] enabled=false`. Pure cores:
`balance_delimiters(text)` appends the missing closers for unbalanced brackets (stack-tracked) and
odd quotes; `wrap(selection, pair)` wraps a selection in a named pair (parens/brackets/braces/
quotes/backticks/angle); `detect_wrap_command(text)` parses "wrap this in …". Dependency-free. OFF
by default.

## Consequences

- Balanced delimiters and wrap-selection for voice coding; pure string ops.
- Distinct from Spoken Code Mode (balancing vs literal symbols).
- Privacy (ADR-011): pure local text transform.
- Caveat: balancing is bracket/quote counting (not full-syntax aware) → a heuristic aid; off by
  default.
