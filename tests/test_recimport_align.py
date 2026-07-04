"""Pure word↔turn alignment — ADR-v2-125 (recimport/align.py)."""
from __future__ import annotations

from yazses.recimport.align import assign_words_to_turns, merge_utterances

# turns are (start, end, speaker); words are (start, end, text)
TURNS = [(0.0, 1.2, "speaker_0"), (1.8, 3.0, "speaker_1")]


def _speakers(assigned):
    return [a[0] for a in assigned]


def test_words_assigned_to_max_overlap_turn():
    words = [(0.0, 0.5, "hello"), (0.6, 1.1, "there"), (2.0, 2.5, "general")]
    assigned = assign_words_to_turns(words, TURNS)
    assert _speakers(assigned) == ["speaker_0", "speaker_0", "speaker_1"]


def test_straddling_word_goes_to_majority_speaker():
    # word 1.0–2.0 overlaps speaker_0 by 0.2 and speaker_1 by 0.2 → tie broken to
    # earliest-start speaker (speaker_0); shift to clearly favour speaker_1:
    words = [(1.1, 2.6, "mid")]
    assigned = assign_words_to_turns(words, TURNS)
    assert assigned[0][0] == "speaker_1"  # 0.8s in speaker_1 vs 0.1s in speaker_0


def test_gap_word_filled_from_nearest_turn_within_cap():
    words = [(1.4, 1.6, "uhh")]  # in the gap, 0.2s long but > backchannel default? no
    assigned = assign_words_to_turns(words, TURNS, backchannel_max=0.1)
    assert assigned[0][0] in ("speaker_0", "speaker_1")  # nearest fill happened


def test_short_backchannel_in_gap_left_unassigned():
    words = [(1.45, 1.55, "mm")]  # 0.1s < backchannel_max default 0.3 → not stolen
    assigned = assign_words_to_turns(words, TURNS)
    assert assigned[0][0] is None


def test_far_gap_word_beyond_cap_unassigned():
    words = [(50.0, 50.4, "later")]
    assigned = assign_words_to_turns(words, TURNS, fill_nearest_max=2.0)
    assert assigned[0][0] is None


def test_blank_words_dropped():
    assigned = assign_words_to_turns([(0.0, 0.5, "   "), (0.6, 1.0, "hi")], TURNS)
    assert len(assigned) == 1 and assigned[0][3] == "hi"


def test_merge_breaks_on_speaker_change():
    assigned = [
        ("speaker_0", 0.0, 0.5, "hello"),
        ("speaker_0", 0.6, 1.0, "there"),
        ("speaker_1", 2.0, 2.5, "general"),
    ]
    utts = merge_utterances(assigned)
    assert [(u.speaker, u.text) for u in utts] == [
        ("speaker_0", "hello there"),
        ("speaker_1", "general"),
    ]


def test_merge_breaks_on_long_gap_same_speaker():
    assigned = [
        ("speaker_0", 0.0, 0.5, "one"),
        ("speaker_0", 5.0, 5.5, "two"),  # gap 4.5s > max_gap
    ]
    utts = merge_utterances(assigned, max_gap=1.0)
    assert len(utts) == 2


def test_merge_none_speaker_inherits_run():
    assigned = [
        ("speaker_0", 0.0, 0.5, "hello"),
        (None, 0.6, 0.7, "."),
        ("speaker_0", 0.8, 1.2, "world"),
    ]
    utts = merge_utterances(assigned)
    assert len(utts) == 1 and utts[0].text == "hello . world"
