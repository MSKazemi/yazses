# ADR-v2-057 — Spoken Temporal Normalizer

**Status:** Accepted (2026-07-02) · Wave H
**Context links:** [[adr-v2-045-entity-itn]] (formats numbers, doesn't resolve dates), [[adr-011]]

## Context

Wave H research (#3) — resolve spoken relative/absolute time expressions against the clock and
inject a concrete date: "next Friday" → "Fri Jul 10 2026", "tomorrow"/"yesterday"/"in two weeks"
→ concrete dates. Invaluable for email/calendar dictation. Anchors: SCATE end-to-end time
normalization (arXiv 2507.06450), SUTIME/HeidelTime, Python `dateparser`.

Distinct from Entity ITN, which *formats* number words ("twenty twenty" → "2020") but does not
*resolve* "next Friday" to a calendar date relative to now.

## Decision

Add an opt-in **Spoken Temporal Normalizer**: `[temporal] enabled=false`. The pure core
`resolve_temporal(text, now)` replaces recognized relative-date expressions
(today/tomorrow/yesterday, this/next <weekday>, "in N days/weeks") with a concrete formatted
date, using only stdlib `datetime` — `now` is injected so the function stays pure and
deterministically testable. Wired on the DICTATE path (the daemon passes the current time). The
neural SCATE model + `dateparser` for messy phrasing are deferred behind a `temporal` extra. OFF
by default.

## Consequences

- Ships with **no new dependency** — stdlib datetime arithmetic.
- Distinct from ITN (resolve vs format).
- Privacy (ADR-011): uses only the local system clock; fully offline.
- Caveat: built-in grammar covers common phrasings → messy natural language deferred to the
  neural tier; off by default so ordinary prose is never rewritten.
