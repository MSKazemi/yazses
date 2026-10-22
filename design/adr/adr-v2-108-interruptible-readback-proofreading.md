# ADR-v2-108 — Interruptible Read-Back Proofreading (barge-in alignment)

**Status:** Accepted (2026-07-02) · Wave M
**Context links:** [[project_readback_loop]] (playback only), spoken-edit, [[adr-011]]

## Context

Wave M research (#4) — the draft is read aloud (TTS); the moment the user speaks ("stop — change
that to…"), the system maps the barge-in *timestamp* to the exact word being spoken and drops the
edit cursor there. Read-Back only *plays*; Spoken Edit edits whatever is current. The new primitive
is **time→word-index alignment of a barge-in during playback** — hearing-driven eyes-free
proofreading, which the excluded set lacks. Anchor: barge-in is a studied spoken-dialogue capability
(Interspeech/ICASSP); "hearing mistakes is easier than seeing them" is the canonical dyslexia-TTS
finding.

## Decision

Add an opt-in **Interruptible Read-Back Proofreading**: `[proofback] enabled=false`. Pure cores in
`proofback/align.py`: `build_schedule(words, per_word_ms)` → a cumulative `[Span(index, start_ms,
end_ms)]` playback timeline, `word_at(schedule, t_ms)` → the word index at a barge-in timestamp
(clamped to the ends), and `resolve_target(index, intent)` → the edit target. Pure arithmetic; the
TTS/barge-in capture is the existing infra. OFF by default.

## Consequences

- Eyes-free proofreading: interrupt the read-back and land the cursor on the exact word.
- Pure timeline/alignment → fully testable.
- Distinct from Read-Back (alignment vs playback) and Spoken Edit (barge-in-located vs current).
- Privacy (ADR-011): local audio/text only.
- Caveat: fixed/estimated per-word durations (true forced alignment is a later tier); off by default.

## Addendum (2026-10-21) — per-word playback timing; post-barge-in semantics open

`build_schedule` needs a duration per word, and no TTS backend reports one. Two pieces now
supply an estimate, still unwired:

- `proofback/timeline.py` (pure): `PlaybackTimeline.add_chunk(text, n_samples, sample_rate,
  started_at)` records each sentence chunk as it starts playing and spreads the chunk's
  duration over its words by `char_weight` (letters/digits, default) or `syllable_weight`
  (an English vowel-group heuristic). `word_at(t, lag_s=0.0)` maps a monotonic time to a
  global word index, which equals the word's position in `text.split()` of the read-back
  text. Silence between chunks maps to the last word heard; before playback, to word 0.
- `KokoroTtsBackend.set_playback_listener(fn)`: optional and duck-typed like `begin`, not a
  `TtsBackend` Protocol method. `speak` calls `fn(chunk, len(samples), sr, monotonic())`
  right after starting each chunk. Output-device latency is not subtracted.

Open questions, deliberately undecided:

1. **Which word does a barge-in mean?** The word playing at the hold, or an earlier one,
   because the listener reacts after hearing the mistake. `word_at` takes `lag_s` but
   defaults to 0. Nothing has measured the right value for this audience.
2. **What happens to playback after the edit?** Resume from the edited word, restart the
   sentence, or stop. Today a hold cancels read-back outright.
3. **What does the index address?** Read-back may be truncated to `[tts]
   max_readback_chars` with an appended `…`. Indices count words of the *spoken* text, so a
   caller must map them back onto the injected text. That holds only while the two texts
   share a word prefix.
4. **How is the cursor moved?** `resolve_target` returns `{word_index, intent}`. Turning
   that into keystrokes in an app that has since received other input is not designed.

## Addendum (2026-10-22) — wired; the post-barge-in decisions

Owner decision (2026-10-22): a barge-in marks the word being read, and the next dictated
burst replaces the text **from that word to the end of the burst**. Implemented in the pure,
clock-injected `proofback/bargein.py` and wired in `core/daemon.py`. The four open questions
above are answered as follows:

1. **Which word?** The word playing when the key goes down, `lag_s = 0.0`. The clock is read
   before the TTS is cancelled. The reaction-time lag is still unmeasured, so it is not a
   config key yet.
2. **Playback after the edit?** It stops, as any hold already did. The replacement burst is
   read back like any other dictation, so it can be proofread in turn.
3. **What does the index address?** A word of the *spoken* text. It is used only when the
   spoken and the typed text agree word for word up to and including that word. A word cut
   by `max_readback_chars` ("hel…") is reported, never replaced.
4. **How is the cursor moved?** It is not. The span always ends where the burst ends, so the
   erase is backspaces from the end of the text YazSes typed, the "scratch that" and
   Punch-In mechanism. Replacing only the one word would need a caret move or a re-type of
   the words after it. It would also need a guess at how many words the correction covers.

The guard (ADR-021) is checkable signals only. A hold is a barge-in only while the tray
is in `READBACK`, the utterance is the read-back of a dictated burst (not `yazses say`), and
at least one of its words has started playing. The armed target lives for exactly the next
burst. That burst erases nothing, and is typed as ordinary dictation, when:

- streaming is on, because live text already follows the old tail;
- the target is known not to be a text field;
- YazSes typed anything since the read-back;
- the burst is empty.

"Starts speaking" is not a barge-in signal: the recorder is push-to-talk and does not listen
during playback. Every hold source (keyboard, EMG, face switch) goes through `_on_hold_start`
and counts. The Mid-Thought-Undo ledger and the `[timeline]` history are rewritten to the
shortened burst, so "scratch that" and "undo burst" never press too many backspaces.

The feature is experimental and off by default. Word timing is estimated, and it has not been
observed on real hardware.
