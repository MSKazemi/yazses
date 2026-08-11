# ADR-v2-071 — Citation-by-Voice from a local BibTeX/CSL library

**Status:** Accepted (2026-07-02) · Wave I
**Context links:** [[adr-v2-021-voice-grounded-rag]] (retrieve+generate vs deterministic lookup), [[adr-v2-030-spoken-math-latex]], [[adr-011]]

## Context

Wave I research (#10) — "cite Vaswani 2017" → a correctly formatted citation, fully offline, no
internet lookup. Fuzzy-matches the spoken author/year against a local `.bib` file and inserts a
citation in a chosen style (or a `\cite{key}` key for LaTeX). Distinct from Voice-grounded RAG,
which *retrieves and generates* — this is deterministic lookup + formatting from the user's own
library. An academic-accessibility win needing no model.

## Decision

Add an opt-in **Citation-by-Voice**: `[cite] enabled=false, style="latex"`. Pure cores:
`parse_bibtex(text)` → `Entry(key, authors, year, title)` list (a minimal, dependency-free
parser), `resolve_citation(query, entries)` → the best entry by surname + year fuzzy score, and
`format_citation(entry, style)` → LaTeX `\cite{key}`, or `Surname (Year)` / `Surname et al.
(Year)` for plain/APA. An optional embedding index for large libraries is deferred. OFF by default.

## Consequences

- Offline citation insertion — no internet round-trip a cloud tool would make.
- Pure parse + resolve + format → fully testable with an in-memory `.bib`.
- Distinct from RAG (deterministic lookup vs generation).
- Privacy (ADR-011): reads a local file; nothing transmitted.
- Caveat: the minimal parser covers common `@type{key, field = {…}}` entries; exotic BibTeX is the
  deferred tier. Off by default.
