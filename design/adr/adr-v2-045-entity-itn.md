# ADR-v2-045 — Entity Inverse Text Normalization (ITN)

**Status:** Accepted (2026-07-02) · Wave G
**Context links:** [[adr-v2-027-phonetic-corrector]] (distinct: mis-heard vs mis-written), voice_punctuation (distinct: command words), [[adr-011]]

## Context

Wave G research (#1) — the single biggest daily dictation friction is that faster-whisper
spells out structured entities phonetically: emails become "john dot doe at gmail dot com",
version numbers become words, URLs and paths are mangled. Inverse text normalization (ITN)
rewrites correctly-heard-but-wrongly-written spans into their written form with **no command
words**. Anchors: NeMo ITN WFST grammars (arXiv 2104.05055), Thutmose Tagger single-pass neural
ITN (2208.00064), context-aware streaming ITN LM (2505.24229).

Distinct from **voice_punctuation** (converts *command words* like "comma"→",") and from the
**Phonetic Corrector** (fixes mis-*heard* words); ITN fixes *ordinary speech* describing
structured entities.

## Decision

Add an opt-in **Entity ITN**: `[itn] enabled=false`. The pure core `normalize_entities(text)`
ships a conservative, false-positive-averse rule set built on stdlib `re`, covering the two
highest-value, lowest-ambiguity entities first: **email addresses** ("X at Y dot Z" →
`X@Y.Z`, expanding "dot") and **version numbers** ("version two point one" / "version 2 point
1" → `v2.1`, digits or number-words). It is wired on the DICTATE path (mirroring
voice_punctuation) when enabled. Higher-ambiguity entities (bare URLs, dates, currency, phone
numbers — which need context to avoid false positives like "dot-com bubble") are deferred to a
rule expansion + the neural context-aware ITN LM behind an `itn` extra.

## Consequences

- Ships now with **no new dependency** — pure `re` rules; email + version are near-zero false
  positive (email requires an "at" with a dotted domain; version requires the leading "version").
- Distinct from voice_punctuation and Phonetic Corrector.
- Privacy (ADR-011): pure in-process string transform; no audio, no network.
- Caveat: conservative scope by design → URLs/dates/currency deferred so the enabled default
  never corrupts ordinary prose; off by default.
