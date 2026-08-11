# ADR-v2-055 — Emoji & Symbol by Voice

**Status:** Accepted (2026-07-02) · Wave H
**Context links:** voice_punctuation (ASCII only — distinct), [[adr-v2-032-spoken-math]] (math render vs symbol insert), [[adr-011]]

## Context

Wave H research (#9) — speak emoji, symbols, and arrows: "shrug emoji" → 🤷, "check mark" → ✓,
"right arrow" → →, "degree sign" → °, "bullet" → •. Emoji/symbol pickers are a motor-accessibility
barrier (WCAG input-modality), and mainstream dictation offers essentially no symbol-by-voice.

Distinct from Voice Punctuation (covers only ASCII `.,;:` and newlines) and Spoken Math→LaTeX
(renders equations, doesn't insert standalone Unicode symbols/emoji).

## Decision

Add an opt-in **Emoji & Symbol by Voice**: `[commands] symbols=false`. The pure core
`apply_symbols(text)` replaces spoken symbol/emoji names with their Unicode character from a
curated name→codepoint table (longest phrase first, word-boundary protected so ordinary speech
is untouched). Wired on the DICTATE path (mirrors voice_punctuation). OFF by default (the names
also occur in normal speech). Descriptive fuzzy lookup ("the crying-laughing one") via an
on-device embedding is deferred.

## Consequences

- Ships with **no new dependency** — a static table + phrase replacement.
- Distinct from Voice Punctuation (Unicode symbols/emoji vs ASCII punctuation).
- Privacy (ADR-011): static local table, pure string transform, fully offline.
- Caveat: symbol names overlap ordinary words → off by default + word-boundary matching.
