# ADR-v2-116 — Romanized → Native-Script Transliteration

**Status:** Accepted (2026-07-02) · Wave N
**Context links:** polyglot, langroute, translate, itn, [[adr-011]]

## Context

Wave N research (#2) — a bilingual user dictates their native language in Latin letters ("salam,
chetori?" / "ni hao") and YazSes injects the native script (سلام، چطوری؟ / 你好), because Whisper
mis-transcribes low-resource native audio but nails romanized phonetics. Polyglot/Langroute/Translate/
Interpret handle language *switching* and *translation*; ITN handles numbers. None do deterministic
**transliteration** (grapheme mapping within one language) — which turns YazSes into a usable
dictation tool for hundreds of millions whose script Whisper handles poorly (Persian, Hindi, Urdu,
Tamil…). Anchor: ITRANS (Chopde, 1994) and Pinyin are mature ASCII→script schemes; Google Input
Tools / Keyman ship exactly this for keyboards — but not for voice.

## Decision

Add an opt-in **Transliteration**: `[translit] enabled=false, scheme="finglish"`. Pure cores in
`translit/scheme.py`: `transliterate(latin, scheme)` (table-driven longest-match grapheme mapping,
built-in Finglish→Persian table) and `detect_scheme(text, enabled_scheme)` → the scheme or `None`
(an all-ASCII gate so English passes through untouched). Pure, table-driven, zero heavy deps; a
statistical Pinyin→Hanzi disambiguator is a lazy extra. OFF by default.

## Consequences

- Usable native-script dictation for bilingual/diaspora and low-resource-language users.
- Pure longest-match table → fully testable and deterministic.
- Distinct from Translate (script mapping vs meaning) and Polyglot (transliterate vs switch).
- Privacy (ADR-011): local text only.
- Caveat: the built-in tables are simplified (full ITRANS/Pinyin are later tiers); off by default.
