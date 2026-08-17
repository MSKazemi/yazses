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


# ---------------------------------------------------------------------------
# Properties that hold for every transcript, not just the nine above.
#
# The example tests pin each documented behaviour on three or four words. What
# they cannot establish is what happens across a two-hour meeting: the failure
# that matters there is not a word given to the wrong speaker, it is a word that
# quietly stops appearing at all, in output nobody diffs against the audio.
# ---------------------------------------------------------------------------

def _random_transcript(rng):
    """Words with real durations and gaps, over turns that tile the timeline."""
    t = 0.0
    words = []
    for i in range(rng.randrange(1, 25)):
        t += rng.random() * 0.6                       # silence before the word
        d = 0.05 + rng.random() * 0.7                 # 50 ms .. 750 ms
        words.append((t, t + d, f"w{i}"))
        t += d
    turns, tt, k = [], 0.0, 0
    while tt < max(t, 0.1):
        d = 0.5 + rng.random() * 3.0
        turns.append((tt, tt + d, f"speaker_{k % 3}"))
        tt += d
        k += 1
    return words, turns


def test_no_word_is_ever_lost_or_reordered():
    """Blank words are dropped on purpose (see above); every other word survives."""
    import random

    rng = random.Random(11)
    for _ in range(400):
        words, turns = _random_transcript(rng)
        assigned = assign_words_to_turns(words, turns)
        assert [a[3] for a in assigned] == [w[2] for w in words]


def test_merging_preserves_the_transcript_exactly():
    """The property a long meeting depends on.

    `merge_utterances` decides where utterances break. A break in the wrong place
    is visible and arguable; a word dropped while re-joining runs is neither, and
    it lands in a transcript nobody re-checks against the recording.
    """
    import random

    rng = random.Random(12)
    for _ in range(400):
        words, turns = _random_transcript(rng)
        merged = merge_utterances(assign_words_to_turns(words, turns))
        assert " ".join(u.text for u in merged).split() == [w[2] for w in words]


def test_every_word_goes_to_the_speaker_it_overlaps_most():
    """The docstring's rule, checked against an independent computation.

    Overlap-per-speaker is recomputed here from the raw intervals rather than
    reusing anything the module does, so this disagrees with the implementation
    if either one is wrong.
    """
    import random

    rng = random.Random(13)

    def overlap(a1, a2, b1, b2):
        return max(0.0, min(a2, b2) - max(a1, b1))

    for _ in range(400):
        words, turns = _random_transcript(rng)
        for spk, ws, we, _txt in assign_words_to_turns(words, turns):
            per: dict[str, float] = {}
            for ts, te, tspk in turns:
                o = overlap(ws, we, ts, te)
                if o > 0:
                    per[tspk] = per.get(tspk, 0.0) + o
            if not per:
                continue  # no overlap at all: the nearest-fill rules apply instead
            best = max(per.values())
            assert spk is not None and per.get(spk, -1.0) >= best - 1e-9, (
                f"word [{ws}, {we}] went to {spk!r}; overlaps were {per}"
            )
