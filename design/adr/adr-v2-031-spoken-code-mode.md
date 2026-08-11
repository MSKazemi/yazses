# ADR-v2-031 — Spoken Code Mode

**Status:** Accepted (2026-07-02) · Wave E
**Context links:** [[adr-v2-004-context-primed]] (biases prior, not syntax), [[adr-v2-006-spoken-mcp]] (runs tools), [[adr-011]]

## Context

The Wave E research (#6) proposes syntax-aware programming by voice — spoken symbols and
identifier casing ("snake user I d" → `user_id`) — the Talon/Serenade/Cursorless paradigm.
Context-Primed dictation only feeds LSP context into `initial_prompt`; Voice-to-Tool runs MCP
actions. Neither produces code *text*, so this is a distinct output grammar.

## Decision

Add an opt-in **Spoken Code Mode**: `[code] enabled=false`. Two pure cores:
`spoken_symbols(text)` maps spoken symbol phrases to punctuation (longest-match: "open paren"
→ `(`, "arrow" → `->`, "equals" → `=`, …), and `to_case(words, style)` joins words into an
identifier in `camel` / `snake` / `pascal` / `constant` / `kebab` style. These compose on the
command path; the LSP identifier completion (via the existing `NeovimBridge`) is a deferred
enhancement. OFF by default.

## Consequences

- Distinct output grammar (code text) — neither prior-biasing nor tool-running.
- Both cores pure → fully testable with no model; activatable via a dedicated command key.
- On-device only (ADR-011); pure string transforms.
- Caveat: symbol phrases overlap ordinary words → active only in code mode, off by default.
