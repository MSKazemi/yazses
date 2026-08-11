# ADR-v2-122 — Diacritize (diacritics restoration)

**Status:** Accepted (2026-07-03) · Wave N
**Context links:** itn (entity normalization), phonetic (corrector), translit, [[adr-011]]

## Context

Wave N research (#8) — English ASR drops diacritics on loanwords: "cafe", "naive", "cliche",
"jalapeno". Correct output matters for names, menus, and multilingual text, and nothing in the set
restores them (ITN handles entities, Phonetic handles mis-hearings). Anchor: diacritics/accent
restoration literature (NAACL 2024 diacritics restoration).

## Decision

Add an opt-in **Diacritize**: `[diacritize] enabled=false`. Pure core in `diacritize/restore.py`:
`restore_diacritics(text, extra)` — whole-word (and multi-word phrase, longest-first) replacement
from an unambiguous built-in lexicon, case-preserving ("Cafe"→"Café", "CAFE"→"CAFÉ"), with a user
`extra` mapping merged on top. Words that are also plain-English words ("resume", "expose") are
deliberately excluded — those need context and stay with an optional neural diacritizer backend.
OFF by default.

## Consequences

- Dictated loanwords/names come out correctly accented with zero configuration.
- Pure lexicon restorer → fully testable, deterministic, dependency-free.
- Distinct from ITN (numbers/entities) and Phonetic Corrector (mis-recognitions).
- Privacy (ADR-011): local text only.
- Caveat: lexicon covers common unambiguous loanwords; context-dependent words need the optional
  neural backend; off by default.
