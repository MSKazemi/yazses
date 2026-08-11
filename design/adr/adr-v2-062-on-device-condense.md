# ADR-v2-062 — On-Device Condense

**Status:** Accepted (2026-07-02) · Wave H
**Context links:** [[adr-v2-019-meeting-scribe]] (others' meeting vs your own burst), [[adr-013-llm-cleanup]] (abstractive tier), [[adr-011]]

## Context

Wave H research (#5) — speak a rambling paragraph, and a "condense" hotkey variant inserts a
tightened summary/outline instead of the verbatim transcript. Anchors: NVIDIA Canary-Qwen-2.5B
(on-device transcribe+summarize), Omi 0.6B on-device transcribe+summarize.

Distinct from Ambient Meeting Scribe (captures *others'* multi-speaker meetings) — this condenses
*your own single dictation burst* on demand.

## Decision

Add an opt-in **On-Device Condense**: `[condense] enabled=false, max_sentences=2`. The pure core
`condense(text, max_sentences)` performs extractive summarization — split into sentences, score
each by normalized content-word frequency, and emit the top-N in original order (dependency-free,
deterministic). The abstractive small-LLM (Qwen3-0.6B) is deferred behind the existing
`llm_cleanup` extra. OFF by default.

## Consequences

- Ships with **no new dependency** — frequency-ranked extractive summary.
- Distinct from Meeting Scribe (own burst vs others' meeting).
- Privacy (ADR-011): reuses the dormant offline LLM path when abstractive; nothing leaves the
  machine.
- Caveat: extractive summaries are blunt → abstractive tier is the quality path; off by default.
