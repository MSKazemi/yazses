"""Per-word playback timeline for Interruptible Read-Back Proofreading (ADR-v2-108).

Pure arithmetic over (chunk text, sample count, sample rate, monotonic start), so every
timeline here is exact and needs no audio, model, or clock. The barge-in contract the
daemon will rely on: a time maps to the word that was playing then; silence between
chunks maps to the word just heard; an empty timeline answers -1.
"""
from __future__ import annotations

import threading

import pytest

from yazses.proofback.timeline import (
    PlaybackTimeline,
    TimedWord,
    char_weight,
    syllable_weight,
)
from yazses.tts.chunking import sentence_chunks

SR = 1000  # 1 sample == 1 ms keeps the expected numbers readable


# ---- weights ----------------------------------------------------------------

def test_char_weight_counts_letters_and_digits_only():
    assert char_weight("hello,") == 5.0
    assert char_weight("2026") == 4.0
    assert char_weight("—") == 1.0  # punctuation-only token still takes time
    assert char_weight("سلام") == 4.0  # Unicode letters count


def test_syllable_weight_heuristic():
    assert syllable_weight("cat") == 1.0
    assert syllable_weight("make") == 1.0  # silent final e
    assert syllable_weight("table") == 2.0  # -le keeps its syllable
    assert syllable_weight("banana") == 3.0
    assert syllable_weight("42") == 2.0
    assert syllable_weight("hmm") == 1.0  # never zero
    assert syllable_weight("سلام") == char_weight("سلام")  # non-ASCII falls back


# ---- construction -----------------------------------------------------------

def test_char_weighted_spread_within_one_chunk():
    tl = PlaybackTimeline()
    # "a" (1) + "bbb" (3) = 4 units over 400 ms starting at t=10.0 s.
    tl.add_chunk("a bbb", 400, SR, 10.0)
    assert tl.words == (
        TimedWord(0, "a", 0, 10.0, pytest.approx(10.1)),
        TimedWord(1, "bbb", 0, pytest.approx(10.1), 10.4),
    )
    assert tl.end_s() == 10.4


def test_syllable_weighting_changes_the_split():
    tl = PlaybackTimeline(weight=syllable_weight)
    # "banana" (3 syllables, 6 chars) vs "strength" (1 syllable, 8 chars).
    tl.add_chunk("banana strength", 400, SR, 0.0)
    assert tl.words[0].end_s == pytest.approx(0.3)
    tl_chars = PlaybackTimeline()
    tl_chars.add_chunk("banana strength", 1400, SR, 0.0)
    assert tl_chars.words[0].end_s == pytest.approx(0.6)


def test_contiguous_places_chunks_back_to_back_with_global_indices():
    tl = PlaybackTimeline.contiguous([("aa bb.", 400), ("cc dd.", 200)], SR, 5.0)
    assert [(w.index, w.text, w.chunk) for w in tl.words] == [
        (0, "aa", 0), (1, "bb.", 0), (2, "cc", 1), (3, "dd.", 1),
    ]
    assert tl.words[2].start_s == pytest.approx(5.4)
    assert tl.end_s() == pytest.approx(5.6)


def test_global_indices_match_split_of_the_chunked_text():
    text = "Fix the  first line.  Then read it back!   Done"
    chunks = list(sentence_chunks(text))
    tl = PlaybackTimeline.contiguous([(c, 100) for c in chunks], SR, 0.0)
    assert [w.text for w in tl.words] == text.split()


def test_last_word_ends_exactly_at_the_chunk_end():
    tl = PlaybackTimeline()
    tl.add_chunk("one two three four five six seven", 7001, 24000, 1.0)
    assert tl.words[-1].end_s == 1.0 + 7001 / 24000
    starts = [w.start_s for w in tl.words]
    assert starts == sorted(starts)


def test_zero_weight_everywhere_splits_evenly():
    tl = PlaybackTimeline(weight=lambda w: 0.0)
    tl.add_chunk("x y", 200, SR, 0.0)
    assert tl.words[1].start_s == pytest.approx(0.1)


def test_invalid_input_is_rejected():
    tl = PlaybackTimeline()
    with pytest.raises(ValueError):
        tl.add_chunk("a", 10, 0, 0.0)
    with pytest.raises(ValueError):
        tl.add_chunk("a", -1, SR, 0.0)
    tl.add_chunk("a", 10, SR, 5.0)
    with pytest.raises(ValueError):
        tl.add_chunk("b", 10, SR, 4.0)


# ---- word_at: the barge-in query ---------------------------------------------

def test_empty_timeline_answers_minus_one():
    tl = PlaybackTimeline()
    assert tl.word_at(0.0) == -1
    assert tl.end_s() is None
    assert tl.words == ()


def test_one_word_timeline_clamps_on_both_sides():
    tl = PlaybackTimeline()
    tl.add_chunk("hello", 500, SR, 2.0)
    assert tl.word_at(0.0) == 0
    assert tl.word_at(2.25) == 0
    assert tl.word_at(99.0) == 0


def test_barge_in_maps_to_the_word_being_spoken():
    tl = PlaybackTimeline.contiguous([("aa bb.", 400), ("cc dd.", 200)], SR, 5.0)
    # words: aa [5.0,5.2) bb. [5.2,5.4) cc [5.4,5.5) dd. [5.5,5.6)
    assert tl.word_at(5.0) == 0
    assert tl.word_at(5.199) == 0
    assert tl.word_at(5.2) == 1
    assert tl.word_at(5.45) == 2
    assert tl.word_at(5.55) == 3
    assert tl.word_at(4.0) == 0  # before playback: clamp to the first word
    assert tl.word_at(7.0) == 3  # after playback: the last word heard


def test_silence_between_chunks_maps_to_the_word_just_heard():
    tl = PlaybackTimeline()
    tl.add_chunk("one two.", 200, SR, 0.0)  # ends at 0.2
    tl.add_chunk("three.", 100, SR, 0.5)  # 0.3 s synthesis gap before it
    assert tl.word_at(0.35) == 1
    assert tl.word_at(0.5) == 2


def test_lag_moves_the_answer_back_by_the_reaction_time():
    tl = PlaybackTimeline.contiguous([("aa bb cc", 600)], SR, 0.0)
    assert tl.word_at(0.45) == 2
    assert tl.word_at(0.45, lag_s=0.3) == 0


def test_chunk_with_no_words_consumes_a_chunk_index_but_no_word():
    tl = PlaybackTimeline()
    tl.add_chunk("   ", 100, SR, 0.0)
    tl.add_chunk("word", 100, SR, 0.1)
    assert tl.words == (TimedWord(0, "word", 1, 0.1, pytest.approx(0.2)),)
    assert tl.word_at(0.0) == 0


def test_add_chunk_is_a_valid_playback_listener_across_threads():
    tl = PlaybackTimeline()
    seen: list[int] = []

    def play():
        for i in range(50):
            tl.add_chunk(f"w{i}", 10, SR, i * 0.01)

    def query():
        for _ in range(200):
            seen.append(tl.word_at(1.0))

    threads = [threading.Thread(target=play), threading.Thread(target=query)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert tl.word_at(1.0) == 49
    assert all(-1 <= s <= 49 for s in seen)
