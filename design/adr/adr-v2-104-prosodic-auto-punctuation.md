# ADR-v2-104 — Prosodic Auto-Punctuation (acoustic, word-free sentence structure)

**Status:** Accepted (2026-07-02) · Wave L
**Context links:** voice-punctuation (spoken words), prosody (pause→¶ + emphasis), itn, [[adr-011]]

## Context

Wave L research (#10) — Voice Punctuation requires the user to **say** "comma"/"period"; Prosody Ink
does pause→¶ and emphasis→bold only. Full sentence/clause punctuation driven by the **acoustic**
prosodic contour (pause duration, pitch declination/reset, terminal rise) — inserting `. , ?` without
any spoken punctuation words — is a distinct, broadly useful capability, and especially relieves
RSI/motor users of saying "comma… period…" every clause. Anchor: Cho et al., *Leveraging Prosody for
Punctuation Prediction of Spontaneous Speech* (Interspeech 2022, UW) — duration + pitch + energy
features beat pause-only punctuation on ASR output.

## Decision

Add an opt-in **Prosodic Auto-Punctuation**: `[prosodypunct] enabled=false, sentence_pause_ms=700,
comma_pause_ms=250`. Pure core in `prosodypunct/punctuate.py`: `punctuate_from_prosody(tokens,
pause_after_ms, pitch_reset, terminal_rise, ...)` → punctuated text — a sentence boundary (long pause
or pitch reset) takes `?` on a terminal rise else `.`; a medium pause takes `,`. The F0/energy
extraction is the optional lazy extra; the decision logic is 100% pure. OFF by default.

## Consequences

- Natural punctuation from how you speak, no spoken punctuation words.
- Pure feature-rule engine → fully testable with synthetic prosodic vectors.
- Distinct from Voice Punctuation (acoustic vs spoken keywords) and Prosody Ink (adds `. , ?` vs ¶).
- Privacy (ADR-011): local prosodic features only.
- Caveat: heuristic thresholds (a learned model is a later tier); off by default.
