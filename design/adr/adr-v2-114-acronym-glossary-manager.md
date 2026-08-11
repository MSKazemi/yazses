# ADR-v2-114 — Acronym / Glossary First-Use Manager

**Status:** Accepted (2026-07-02) · Wave M
**Context links:** hotwords, itn, spelling, [[adr-v2-109-style-consistency-enforcer]], [[adr-011]]

## Context

Wave M research (#10) — track defined terms in the current document; on first mention expand "World
Health Organization (WHO)", then let the user say "W-H-O" and inject the acronym; and flag an
undefined acronym that was never expanded. Contextual biasing (Hotwords), ITN, and Phonetic Spelling
handle recognition/formatting; none manages **document-scoped acronym state** (define-on-first-use,
later contraction, undefined-acronym warnings). A small, distinct text-intelligence layer. Anchor:
the "define acronyms on first use" convention is a hard rule in scientific/technical/medical style
guides; acronym-consistency checkers exist as static tools (LaTeX `glossaries`/`acro`, journal
checkers) but not in any live dictation flow.

## Decision

Add an opt-in **Acronym/Glossary Manager**: `[acronyms] enabled=false`. Pure core in
`acronyms/glossary.py`: `AcronymState` with `observe(text)` (learn "Full Name (ACR)" definitions
already written), `define(acr, full)` (register a known expansion for first-use), `resolve(term)`
(expand on first use, contract after), and `audit(doc)` → warnings for acronyms used but never
defined. Pure regex/dict; no model. OFF by default.

## Consequences

- Consistent define-on-first-use and undefined-acronym warnings, hands-free.
- Pure state machine → fully testable.
- Distinct from Hotwords/ITN (document-scoped acronym state vs recognition/formatting).
- Privacy (ADR-011): local text only.
- Caveat: heuristic "Full Name (ACR)" detection; off by default.
