# ADR-v2-101 — Hesitation-Hold Endpointing

**Status:** Accepted (2026-07-02) · Wave L
**Context links:** autostop (silence endpoint), self_repair (content), disfluency (filler removal), [[adr-011]]

## Context

Wave L research (#7) — Hands-Free Auto-Stop ends the turn on *silence*; Mid-Utterance Self-Repair
fixes *content*. Neither addresses the **false-endpoint problem**: when a user trails off with a
*filled* hesitation ("annnd… uhh…", an elongated vowel, a nasal "mmm") rather than clean silence,
the near-silence that follows is mis-read as "done" and the recognizer cuts them off mid-thought.
Detecting the *filled* pause and extending the endpoint threshold is a distinct timing behavior that
especially helps slow/aphasic/aging speakers. Anchor: Chatziagapi et al., *Audio and ASR-based Filled
Pause Detection* (ACII 2022) — filled pauses hold the floor; silence after word-lengthening/filled
pauses should be relabeled as pause, not sentence end.

## Decision

Add an opt-in **Hesitation-Hold Endpointing**: `[hesitation] enabled=false, commit_ms=800,
hold_extra_ms=1200`. Pure cores in `hesitation/endpoint.py`: `is_filled_pause(f0_series,
spectral_stability)` → detects a flat-F0, spectrally-stable sustained vocalization, and
`endpoint_decision(silence_ms, last_was_filled_pause, commit_ms, hold_extra_ms)` → `hold` | `commit`
(the threshold is extended by `hold_extra_ms` right after a filled pause). The F0/spectral extraction
is the lazy extra; the rule is pure. OFF by default.

## Consequences

- Fewer mid-thought cut-offs for people who think out loud; a turn-taking accessibility win.
- Pure rule over pre-computed features → fully testable with synthetic streams.
- Distinct from Auto-Stop (extends vs fixed silence) and Self-Repair (timing vs content).
- Privacy (ADR-011): local features only.
- Caveat: heuristic thresholds; a persistent hesitater could feel slower (tunable); off by default.
