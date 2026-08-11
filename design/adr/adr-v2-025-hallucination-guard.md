# ADR-v2-025 — Hallucination Guard

**Status:** Accepted (2026-07-02) · Wave E
**Context links:** [[adr-v2-001-confidence-ink]] (distinct: words vs whole spans), [[adr-011]], postprocess/cleaner.py

## Context

Whisper fabricates confident nonsense on silence, breath, or noise — the notorious ghost
"Thank you.", "Please subscribe", or a phrase looped many times — which then gets typed.
The Wave E research (#1) anchors this to *Careless Whisper* (FAccT 2024, arXiv 2402.08021):
~1% of transcriptions contain fully fabricated content, worse for atypical/aphasic speech
(arXiv 2502.12414). Confidence Ink (ADR-v2-001) surfaces low-confidence *words*; it does not
target *whole fabricated spans*, and the plain transcribe path has no per-word data anyway.

## Decision

Add an opt-in **Hallucination Guard**: a pure detector that drops a transcript judged
fabricated before injection. Three signals, all pure:
1. **Ghost-phrase blacklist** — the *entire* cleaned transcript exactly matches a curated
   set of video-outro artefacts nobody dictates ("thanks for watching", "please subscribe",
   …). Conservative: substring matches and ambiguous single words are never auto-dropped.
2. **Repetition loop** — a short phrase repeated ≥N times dominating the text.
3. **Segment signals** (when available) — `no_speech_prob` / `avg_logprob` /
   `compression_ratio` thresholds, the standard Whisper hallucination tells.
Config `[hallucination] enabled=false, …thresholds`. Wired into `core/daemon.py` after
`clean_text`; when it fires, the burst is discarded (metadata-logged, ADR-011-safe). OFF by
default.

## Consequences

- Directly kills the most common Whisper failure that types garbage into the user's editor.
- Conservative blacklist (whole-transcript-only) avoids dropping legitimate short utterances.
- Pure detector → fully unit-tested; the segment-signal gate is ready for when the decode
  path exposes per-segment metadata.
- On-device only (ADR-011); operates on output already in RAM, stores nothing.
- Caveat: aggressive thresholds could drop a real terse utterance → default off, conservative
  defaults, whole-transcript-only blacklist.
