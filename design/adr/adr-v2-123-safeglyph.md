# ADR-v2-123 — SafeGlyph (homoglyph/confusable hazard detection)

**Status:** Accepted (2026-07-03) · Wave N
**Context links:** cmdsafety (terminal guard), redaction (scrub), voiceguard, [[adr-011]]

## Context

Wave N research (#9) — dictated or pasted identifiers, URLs, and secrets can carry Unicode
homoglyphs (Cyrillic "а" vs Latin "a"), zero-width characters, and mixed-script words — classic
phishing/typosquatting and source-poisoning vectors. The set guards dangerous *commands*
(cmdsafety) but nothing inspects the *glyphs* being injected. Anchor: Unicode UTS-39 (security
mechanisms; confusable detection + skeleton algorithm).

## Decision

Add an opt-in **SafeGlyph**: `[safeglyph] enabled=false`. Pure cores in
`safeglyph/confusables.py`: `scan_confusables(text)` → findings (`confusable` for the common
Cyrillic/Greek homoglyph set + fullwidth forms, `invisible` for zero-width/soft-hyphen class,
`mixed-script` for words blending Latin with Cyrillic/Greek) each with an index and an ASCII
suggestion; `normalize_ascii(text)` → the UTS-39-style skeleton (homoglyphs mapped, invisibles
dropped). The full UTS-39 confusables data file stays an optional extra. OFF by default.

## Consequences

- Homoglyph/zero-width hazards are surfaced before text is injected into terminals/editors.
- Pure scanner + normalizer → fully testable, deterministic, dependency-free.
- Distinct from cmdsafety (semantic command risk) — this is glyph-level integrity.
- Privacy (ADR-011): local text only.
- Caveat: built-in table is the high-frequency UTS-39 subset; full confusables.txt is an optional
  data extra; off by default.
