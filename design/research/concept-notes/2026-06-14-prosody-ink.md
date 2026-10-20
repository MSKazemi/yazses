# Prosody Ink — origin note

> **Written:** 2026-06-14 · **Owner:** Mohsen Seyedkazemi Ardebili
> **Shipped as:** [ADR-v2-002 — Prosody Auto-Formatting](../../adr/adr-v2-002-prosody-autoformat.md)
> **Tier:** `design/` — public. Historical origin note; the ADRs above are the current
> source of truth.

## The idea

The pitch: a transcript is normally a flat token stream that throws away everything the
prosodic channel carries for free — stress, pause length, intonation. The dream was
dictation that keeps a thin, cheap slice of that music on the page: lean on a word and it
lands in bold, let a thought finish and breathe and a paragraph break opens, without ever
having to say "comma" or "new paragraph" out loud. The decision gate explicitly split the
idea into a safe subset (pause-to-paragraph, stress-to-bold) it judged ready to build, and
a riskier one (pitch-to-question-mark) it flagged as needing more evidence first.

## What shipped

The safe subset shipped: `src/yazses/postprocess/prosody.py` turns a pause at or above a
configured threshold into a paragraph break, and reuses ASR-level word-confidence signals
for emphasis marking — wired to the `prosody` feature toggle (**off by default**). It is
implemented as a pure post-processing pass over word timings and confidences, not a
separate prosody model. The pitch-to-question-mark direction the original card flagged as
unproven was not built as part of this pass.
