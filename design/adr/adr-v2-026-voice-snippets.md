# ADR-v2-026 — Voice Snippets (spoken text expander)

**Status:** Accepted (2026-07-02) · Wave E
**Context links:** [[adr-v2-000-interaction-layer]], [[adr-011]], `[macros]` (keystrokes, distinct)

## Context

The Wave E research (#7) proposes voice-native text expansion: say "insert my signature" /
"standup template" and inject a stored multi-line template — the TextExpander/espanso pattern,
voice-triggered. YazSes `[macros]` fire *keystroke* sequences, and `vocabulary` biases
*recognition*; neither stores user *text templates* keyed by spoken trigger. High daily value
for boilerplate (signatures, addresses, templates).

## Decision

Add an opt-in **Voice Snippets** store: `[snippets] enabled=false, entries` (trigger phrase →
template text). The pure core `expand_snippet(phrase, entries)` normalizes the phrase, strips
an optional leading verb ("insert/expand/snippet"), and returns the matching template or
`None` (longest/exact trigger wins). Runs on the command path; when it returns text, that text
is injected. OFF by default.

## Consequences

- Distinct from `[macros]` (keystrokes) and `vocabulary` (recognition bias) — a text store.
- Pure match/expand → fully testable; entries live in the local config, nothing leaves the box.
- On-device only (ADR-011).
- Caveat: trigger phrases must not collide with ordinary dictation → matched only in command
  mode / with the leading verb, and off by default.
