"""Word-timestamp ↔ speaker-turn alignment (pure) — ADR-v2-125.

Assign each transcribed word to the diarization turn it overlaps most, then merge
consecutive same-speaker words into utterances. This reproduces WhisperX's
``assign_word_speakers`` semantics (max intersection duration + nearest-turn fill)
in dependency-free Python, so it is fully unit-testable with no model. The diarizer
and STT engine that produce the inputs live behind lazy backends.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Utterance:
    """A run of consecutive words attributed to one speaker.

    ``speaker`` is the diarizer's canonical cluster id (e.g. ``"speaker_0"``); the
    renderer maps it to a display name. Empty ``speaker`` means "not diarized".
    """
    speaker: str
    start: float
    end: float
    text: str


def _bounds(word):
    """Return ``(start, end, text)`` for a word (duck-typed Word or a 3-tuple)."""
    if hasattr(word, "start"):
        return float(word.start), float(word.end), (word.text or "").strip()
    start, end, text = word
    return float(start), float(end), (text or "").strip()


def _turn_bounds(turn):
    """Return ``(start, end, speaker)`` for a turn (duck-typed or a 3-tuple)."""
    if hasattr(turn, "speaker"):
        return float(turn.start), float(turn.end), turn.speaker
    start, end, speaker = turn
    return float(start), float(end), speaker


def assign_words_to_turns(
    words,
    turns,
    *,
    fill_nearest_max: float = 2.0,
    backchannel_max: float = 0.3,
):
    """Attribute each word to a speaker by maximum temporal overlap. Pure.

    For each word, sum its overlap with every turn per speaker and take the argmax
    speaker (summing handles a word straddling two consecutive same-speaker turns and
    gives a stable, deterministic winner). A word overlapping no turn is filled from
    the nearest turn by midpoint distance, but only within ``fill_nearest_max`` seconds
    — and a very short word (``< backchannel_max`` s, a likely backchannel) is *not*
    nearest-filled, so it is left unassigned rather than mis-stolen by an adjacent
    speaker. Ties break to the earliest-starting speaker for determinism.

    Returns a list of ``(speaker_or_None, start, end, text)`` per word, preserving
    input order. Blank-text words are dropped.
    """
    tb = [_turn_bounds(t) for t in (turns or ())]
    assigned = []
    for word in words or ():
        w_start, w_end, w_text = _bounds(word)
        if not w_text:
            continue
        overlap_by_speaker: dict = {}
        first_start: dict = {}
        for t_start, t_end, spk in tb:
            ov = min(w_end, t_end) - max(w_start, t_start)
            if ov > 0:
                overlap_by_speaker[spk] = overlap_by_speaker.get(spk, 0.0) + ov
                if spk not in first_start:
                    first_start[spk] = t_start
        if overlap_by_speaker:
            # max overlap; tie-break on earliest turn start for stable output
            speaker = max(
                overlap_by_speaker,
                key=lambda s: (overlap_by_speaker[s], -first_start[s]),
            )
        else:
            speaker = _nearest_speaker(
                w_start, w_end, tb,
                fill_nearest_max=fill_nearest_max,
                backchannel_max=backchannel_max,
            )
        assigned.append((speaker, w_start, w_end, w_text))
    return assigned


def _gap(w_start, w_end, t_start, t_end) -> float:
    """Seconds between a word and a turn; 0.0 if they touch or overlap. Pure."""
    return max(0.0, t_start - w_end, w_start - t_end)


def _nearest_speaker(w_start, w_end, tb, *, fill_nearest_max, backchannel_max):
    """Nearest-turn speaker for a word with zero overlap, or ``None``. Pure.

    Distance is the **gap to the turn**, not the distance between midpoints. Midpoints
    made the answer depend on how long the turn was rather than how far the word was
    from it, which is neither what `fill_nearest_max` is named for nor what its docstring
    promises ("within N seconds"), and produced two wrong answers on ordinary meeting
    input:

    * a word 0.1 s after a 100 s turn was **dropped** (its midpoint is 50 s away), while
      the identical 0.1 s gap after a 0.5 s turn was assigned;
    * a word 0.2 s after speaker A's turn and 0.8 s before speaker B's was given to
      **B** -- words in the wrong person's mouth in a transcript, which is the one error
      a diarized transcript must not make quietly.

    Turns are long in real meetings, so the long-turn case is the common one.
    """
    if not tb or (w_end - w_start) < backchannel_max:
        return None
    best_spk, best_dist, best_start = None, float("inf"), 0.0
    for t_start, t_end, spk in tb:
        dist = _gap(w_start, w_end, t_start, t_end)
        # Ties break to the earliest-starting turn, matching the overlap branch above,
        # so the output stays deterministic when a word sits midway between two turns.
        if dist < best_dist or (dist == best_dist and t_start < best_start):
            best_spk, best_dist, best_start = spk, dist, t_start
    return best_spk if best_dist <= fill_nearest_max else None


def merge_utterances(assigned, *, max_gap: float = 1.0):
    """Merge consecutive same-speaker words into utterances. Pure.

    Breaks a run on a speaker change or a silence gap larger than ``max_gap`` seconds.
    A word whose speaker is ``None`` inherits the current run's speaker (an unassigned
    punctuation/backchannel word stays with the surrounding utterance) or, if there is
    no current run, opens one with speaker ``""``.
    """
    utterances: list[Utterance] = []
    cur_spk = None
    cur_start = cur_end = 0.0
    cur_words: list[str] = []

    def flush():
        if cur_words:
            utterances.append(
                Utterance(cur_spk or "", cur_start, cur_end, " ".join(cur_words))
            )

    for speaker, start, end, text in assigned or ():
        eff_spk = speaker if speaker is not None else cur_spk
        gap = start - cur_end if cur_words else 0.0
        if cur_words and eff_spk == cur_spk and gap <= max_gap:
            cur_end = end
            cur_words.append(text)
        else:
            flush()
            cur_spk = eff_spk
            cur_start, cur_end = start, end
            cur_words = [text]
    flush()
    return utterances
