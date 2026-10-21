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

## Amendment (2026-10-21) — PROPOSED, for the owner's review

**Status of this amendment: proposed, not accepted.** It records what was built toward wiring
(#164, WIRE-HESITATION-001). Nothing below is wired; `[hesitation]` is still unreachable and
off by default.

**What was missing.** `is_filled_pause` takes an F0 series and a spectral-stability value, and
nothing on main produced either from live audio. A shared numpy YIN tracker with per-frame
spectral flux now does (`src/yazses/audio/pitch.py`, also used by ADR-v2-103; no optional
extra), and `src/yazses/hesitation/stream.py` adapts it:

- "the trailing vocalization" is the 400 ms of frames ending at the most recent *voiced* frame.
  Silence and room noise are both unvoiced, so the window does not rest on an energy threshold;
- stability is `1 - mean(spectral flux)` over that window;
- **added condition:** the window must hold at least 300 ms of voiced frames, so the flat last
  syllable of an ordinary word does not extend the endpoint (AGENTS.md rule 9);
- `HesitationMonitor` queues chunks from the audio thread and analyses them on the reader's
  thread, then answers `endpoint_decision` for the caller's silence.

Open points for the owner: (a) hold-to-talk ends on key release, so the hold only changes
anything in a hands-free (`[autostop]`) turn — wiring there means `[hesitation] commit_ms` and
`[autostop] silence_timeout_ms` both describe the plain commit threshold, and one must win;
(b) the 300 ms / 400 ms / 25 Hz / 0.7 thresholds were checked on synthetic tones only.
