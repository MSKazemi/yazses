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

## Implementation note (wired 2026-10)

Wired into the batch dictation path in `core/daemon.py`, immediately before Prosody Ink, through
`prosodypunct/apply.py::punctuate_text`. What shipped is the **pause-driven half**: `.` and `,` from
the silence between Whisper word timestamps. The pitch half (`pitch_reset`, `terminal_rise`, hence
`?`) is accepted by the pure core but the daemon supplies no F0 features yet, so no question mark is
ever written; that needs the lazy `prosody` extra and a measured false-positive rate first (the
Prosody Ink spec already records rising pitch as an unreliable question cue, since WH-questions fall).

Safety properties, each under test: punctuation the recognizer already wrote is never doubled; text
whitespace is preserved; when the word count of the text and the timings differ (number
normalisation, vocabulary correction) the text is left untouched; nothing is inserted after a
non-alphanumeric word end. It composes with Prosody Ink because that pass skips a word that already
ends in punctuation. Tier is `OPTIONAL`, not `RECOMMENDED`: a `RECOMMENDED` wired feature is switched
on for fresh installs, which would contradict "OFF by default".
