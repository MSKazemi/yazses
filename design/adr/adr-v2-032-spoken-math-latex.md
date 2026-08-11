# ADR-v2-032 — Spoken Math → LaTeX

**Status:** Accepted (2026-07-02) · Wave E
**Context links:** [[adr-v2-031-spoken-code-mode]], [[adr-011]]

## Context

The Wave E research (#3) proposes dictating math and injecting LaTeX ("x squared plus y
squared" → `x^{2} + y^{2}`) — for STEM writing and blind/low-vision mathematicians. Anchors:
MathSpeech (AAAI 2025, arXiv 2412.15655), Speech-to-LaTeX (ICLR 2026, arXiv 2508.03542).
General dictation and LLM cleanup mangle notation; this is a distinct target grammar.

## Decision

Add an opt-in **Spoken Math Mode**: `[math] enabled=false`. The pure core
`spoken_to_latex(text)` handles the common vocabulary and patterns — greek letters, operators
(`times`→`\times`, `plus/minus`), functions/symbols (`integral`→`\int`, `sum`→`\sum`,
`infinity`→`\infty`), and templates (`<t> squared`→`<t>^{2}`, `square root of <t>`→
`\sqrt{<t>}`, `<a> to the <b>`→`<a>^{<b>}`). Arbitrary nested expressions are out of scope for
the pure core and route to a deferred MathSpeech-style small seq2seq (T5-small int8) behind a
`mathspeech` extra. OFF by default; activatable via a dedicated command key.

## Consequences

- Covers the common cases with zero ML; the hard/nested cases stay behind an opt-in model.
- Pure transform → fully testable; on-device only (ADR-011).
- Caveat: the pure grammar is intentionally limited (honest scoping) → complex expressions
  need the deferred model; off by default.
