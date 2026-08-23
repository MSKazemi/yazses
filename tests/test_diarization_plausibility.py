"""The post-hoc "does this look like people?" check on a diarization result.

The numbers in the AMI cases below are the measured ones, not invented shapes: scored
against the human annotations for the AMI test split, the shipped clustering defaults
returned 86 labels for the four people in IS1009a, with the largest holding 60s and the
smallest 0.32s. Every guard here exists so that result cannot pass silently again.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from yazses.recimport.plausibility import (
    FRAGMENT_SECONDS,
    attribution_problem,
    speech_by_speaker,
)


@dataclass(frozen=True)
class Turn:
    start: float
    end: float
    speaker: str


def _turns(durations: dict[str, float]) -> list[Turn]:
    """One turn per speaker, of the given total length, laid end to end."""
    out, t = [], 0.0
    for name, secs in durations.items():
        out.append(Turn(t, t + secs, name))
        t += secs
    return out


def _over_split(n: int) -> list[Turn]:
    """The measured IS1009a shape: a handful of real-sized labels, the rest fragments."""
    big = {f"speaker_{i}": s for i, s in enumerate([60.1, 47.6, 46.9, 38.4, 37.9])}
    small = {f"speaker_{i + 5}": 5.0 for i in range(n - 5)}
    return _turns({**big, **small})


def test_the_measured_ami_failure_is_flagged():
    problem = attribution_problem(_over_split(86))
    assert problem is not None
    assert "86 speakers" in problem


def test_a_normal_four_person_meeting_is_not_flagged():
    # Below the label floor as well as far above the fragment floor: a small meeting
    # must never trip this, whatever the balance between its speakers.
    assert attribution_problem(_turns({"a": 400.0, "b": 300.0, "c": 120.0, "d": 8.0})) is None


def test_a_large_meeting_where_everyone_really_speaks_is_not_flagged():
    # Twelve labels is the count that a count-based check would flag. Every one of them
    # holds a participant's worth of speech, so the shape says this is a big meeting.
    assert attribution_problem(_turns({f"s{i}": 45.0 for i in range(12)})) is None


def test_one_word_answers_in_a_long_meeting_are_not_enough_to_flag_it():
    # Four attendees say a single word each and six carry the discussion: 40% fragments,
    # which is exactly the case a bare "any speaker under 20s" rule would ruin.
    speakers = {f"big{i}": 300.0 for i in range(6)}
    speakers.update({f"tiny{i}": 2.0 for i in range(4)})
    assert attribution_problem(_turns(speakers)) is None


def test_it_flags_once_fragments_are_the_majority():
    speakers = {f"big{i}": 300.0 for i in range(5)}
    speakers.update({f"tiny{i}": 2.0 for i in range(6)})
    assert attribution_problem(_turns(speakers)) is not None


def test_five_labels_are_never_enough_to_claim_a_distribution():
    # All five are fragments, but five labels cannot establish "most of them".
    assert attribution_problem(_turns({f"s{i}": 1.0 for i in range(5)})) is None
    assert attribution_problem(_turns({f"s{i}": 1.0 for i in range(6)})) is not None


def test_no_turns_at_all_is_not_a_problem_report():
    # A dormant diarizer returns nothing; that is "not diarized", not "diarized badly".
    assert attribution_problem([]) is None


def test_speech_is_summed_across_a_speakers_turns_not_counted_once():
    turns = [Turn(0, 10, "a"), Turn(20, 35, "a"), Turn(35, 40, "b")]
    assert speech_by_speaker(turns) == {"a": 25.0, "b": 5.0}


@pytest.mark.parametrize("start,end", [(5.0, 5.0), (9.0, 4.0)])
def test_an_empty_or_reversed_turn_contributes_nothing(start, end):
    # Guards the subtraction: a reversed turn would otherwise credit negative speech and
    # could push a real speaker under the fragment floor.
    assert speech_by_speaker([Turn(start, end, "a")]) == {}


def test_the_thresholds_are_arguments_so_a_caller_can_tighten_them():
    speakers = {f"s{i}": 25.0 for i in range(8)}
    assert attribution_problem(_turns(speakers)) is None
    assert attribution_problem(_turns(speakers), fragment_seconds=30.0) is not None


def test_the_fragment_floor_sits_between_the_two_measured_regimes():
    # AMI at the shipped defaults: median label ~5s. AMI with the speaker count given:
    # ~3 minutes. The constant has to separate those and must not creep toward either.
    assert 5.0 < FRAGMENT_SECONDS < 180.0


def test_a_turn_object_need_not_be_the_diarizers_dataclass():
    # The meeting path and the import path build turns differently; this reads attributes.
    class Loose:
        def __init__(self, s, e, spk):
            self.start, self.end, self.speaker = s, e, spk

    assert speech_by_speaker([Loose(0, 3, "x")]) == {"x": 3.0}
