# ADR-v2-066 — Spoken Regex Builder

**Status:** Accepted (2026-07-02) · Wave I
**Context links:** [[adr-v2-029-spoken-code-mode]] (literal code vs a search pattern), [[adr-v2-030-spoken-math-latex]], [[adr-011]]

## Context

Wave I research (#9) — build regexes/search patterns by voice for developers who can't type
fluently: "four digits dash two digits" → `\d{4}-\d{2}`, "lines starting with a capital letter" →
`^[A-Z]`, "one or more digits" → `\d+`. Feeds find dialogs, `grep`, editor search. Distinct from
Spoken Code Mode (dictates literal code) and Math→LaTeX (equations).

## Decision

Add an opt-in **Spoken Regex Builder**: `[spokenregex] enabled=false`. The pure core
`nl_to_regex(text)` is a compositional grammar: number-word + unit → `{N}` quantifier
(`\d`, `[A-Za-z]`, `[A-Z]`, `\w`, `\s`), literal words (`dash`, `dot`, `slash`, `at sign`, …),
`one or more`/`zero or more`/`optional` → `+`/`*`/`?` on the following atom, and a
`starting with` prefix → `^`. Returns `None` when nothing parses. Dependency-free. An optional
local model for free-form descriptions is deferred. OFF by default.

## Consequences

- Hands-free pattern authoring; pure grammar, no model, deterministic and inspectable.
- Distinct from Code Mode / Math (search pattern, not literal code/equation).
- Privacy (ADR-011): fully local; patterns never leave the machine.
- Caveat: covers a bounded phrase grammar (counts, atoms, quantifiers, anchors) → free-form
  English deferred to the optional model tier; off by default.
