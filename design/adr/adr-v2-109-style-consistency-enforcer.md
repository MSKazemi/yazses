# ADR-v2-109 — Local Style-Consistency Enforcer (Vale-lite)

**Status:** Accepted (2026-07-02) · Wave M
**Context links:** gec (grammar), corrdict (misrecognitions), [[adr-v2-114-acronym-glossary-manager]], [[adr-011]]

## Context

Wave M research (#5) — a user/house style sheet ("e-mail not email", US spelling, "cannot" not "can
not", expand vs contract) applied to each dictation so terminology stays consistent across a
document — a proselint/Vale pass, fully offline. Grammar Repair fixes grammar and the Self-Learning
Correction Dictionary fixes *misrecognitions*; neither enforces **stylistic/terminological
consistency** against a user rulebook. Distinct linter class. Anchor: Vale (errata-ai) and proselint
— established rule-based prose linters; editorial "standardize on first use" conventions — all
rule-table driven, no ML.

## Decision

Add an opt-in **Style-Consistency Enforcer**: `[styleguard] enabled=false`. Pure cores in
`styleguard/rules.py`: `load_stylerules(items)` → a list of `Rule(pattern, replacement, ignore_case,
regex)`, and `apply_style(text, rules)` → `(rewritten, [Change(before, after)])` (word rules match on
`\b` boundaries; regex rules apply verbatim). Pure regex; no dependency. OFF by default.

## Consequences

- Consistent terminology/style without a manual editing pass; user-supplied rulebook.
- Pure regex engine → fully testable.
- Distinct from GEC (style vs grammar) and Correction Dictionary (style vs misrecognition).
- Privacy (ADR-011): local text only.
- Caveat: literal/regex rules only (no NLP-aware rules); off by default.
