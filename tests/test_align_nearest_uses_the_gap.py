"""A word is filled from the nearest turn by *gap*, not by distance between midpoints.

`_nearest_speaker` measured ``abs(word_midpoint - turn_midpoint)`` and compared it to
`fill_nearest_max`, whose name and docstring both promise "within N **seconds**" of the
turn. Those are the same number only when turns are short. Real meeting turns are not, and
the difference produced two wrong answers on ordinary input:

**The same gap, opposite outcomes.** A word 0.1 s after a 100-second turn was *dropped* —
its midpoint is 50 s away — while the identical 0.1 s gap after a 0.5-second turn was
assigned. Whether a word gets a speaker depended on how long that speaker had been
talking.

**The wrong speaker.** A word 0.2 s after speaker A's turn (0–60) and 0.8 s before
speaker B's (61.5–62.0) was attributed to **B**, because B's turn is short and its
midpoint is close. Putting words in the wrong person's mouth is the one error a diarized
transcript must not make quietly — it reads as fact.

Distance is now ``max(0, t_start - w_end, w_start - t_end)``: zero when they touch,
otherwise the real gap. The two existing guards are unchanged — the `fill_nearest_max`
cap still refuses a distant turn, and a word shorter than `backchannel_max` is still left
unassigned rather than stolen by a neighbour.
"""

from __future__ import annotations

import pytest

from yazses.recimport.align import _gap, assign_words_to_turns


def _speakers(words, turns, **kw):
    return [row[0] for row in assign_words_to_turns(words, turns, **kw)]


def test_the_same_gap_gives_the_same_answer_whatever_the_turn_length() -> None:
    """The defect in one assertion: only the gap may decide."""
    word = [(100.1, 100.6, "yes")]
    after_long = _speakers(word, [(0.0, 100.0, "S1")])
    after_short = _speakers(word, [(99.5, 100.0, "S1")])
    assert after_long == after_short == ["S1"], (
        f"a 0.1 s gap resolved differently by turn length: long={after_long} "
        f"short={after_short}"
    )


def test_the_nearer_speaker_wins() -> None:
    """0.2 s after A, 0.8 s before B — it is A's word."""
    assert _speakers([(60.2, 60.7, "right")], [(0.0, 60.0, "A"), (61.5, 62.0, "B")]) == ["A"]


def test_a_word_inside_a_turn_is_unaffected() -> None:
    """The overlap branch never went through this code; prove the fix left it alone."""
    assert _speakers([(50.0, 50.5, "hello")], [(0.0, 100.0, "S1")]) == ["S1"]


def test_the_distance_cap_still_refuses() -> None:
    """A fix that assigned everything to the only turn would pass the tests above."""
    assert _speakers([(110.0, 110.5, "later")], [(0.0, 100.0, "S1")]) == [None]
    assert _speakers(
        [(101.0, 101.5, "soon")], [(0.0, 100.0, "S1")], fill_nearest_max=0.5
    ) == [None]


def test_a_backchannel_is_still_not_stolen() -> None:
    """Short words stay unassigned rather than being attributed to a neighbour."""
    assert _speakers([(100.1, 100.2, "mm")], [(0.0, 100.0, "S1")]) == [None]


def test_no_turns_at_all() -> None:
    assert _speakers([(1.0, 1.5, "hello")], []) == [None]


@pytest.mark.parametrize(
    "w_start,w_end,t_start,t_end,expected",
    [
        (100.1, 100.6, 0.0, 100.0, pytest.approx(0.1)),   # word after turn
        (0.0, 0.5, 1.0, 2.0, pytest.approx(0.5)),         # word before turn
        (1.2, 1.4, 1.0, 2.0, 0.0),                        # word inside turn
        (1.0, 2.0, 2.0, 3.0, 0.0),                        # touching exactly
        (0.0, 1.5, 1.0, 2.0, 0.0),                        # partial overlap
    ],
)
def test_the_gap_itself(w_start, w_end, t_start, t_end, expected) -> None:
    assert _gap(w_start, w_end, t_start, t_end) == expected


def test_a_tie_is_deterministic() -> None:
    """Equidistant turns must resolve the same way every run.

    Ties break to the earliest-starting turn, matching how the overlap branch above
    already breaks its own ties.
    """
    turns = [(0.0, 10.0, "A"), (11.0, 21.0, "B")]
    word = [(10.5, 10.5, "x")]  # exactly 0.5 from each
    first = _speakers(word, turns, backchannel_max=0.0)
    assert first == ["A"]
    assert all(_speakers(word, turns, backchannel_max=0.0) == first for _ in range(5))
