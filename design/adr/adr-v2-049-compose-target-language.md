# ADR-v2-049 — Compose-in-Target-Language

**Status:** Accepted (2026-07-02) · Wave G
**Context links:** [[adr-v2-014-live-translation]] (X→English — this is the inverse), [[adr-013-llm-cleanup]] (length guard), [[adr-011]]

## Context

Wave G research (#6) — dictate in your strongest language and inject the text in a target
language you write less fluently: a native Farsi/Spanish speaker composes an English email by
speaking their own language; an English speaker fires off a Spanish reply. This is *composition*
(you produce foreign-language text), the inverse of Wave D's Live Translation (X→English
comprehension). Anchors: SeamlessM4T v2 (on-device speech→text translation, 96 output
languages), IWSLT 2025 low-resource speech translation (arXiv 2505.21781).

## Decision

Add an opt-in **Compose-in-Target-Language**: `[compose] enabled=false, source="", target="en"`.
The pure core routes and guards: `compose_route(source, target)` returns `(source, target)` (or
None when same/blank), and `is_plausible(src_text, out_text)` rejects MT output whose
length ratio is implausible (reuses the ADR-013 guard idea so a broken translation never
replaces good dictation). The MADLAD/SeamlessM4T MT model is lazy behind the existing `translate`
extra. OFF by default.

## Consequences

- Inverse of Live Translation (compose vs comprehend); multi-target vs English-only.
- Pure routing + plausibility guard → fully testable with no model.
- Privacy (ADR-011): offline MT runs locally, unlike every mainstream "translate as you type".
- Caveat: MT errors → the plausibility guard + off-by-default keep dictation safe.
