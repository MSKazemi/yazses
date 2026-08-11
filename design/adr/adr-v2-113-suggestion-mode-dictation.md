# ADR-v2-113 — Suggestion-Mode Dictation (CriticMarkup tracked changes)

**Status:** Accepted (2026-07-02) · Wave M
**Context links:** spoken-edit (in-place mutation), redaction, [[adr-v2-111-semantic-line-breaks]], [[adr-011]]

## Context

Wave M research (#9) — in "suggestion mode", dictated edits are emitted as **CriticMarkup**
(`{++insert++}`, `{--delete--}`, `{~~old~>new~~}`, `{>>comment<<}`) instead of being applied, so an
editor can review/accept later — voice-driven collaborative editing. Spoken Edit Mode mutates text
in place; Redaction Ink masks it. Producing **non-destructive tracked suggestions** in a plain-text
change syntax is a distinct collaborative-editing mode absent from the set. Anchor: CriticMarkup spec
(criticmarkup.com; MultiMarkdown) — explicit add/delete/substitute/comment syntax with an established
"suggest mode" (Obsidian, Emacs); Google Docs "Suggesting" as the UX analog.

## Decision

Add an opt-in **Suggestion-Mode Dictation**: `[suggestmode] enabled=false`. Pure cores in
`suggestmode/critic.py`: `to_criticmarkup(kind, ...)` → the markup for an insert/delete/substitute/
comment, and `diff_to_critic(before, after)` → a word-level CriticMarkup diff (via stdlib
`difflib`). Pure; no third-party dependency. OFF by default.

## Consequences

- Non-destructive, reviewable voice edits for copyeditors/reviewers/teachers.
- Pure diff/markup → fully testable.
- Distinct from Spoken Edit (tracked suggestion vs in-place mutation).
- Privacy (ADR-011): local text only.
- Caveat: word-granularity diff (character-level is a later tier); off by default.
