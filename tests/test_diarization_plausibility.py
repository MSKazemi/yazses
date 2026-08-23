"""The post-hoc "does this look like people?" check on a diarization result.

The AMI cases below are the measured distributions, not invented shapes. Both come from
one recording, IS1009a, so the two directions of this check are tested against the same
11.5 minutes of audio: the shipped clustering defaults returned **86 labels for four
people**, and the human annotation of the same recording returned four. Every guard here
exists so that first result cannot pass silently again.

The fragment split is the real one, and it is closer to the ratio floor than a caricature
would be: 75 of the 86 labels hold under 20s, so 11 of them are participant-sized. A
fixture that gave the broken run only five real-sized labels would be an easier case than
the one that shipped.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from yazses.recimport.plausibility import (
    FRAGMENT_FLOOR_SECONDS,
    FRAGMENT_SECONDS,
    attribution_problem,
    fragment_threshold,
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


#: Every label in the shipped-defaults run on IS1009a that held 20s or more, in seconds,
#: exactly as measured. The remaining 75 labels are fragments; their median was 3.88s.
IS1009A_REAL_SIZED = [60.11, 47.6, 46.93, 38.37, 37.94, 31.37, 27.83, 25.38, 22.09,
                      21.72, 20.15]
IS1009A_FRAGMENTS = 75
IS1009A_FRAGMENT_MEDIAN = 3.88

#: The human annotation of the same recording: four people, 695.9s of speech between them,
#: and one of them holding most of it. Nothing here may look like a fragment.
IS1009A_REFERENCE = {"FIE088": 412.53, "FIO089": 144.26, "FIO087": 70.89, "FIO084": 68.22}


def _over_split() -> list[Turn]:
    """The measured IS1009a shape at the shipped defaults: 11 real labels, 75 fragments."""
    big = {f"speaker_{i}": s for i, s in enumerate(IS1009A_REAL_SIZED)}
    off = len(IS1009A_REAL_SIZED)
    small = {f"speaker_{i + off}": IS1009A_FRAGMENT_MEDIAN for i in range(IS1009A_FRAGMENTS)}
    return _turns({**big, **small})


def test_the_measured_ami_failure_is_flagged():
    problem = attribution_problem(_over_split())
    assert problem is not None
    assert "86 speakers" in problem
    assert "75 of them" in problem


def test_the_human_annotation_of_the_same_recording_is_not_flagged():
    # The other direction, on the same audio. This is what makes the check one-directional
    # rather than a count alarm: the true answer for IS1009a has to survive it untouched.
    assert attribution_problem(_turns(IS1009A_REFERENCE)) is None


def test_the_measured_fixture_is_the_measured_one():
    # Guards the fixture itself. The margin that matters is how far the real run sits above
    # the ratio floor, and a fixture that quietly drifted toward all-fragments would report
    # a guard that is more certain than the measurement behind it.
    turns = _over_split()
    totals = speech_by_speaker(turns)
    assert len(totals) == 86
    assert sum(1 for v in totals.values() if v < FRAGMENT_SECONDS) == IS1009A_FRAGMENTS


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


def test_the_fragment_threshold_scales_with_the_recording_between_its_bounds():
    """20 s is a meeting-length constant. On AMI, where it was measured, a recording
    runs half an hour and the ceiling binds; on a five-minute import it calls ordinary
    speakers fragments."""
    assert fragment_threshold(1800.0) == FRAGMENT_SECONDS       # 2% is 36 s; ceiling
    assert fragment_threshold(300.0) == pytest.approx(6.0)      # five minutes
    assert fragment_threshold(60.0) == FRAGMENT_FLOOR_SECONDS   # 2% is 1.2 s; floor
    assert fragment_threshold(0.0) == FRAGMENT_FLOOR_SECONDS
    assert fragment_threshold(-5.0) == FRAGMENT_FLOOR_SECONDS


def test_scaling_can_only_ever_relax_the_guard_never_tighten_it():
    """The property that makes this safe to change: the derived threshold is bounded
    above by the constant every published measurement was taken at, so no recording
    that was silent before can start warning."""
    for speech in (0.0, 30.0, 180.0, 600.0, 1800.0, 36000.0):
        assert fragment_threshold(speech) <= FRAGMENT_SECONDS


def test_a_short_clip_of_real_speakers_is_no_longer_called_fragments():
    """VoxConverse `aisvi`: eight labels for eight real speakers in 7.5 minutes, six of
    them under 20 s because the recording is short. The flat constant fired and told the
    user their result was "a person's worth of speech split apart" — of a result whose
    speaker count was exactly right."""
    aisvi = {"s0": 178.1, "s1": 10.1, "s2": 0.8, "s3": 11.3,
             "s4": 1.2, "s5": 23.3, "s6": 14.2, "s7": 213.5}
    assert attribution_problem(_turns(aisvi), fragment_seconds=20.0) is not None
    assert attribution_problem(_turns(aisvi)) is None


def test_a_short_clip_shattered_into_equal_slivers_is_still_caught():
    """The failure mode the floor exists for. Three minutes split forty ways: every
    label holds exactly total/40, so a proportional threshold moves with the shattering
    and never catches up. 4.5 s each is under the floor, and the floor does not move."""
    shattered = {f"s{i}": 180.0 / 40 for i in range(40)}
    assert fragment_threshold(180.0) == FRAGMENT_FLOOR_SECONDS
    assert attribution_problem(_turns(shattered)) is not None


def test_the_ami_catastrophe_this_guard_was_built_for_is_untouched():
    """257 labels in a four-person meeting, the measurement that produced the module.
    Half an hour of speech puts 2% above the ceiling, so the threshold is the same 20 s
    it always was."""
    ami = {f"s{i}": 1800.0 / 257 for i in range(257)}
    assert fragment_threshold(1800.0) == FRAGMENT_SECONDS
    assert attribution_problem(_turns(ami)) is not None
