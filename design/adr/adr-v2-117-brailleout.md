# ADR-v2-117 — BrailleOut (dictation as Unicode Braille output)

**Status:** Accepted (2026-07-03) · Wave N
**Context links:** tts (read-back), srpace (screen-reader pacing), [[adr-011]]

## Context

Wave N research (#3) — a Braille-display or DeafBlind user gets dictation output today only via a
screen-reader round-trip; nothing in the set emits Braille directly. Emitting Grade-2 Unicode
Braille (or `.brf`) makes YazSes usable as a direct speech→Braille channel. Anchor: liblouis (the
canonical open-source Braille translator) and the UEB (Unified English Braille) standard.

## Decision

Add an opt-in **BrailleOut**: `[brailleout] enabled=false, grade=2`. Pure core in
`brailleout/ueb.py`: `to_braille(text, grade)` — table-driven UEB translation to Unicode Braille
cells. Grade 1 transcribes letters (capital indicator), digit runs (single number sign) and
punctuation; Grade 2 adds the UEB strong/alphabetic wordsigns (standalone words) and groupsigns
(longest-match within words). Unknown characters pass through. Full liblouis tables remain an
optional heavy backend behind a lazy extra; the built-in table covers the common UEB core with no
new dependency. OFF by default.

## Consequences

- Direct dictation→Braille output for Braille-display and DeafBlind users.
- Pure table translator → fully testable, deterministic, dependency-free.
- Distinct from Read-Back (audio out) and SRPace (timing): this is an output *encoding*.
- Privacy (ADR-011): local text transformation only.
- Caveat: built-in table is a UEB subset (common wordsigns/groupsigns); liblouis extra for full
  fidelity/other languages; off by default.
