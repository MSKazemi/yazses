# ADR-v2-087 — Voice Case & Identifier Transform on Selection

**Status:** Accepted (2026-07-02) · Wave K
**Context links:** [[adr-v2-029-spoken-code-mode]] (dictates new vs transforms existing), [[adr-v2-046-smart-paste]], [[adr-011]]

## Context

Wave K research (#4) — "make this snake_case / Title Case / SHOUT / camelCase" over the current
selection (clipboard): apply a case/identifier transform and paste back. Covers upper/lower/title/
sentence + programmer cases (snake, kebab, camel, Pascal, CONSTANT). Distinct from Spoken Code Mode
(dictates *new* code) — this *transforms existing selected* text, which needs local clipboard/
selection access, impossible in cloud. Anchor: Cursorless format/transform actions, Serenade.

## Decision

Add an opt-in **Voice Case Transform**: `[casetransform] enabled=false`. Pure cores:
`transform_case(text, style)` (tokenizes on non-alnum *and* camelCase boundaries, then renders one
of upper/lower/title/sentence/snake/kebab/camel/pascal/constant) and `detect_style_command(text)`
(parses "make this …"/"convert to …" → a style, longest phrase wins). Dependency-free; uses the
existing clipboard read/paste. OFF by default.

## Consequences

- Transforms existing selected text between any case/identifier convention; pure and exhaustive.
- Distinct from Spoken Code Mode (transform existing vs dictate new).
- Privacy (ADR-011): operates on your clipboard locally only.
- Caveat: the selection is provided via the clipboard bridge; the pure transform is off by default.
