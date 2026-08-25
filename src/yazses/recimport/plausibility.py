"""Does a diarization result look like people, or like fragments? — ADR-v2-133.

`factory.speaker_count_advice` warns *before* a run, from configuration alone: it can
say "you did not tell it how many people were in the room" and nothing more. This
module answers the question that can only be asked *after*, from the turns themselves.

It exists because of a measured failure. Scored against human annotations on the AMI
test split, the shipped clustering defaults found **257 speakers in a four-person
meeting**, and 86, 98 and 81 in the other three. Nothing in the pipeline noticed.
Meeting Mode wrote a transcript, ADR-v2-128's minutes consumed those labels as if they
named participants, and the user was handed a document attributing a discussion to a
crowd that was never in the room. An unusable result that announces itself is a bug
report; an unusable result that does not is a lie.

The signal is deliberately **not** the speaker count. A count alone cannot separate a
large meeting from a broken small one — twelve labels is ordinary in an all-hands and
absurd for a stand-up, and this code does not know which it was handed. What does
separate them is how much each label actually speaks: a person who attended a meeting
contributes tens of seconds to it, while an over-split cluster is a handful of seconds
of one person's voice that drifted far enough to be cut off from the rest.

So it fires on the *shape* of the distribution — most labels being too small to be a
participant — and only once there are enough labels for "most" to mean anything. That
tolerates the two legitimate cases a bare count or a bare minimum would flag: a big
meeting where everyone genuinely speaks, and a long meeting where one attendee says a
single word. It is one-directional and advisory by design: it can say a result looks
wrong, never that one looks right, and it never suppresses or edits a transcript.
"""
from __future__ import annotations

# A label holding less speech than this, across the entire recording, is more likely a
# fragment of somebody than a participant. Set from the measurement above rather than
# from taste: on AMI at the shipped defaults the median label held ~5 s, and with the
# speaker count supplied it held ~3 minutes. Anywhere in between separates them, so the
# value is chosen low enough that a genuinely quiet attendee is not called a fragment.
#
# It is a **ceiling**, not the threshold itself. 20 s is a meeting-length constant: AMI
# recordings run half an hour, where a participant who holds the floor for under twenty
# seconds is barely there. Applied unchanged to a five-minute import it calls ordinary
# speakers fragments — scored against VoxConverse at the shipped `[recimport]` default,
# a flat 20 s fired on 7 of 15 recordings and 3 of those 7 held a speaker count that was
# exactly right or too low, so the message ("split apart rather than that many people")
# was not merely noisy, it was false.
FRAGMENT_SECONDS = 20.0

# So the threshold scales with the recording, between a floor and that ceiling. 2% of
# all speech: on a half-hour meeting that is 36 s and the ceiling binds, leaving AMI
# behaviour untouched; on a five-minute clip it is 6 s.
FRAGMENT_SPEECH_FRACTION = 0.02

# The floor is what the fraction alone cannot do. Shatter a three-minute clip into forty
# equal slivers and every label holds exactly total/40 — no fraction-of-total rule can
# see it, because the fraction moves with the shattering. Under five seconds of speech
# in a whole recording is not a participant on any recording length.
FRAGMENT_FLOOR_SECONDS = 5.0

# Below this many labels, "most of them are small" is not a claim about a distribution.
# Four one-word answers in a five-person call must not trip it.
MIN_LABELS = 6

# How much of the result has to look like fragments before the result does. A half is
# the point past which the labels stop being a few stray splits and start being what
# the output mostly consists of.
FRAGMENT_RATIO = 0.5

# --- the second arm: over-splitting a long meeting ------------------------------------
#
# Everything above is an *absolute* rule -- a label is a fragment if it holds less than
# so many seconds -- and measurement showed that on the domain this guard was written
# for, it is very nearly inert. Scored against human annotations on 16 real AMI meetings
# at the shipped clustering threshold, 12 were genuinely over-split and the rule fired on
# **one** of them: 8.3% recall, 0 false alarms. It was not mistuned. The failure is
# structural: a half-hour meeting over-split into eight labels still gives every spurious
# label well over twenty seconds of accumulated speech, so nothing counts as a fragment,
# and FRAGMENT_RATIO then asks whether the output is *mostly* fragments -- a question
# that describes a shattered three-minute clip and not an over-split meeting at all.
#
# The two failures have different shapes, so they need different rules. Over-splitting a
# long recording shows up as a *distribution*: a few labels carrying the meeting and a
# tail carrying a small share each. That is scale-free, so this arm compares each label
# with the mean label instead of with a constant.
#
# Calibrated on the two corpora together (16 AMI meetings, 15 VoxConverse recordings
# scored at two clustering thresholds -- 46 scored results, 28 genuinely over-split).
# Adding this arm takes recall from 39.3% to 78.6% and leaves false alarms at **zero** on
# all three sets; on AMI alone it goes from 1/12 to 10/12. It is not a knife-edge: false
# alarms stay at zero for any gate from 750 s to 1800 s and any ratio from 0.25 to 0.4.
#
# The gate is a real gate and not a way of saying "AMI": three VoxConverse recordings sit
# above it and none of them false-alarms.
LONG_RECORDING_SECONDS = 900.0

# A label below a quarter of the mean label is a tail label, not a participant, however
# long the recording is.
RELATIVE_FRAGMENT_FRACTION = 0.25

# Lower than FRAGMENT_RATIO on purpose. The absolute arm asks whether the result is
# mostly fragments; this one asks whether it has a *tail*, and an over-split meeting is
# mostly real speakers with some spurious ones hanging off it.
RELATIVE_FRAGMENT_RATIO = 0.3

# ...and the tail has to actually hold some of the meeting. Without this, a long meeting
# where several people genuinely say one word each looks exactly like an over-split one:
# same label count, same share of labels in the tail. What separates them is how much
# speech the tail carries, because an over-split does not invent speech, it *takes* it
# from the real speakers. Measured on the AMI meetings that are genuinely over-split the
# tail holds 1.61% to 6.85% of all speech; for four one-word answers among six speakers
# it holds 0.44%. The floor sits between them with room on both sides.
#
# This case came from `test_one_word_answers_in_a_long_meeting_are_not_enough_to_flag_it`,
# not from the corpora -- neither AMI nor VoxConverse contains it, so the calibration
# could not have found it. The test predates the arm and failed the moment it was added.
RELATIVE_TAIL_SPEECH_FRACTION = 0.01


def speech_by_speaker(turns) -> dict[str, float]:
    """Total speech seconds per speaker label. Pure; tolerates unsorted, overlapping turns."""
    totals: dict[str, float] = {}
    for t in turns:
        speaker = getattr(t, "speaker", "") or ""
        start = float(getattr(t, "start", 0.0) or 0.0)
        end = float(getattr(t, "end", 0.0) or 0.0)
        if end > start:
            totals[speaker] = totals.get(speaker, 0.0) + (end - start)
    return totals


def fragment_threshold(total_speech_seconds: float) -> float:
    """How little speech makes a label a fragment, for a recording of this length. Pure.

    Bounded at both ends on purpose. The ceiling keeps long meetings — where the
    constant was measured — behaving exactly as before. The floor keeps a short
    recording shattered into equal slivers catchable, which a proportional rule alone
    cannot do.
    """
    scaled = FRAGMENT_SPEECH_FRACTION * max(0.0, total_speech_seconds)
    return min(FRAGMENT_SECONDS, max(FRAGMENT_FLOOR_SECONDS, scaled))


def attribution_problem(
    turns,
    *,
    fragment_seconds: float | None = None,
    min_labels: int = MIN_LABELS,
    fragment_ratio: float = FRAGMENT_RATIO,
) -> str | None:
    """A sentence describing implausible speaker attribution, or None. Pure.

    Never raises and never inspects audio: it reads only the turns a diarizer returned,
    so it costs nothing and works identically for a live meeting and an imported file.

    `fragment_seconds` overrides the derived threshold; `None` scales it to the
    recording, which is what every caller wants.
    """
    totals = speech_by_speaker(turns)
    if len(totals) < min_labels:
        return None
    derived = fragment_seconds is None
    if fragment_seconds is None:
        fragment_seconds = fragment_threshold(sum(totals.values()))
    fragments = [s for s in totals.values() if s < fragment_seconds]
    if len(fragments) >= fragment_ratio * len(totals):
        return (
            f"Speaker attribution looks unreliable: {len(totals)} speakers were found and "
            f"{len(fragments)} of them speak for under {fragment_seconds:.0f}s in total, "
            f"which is a person's worth of speech split apart rather than that many people."
        )
    # An explicit `fragment_seconds` means the caller is scoring one specific absolute
    # rule, so it gets that rule and nothing else.
    if not derived:
        return None
    return _long_recording_problem(totals)


def _long_recording_problem(totals: dict[str, float]) -> str | None:
    """The second arm: a long recording whose labels have a small-share tail. Pure.

    Only long recordings, because on a short one an uneven distribution is ordinary and
    this would fire on results that are perfectly correct -- which is exactly what the
    absolute arm was already caught doing on VoxConverse.
    """
    speech = sum(totals.values())
    if speech < LONG_RECORDING_SECONDS:
        return None
    mean = speech / len(totals)
    tail = [s for s in totals.values() if s < RELATIVE_FRAGMENT_FRACTION * mean]
    if len(tail) < RELATIVE_FRAGMENT_RATIO * len(totals):
        return None
    if sum(tail) < RELATIVE_TAIL_SPEECH_FRACTION * speech:
        return None
    return (
        f"Speaker attribution looks unreliable: {len(totals)} speakers were found in "
        f"{speech / 60:.0f} minutes of speech, and {len(tail)} of them hold under a "
        f"quarter of an average speaker's share, which is one person's speech split "
        f"off rather than that many people."
    )
