# ADR-v2-067 — Structured-Markup Dictation

**Status:** Accepted (2026-07-02) · Wave I
**Context links:** [[adr-v2-059-spoken-spreadsheet]] (drives an app vs emits markup), [[adr-v2-057-spoken-temporal-normalizer]], [[adr-011]]

## Context

Wave I research (#7) — speak document structure and get correct Markdown/org markup instead of a
run-on paragraph: "bullet list: apples; oranges; pears" → a bullet list; "table columns Name, Age;
row Alice, 30" → a valid table. Same ITN family as Entity ITN / Temporal Normalizer, applied to
*document structure*. Distinct from Spoken Spreadsheet (drives a cell-grid application) and Code/
Math modes (target code/equations).

## Decision

Add an opt-in **Structured-Markup Dictation**: `[markup] enabled=false`. Two pure cores:
`parse_structure(text)` returns a `Structure(kind, items|columns+rows)` for bullet / numbered /
checklist / table intents, and `render_markup(struct, flavor)` emits Markdown (default) or org.
Dependency-free; an optional LLM only for messy free-form tables is deferred. OFF by default.

## Consequences

- Rule-based, fully local, deterministic markup emission — no model needed for the common shapes.
- Distinct from Spreadsheet (emits text markup vs navigating an app).
- Privacy (ADR-011): pure text transform; nothing leaves the machine.
- Caveat: bounded to explicit "list:"/"table columns…" phrasings → free-form structure deferred
  to the optional model tier; off by default.
