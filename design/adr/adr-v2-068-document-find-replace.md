# ADR-v2-068 — Voice-Driven Document-Wide Find-and-Replace

**Status:** Accepted (2026-07-02) · Wave I
**Context links:** [[adr-v2-035-spoken-edit]] (last utterance vs whole document), [[adr-v2-046-smart-paste]], [[adr-011]]

## Context

Wave I research (#5) — edit the whole document by voice, not just the last utterance: "replace
every 'utilise' with 'use'". Recognizes global find/replace with scope (all/first) and
case-sensitivity, then executes against the target via the accessibility text interface (AT-SPI2
`EditableText` on Linux) or the app's find dialog. Distinct from Spoken Edit / Scratch, which
operate only on the *last utterance*.

## Decision

Add an opt-in **Document Find-and-Replace**: `[findreplace] enabled=false`. Two pure cores:
`parse_replace_command(text)` → a `ReplaceOp(find, replace, all, case_sensitive)` from
replace/change/substitute/swap phrasings (scope words "every/all" vs "first/next", a trailing
"case sensitive" flag), and `apply_replace(op, text)` performs it (used for previews/tests).
Dependency-free. The AT-SPI text-range editing backend is deferred. OFF by default.

## Consequences

- Document-scope editing by voice — impossible in a cloud tool (needs local UI/text access).
- Pure parse + apply → fully testable without a live editor.
- Privacy (ADR-011): parsing and preview are local; the backend uses the OS accessibility API, no
  network.
- Caveat: literal (escaped) find only in the pure core → regex/fuzzy replace is a later tier; the
  gate is off by default.
