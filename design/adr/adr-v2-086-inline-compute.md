# ADR-v2-086 — Inline Compute

**Status:** Accepted (2026-07-02) · Wave K
**Context links:** [[adr-v2-056-voice-unit-conversion]] (converts vs evaluates), [[adr-v2-030-spoken-math-latex]] (formats vs evaluates), [[adr-v2-057-spoken-temporal-normalizer]], [[adr-011]]

## Context

Wave K research (#6) — on-device arithmetic, percentages and date math that injects the *computed
answer*: "what's 15% of 240" → `36`. Distinct from Voice Unit Conversion (converts units), Spoken
Math→LaTeX (formats), and the Temporal Normalizer (normalizes phrasing) — none *evaluate*. No cloud
needed for a calculator, so it's privacy-clean for sensitive figures. Anchor: Apple Math Notes
(iOS 18 / macOS Sequoia, inline solve).

## Decision

Add an opt-in **Inline Compute**: `[compute] enabled=false`. The pure core `evaluate(text)` maps
spoken operators to symbols, rewrites "N% of M" and bare percents, and evaluates the resulting
arithmetic expression through a **safe AST walker** (numbers + `+ - * / ** ( )` only — never
Python `eval`), formatting whole results as ints and fractional ones trimmed. Dependency-free. A
symbolic backend (sympy) for algebra and `dateutil` date math are deferred behind a `compute`
extra. OFF by default.

## Consequences

- Evaluates rather than converts/formats; the answer is typed inline.
- Safe AST evaluation (no `eval`) → no code-execution risk from a misrecognition.
- Distinct from unit conversion / LaTeX / temporal.
- Privacy (ADR-011): arithmetic never leaves the machine — a real differentiator for sensitive
  numbers.
- Caveat: pure core is arithmetic/percent only → algebra and date math are the deferred tier; off
  by default.
