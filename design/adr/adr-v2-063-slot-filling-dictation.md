# ADR-v2-063 — Structured Form / Slot-Filling Dictation

**Status:** Accepted (2026-07-02) · Wave H
**Context links:** [[adr-v2-047-field-aware-dictation]] (formats one field vs maps to many), [[adr-011]]

## Context

Wave H research (#6) — speak naturally once and fill a named-field template: with a user schema
(e.g. bug report: Title/Severity/Browser), "bug in login page, high priority, affects Firefox" →
routes each value to the right field. Anchors: Slot Filling as a Reasoning Task for SpeechLLMs
(arXiv 2510.19326), zero-shot contextual slot filling (2510.15851).

Distinct from Field-Aware Dictation (adapts *formatting to the focused field*) — this maps *one
utterance onto many fields* of a template.

## Decision

Add an opt-in **Slot-Filling Dictation**: `[slotfill] enabled=false`. The pure core
`fill_slots(text, slots)` matches a user-defined schema against an utterance: each `Slot` is
either an `after`-keyword slot (value = the token following the keyword) or a `choices` enum slot
(value = the first choice word present). Dependency-free. The SpeechLLM for freeform
utterance→slot mapping is deferred behind a `slotfill` extra. OFF by default.

## Consequences

- One utterance → many fields; pure schema matching, no model.
- Distinct from Field-Aware (one-to-many vs per-field formatting).
- Privacy (ADR-011): schema + matching are local; template flows never touch a server.
- Caveat: keyword/choice matching covers structured schemas → freeform mapping deferred to the
  SpeechLLM tier; off by default.
