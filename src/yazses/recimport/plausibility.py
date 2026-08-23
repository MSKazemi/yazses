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
FRAGMENT_SECONDS = 20.0

# Below this many labels, "most of them are small" is not a claim about a distribution.
# Four one-word answers in a five-person call must not trip it.
MIN_LABELS = 6

# How much of the result has to look like fragments before the result does. A half is
# the point past which the labels stop being a few stray splits and start being what
# the output mostly consists of.
FRAGMENT_RATIO = 0.5


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


def attribution_problem(
    turns,
    *,
    fragment_seconds: float = FRAGMENT_SECONDS,
    min_labels: int = MIN_LABELS,
    fragment_ratio: float = FRAGMENT_RATIO,
) -> str | None:
    """A sentence describing implausible speaker attribution, or None. Pure.

    Never raises and never inspects audio: it reads only the turns a diarizer returned,
    so it costs nothing and works identically for a live meeting and an imported file.
    """
    totals = speech_by_speaker(turns)
    if len(totals) < min_labels:
        return None
    fragments = [s for s in totals.values() if s < fragment_seconds]
    if len(fragments) < fragment_ratio * len(totals):
        return None
    return (
        f"Speaker attribution looks unreliable: {len(totals)} speakers were found and "
        f"{len(fragments)} of them speak for under {fragment_seconds:.0f}s in total, "
        f"which is a person's worth of speech split apart rather than that many people."
    )
