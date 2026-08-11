# ADR-v2-119 — Echo (own-audio replay for a text span)

**Status:** Accepted (2026-07-03) · Wave N
**Context links:** proofback (read-back proofreading), scrub (audio-anchored scrubbing),
confidence, [[adr-011]]

## Context

Wave N research (#5) — proofreading dictation eyes-free is hard: TTS read-back of the *transcript*
can't reveal an ASR homophone error (it just re-speaks the wrong word correctly). Replaying the
*user's own captured audio* for a span exposes the mismatch by ear. The set has TTS read-back
(proofback) and audio-anchored scrubbing (scrub) but no "play my own recording of this text back"
verb. Anchor: Vertanen eyes-free ASR-error detection (arXiv 2410.20564).

## Decision

Add an opt-in **Echo**: `[echo] enabled=false`. Pure cores in `echo/span.py`:
`build_span_index(words)` → `Span(text, char_start, char_end, t_start, t_end)` list from word
timings (char offsets accumulate with one separating space, matching injected text);
`resolve_playback_target(utterance, spans)` → an audio `(t_start, t_end)` window for "play that
back"/"play all" (whole clip), "last word"/"that word", "first word", or a quoted/bare token
match (matching words merged), defaulting to the whole clip. The captured audio buffer and its
playback are the only I/O and reuse the existing recorder. OFF by default.

## Consequences

- Eyes-free homophone/ASR-error detection via the user's own voice, not TTS.
- Pure index + resolver → fully testable over synthetic word timings.
- Distinct from Proofback (TTS of transcript) and Scrub (navigation) — this replays source audio.
- Privacy (ADR-011): audio stays in the local capture buffer, never persisted by Echo.
- Caveat: needs word timings (faster-whisper provides them) and the retained audio buffer;
  off by default.
