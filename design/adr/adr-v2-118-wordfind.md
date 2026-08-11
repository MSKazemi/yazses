# ADR-v2-118 — WordFind (offline reverse dictionary)

**Status:** Accepted (2026-07-03) · Wave N
**Context links:** recall (spoken recall), snippets, personalize (vocab), [[adr-011]]

## Context

Wave N research (#4) — tip-of-the-tongue moments break dictation flow: you know the meaning but
not the word. For anomia (word-finding difficulty after stroke/aphasia) this is the primary
barrier, and AAC research treats reverse lookup as core assistive tech. Nothing in the set maps a
description to a word. Anchor: WordNet reverse-dictionary work; TREC 2025 Tip-of-the-Tongue
track; anomia/AAC literature.

## Decision

Add an opt-in **WordFind**: `[wordfind] enabled=false, max_candidates=5`. Pure core in
`wordfind/rank.py`: `rank_candidates(query, lexicon, limit)` — content-word overlap (stopword-
filtered) between the spoken description and each definition, normalized by query size,
deterministic alphabetical tie-break. A small built-in demo lexicon ships in-tree; the user's own
entries merge over it, and WordNet-scale lexicons / embedding rerankers stay optional extras.
OFF by default.

## Consequences

- "The word for when water turns to gas" → ranked shortlist, spoken or displayed — flow preserved.
- Pure ranker → fully testable, deterministic, dependency-free.
- Distinct from Recall (your own past notes) — WordFind searches a lexicon of meanings.
- Privacy (ADR-011): local text only.
- Caveat: built-in lexicon is a demo tier; real coverage comes from the optional WordNet extra;
  off by default.
