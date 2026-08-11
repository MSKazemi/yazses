# ADR-v2-058 — Mid-Utterance Self-Repair

**Status:** Accepted (2026-07-02) · Wave H
**Context links:** [[adr-v2-003-spoken-edit-mode]] (post-injection, separate turn), disfluency filter (implicit), [[adr-011]]

## Context

Wave H research (#8) — apply explicit in-burst corrections *before* text is injected: "email
Sarah — no, I mean Sara — about the deck" → injects "email Sara about the deck". Recognizes
editing terms ("no I mean", "make that", "or rather") and rewrites the pending transcript.
Anchor: Toward Interactive Dictation / TERTiUS (arXiv 2307.04008), repair taxonomy
(reparandum / interruption / editing-term / reparans).

Distinct from Spoken Edit Mode (edits *already-injected* text in a separate turn) and the
disfluency filter (removes repairs *implicitly*) — this is explicit, user-directed, and keeps
the intended correction, all pre-injection.

## Decision

Add an opt-in **Mid-Utterance Self-Repair**: `[commands] self_repair=false`. The pure core
`apply_self_repair(text)` finds "<reparandum> <editing-term> <reparans>" spans and replaces the
reparandum with the reparans (looping to resolve chained repairs), for a curated editing-term
set. Wired on the DICTATE path. OFF by default (editing phrases occur in ordinary speech). The
SpeechLLM span classifier for open-ended repairs is deferred.

## Consequences

- Ships with **no new dependency** — a curated editing-term grammar + span replacement.
- Distinct from Spoken Edit (pre-injection self-repair vs post-injection editing).
- Privacy (ADR-011): text-only local transform.
- Caveat: the single-token reparandum heuristic covers the common case → multi-word/open-ended
  repairs deferred to the SpeechLLM tier; off by default.
