# ADR-v2-112 — Spoken Spaced-Repetition Capture

**Status:** Accepted (2026-07-02) · Wave M
**Context links:** recall (ephemeral scratch), rag (query notes), [[adr-011]]

## Context

Wave M research (#8) — saying "remember that the capital of France is Paris" while dictating spins
off an Anki-format cloze card ("The capital of France is {{c1::Paris}}") to a local deck — study
material captured in the flow of work, no cloud. Spoken Recall is an ephemeral scratchpad and
Ask-My-Notes *queries* notes; neither **manufactures spaced-repetition study cards** with cue
detection + cloze generation. New learning/knowledge-capture area. Anchor: Anki + SM-2 (SuperMemo)
cloze deletion — mature, fully-local `.apkg`/SQLite formats; no mainstream tool offers hands-free
voice cloze capture.

## Decision

Add an opt-in **Spoken Spaced-Repetition Capture**: `[srscap] enabled=false`. Pure cores in
`srscap/cards.py`: `detect_fact(utterance)` (cue phrases "remember/note that … is/means/equals …" →
a `Fact`), `to_cloze(fact)` → a `Card(front, back, cloze)` with `{{c1::…}}`, and `sm2_schedule(state,
grade)` → the next `Sm2State` (interval/ease/reps) by the SM-2 algorithm. Pure; no dependency (deck
export is a thin downstream writer). OFF by default.

## Consequences

- Study cards captured in the flow of dictation, fully local.
- Pure cue-detection + cloze + SM-2 → fully testable.
- Distinct from Recall (durable cards vs ephemeral scratch) and RAG (create vs query).
- Privacy (ADR-011): local deck only.
- Caveat: simple "X is Y" cue grammar (richer templates are a later tier); off by default.
