# ADR-v2-075 — Phonetic Spelling Mode

**Status:** Accepted (2026-07-02) · Wave J
**Context links:** [[adr-v2-048-entity-itn]] (normalizes prose vs character-exact), [[adr-v2-055-emoji-symbol-by-voice]], [[adr-011]]

## Context

Wave J research (#2) — a deliberate character-exact mode where NATO words map to letters ("capital
alpha, bravo, double lima" → `Abll`), with digits and symbols — the one case free dictation always
mangles: passwords, codes, IDs, filenames. Distinct from Entity ITN / Emoji-by-Voice (those
normalize prose); this is a mode that spells. A large motor/low-vision accessibility win with a
trivial pure core. Anchor: Picovoice on-device NATO-spelling engine (user-value, not novelty).

## Decision

Add an opt-in **Phonetic Spelling Mode**: `[spelling] enabled=false`. The pure core
`spell_parse(text)` maps NATO words → letters with `capital`/`cap`/`upper` (and `lowercase`)
modifiers and `double`/`triple` repeaters, plus spoken digits and symbols (dash, dot, underscore,
at, hash, slash, space, …). Dependency-free. An optional constrained/biased decode for the
spelling burst is deferred. OFF by default.

## Consequences

- Character-exact capture for the one thing prose dictation can't do; pure dict + modifier grammar.
- Distinct from ITN/Emoji (spells vs normalizes).
- Privacy (ADR-011): pure string mapping, fully offline.
- Caveat: covers the NATO set + common symbols → exotic glyphs need the deferred biased decode;
  off by default.
