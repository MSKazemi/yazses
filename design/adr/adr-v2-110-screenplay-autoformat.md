# ADR-v2-110 — Screenplay & Dialogue Auto-Format (Fountain)

**Status:** Accepted (2026-07-02) · Wave M
**Context links:** markup (generic Markdown), [[adr-v2-111-semantic-line-breaks]], [[adr-011]]

## Context

Wave M research (#6) — dictating "scene: interior coffee shop, day … Maya (character) quote where
were you unquote" auto-emits correctly structured **Fountain** (scene headings, character cues,
parentheticals, smart curly quotes, blank-line separation). Structured-Markup Dictation handles
generic Markdown/headings; no excluded feature knows the **screenplay/dialogue grammar** (speaker
turns, cues, transitions) or does smart-quote dialogue attribution. A new output-formatting domain.
Anchor: Fountain plain-text screenwriting markup (fountain.io) — "indistinguishable from Final Draft
when exported", Markdown-inspired and text-editor-native, so a formatter core is pure string
transformation.

## Decision

Add an opt-in **Screenplay Auto-Format**: `[screenplay] enabled=false`. Pure cores in
`screenplay/fountain.py`: `to_fountain(utterance)` (detect scene heading → `INT./EXT. LOCATION -
DAY`, "NAME (character) …" → an uppercased cue + dialogue, "transition: cut to" → `CUT TO:`, else an
action line) and `smart_quote_dialogue(text)` (spoken "quote/unquote" and straight `"…"` → curly
quotes). Pure regex/string transformation; no model. OFF by default.

## Consequences

- Hands-free screenplay authoring in a standard, portable plain-text format.
- Pure transformation → fully testable.
- Distinct from Structured-Markup (screenplay grammar vs generic Markdown).
- Privacy (ADR-011): local text only.
- Caveat: heuristic element detection (a full parser is a later tier); off by default.
