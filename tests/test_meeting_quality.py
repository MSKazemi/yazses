"""Decode-collapse detection for Meeting Mode — `yazses.meeting.quality`.

The defect these guard: a real 41-minute meeting finalized as `status: "done"`,
`capture: "ok"`, with a transcript that was 93 repetitions of "Hello, hello, hello."
Every existing check passed it, so the recording was deleted as a successful
consumption and the meeting became unrecoverable.

The thresholds were measured against the five meetings stored on the machine where
that happened, and the numbers in `_REAL_CORPUS` are those measurements. A guard tuned
only to the one sample that broke is a guard that fires on the next healthy meeting,
so the healthy rows are as load-bearing as the collapsed one: they are what pins the
false-alarm rate at zero.
"""
from __future__ import annotations

import json

import pytest

from yazses.meeting import quality as q

# (name, duration_s, words_per_minute, top-trigram share, distinct-trigram ratio,
#  live word count, expected verdict) — measured on real stored meetings.
_REAL_CORPUS = [
    ("short-healthy", 56.7, 106.9, 0.0101, 1.0000, 0, q.QUALITY_OK),
    ("long-healthy", 8081.4, 117.9, 0.0049, 0.8210, 16000, q.QUALITY_OK),
    ("collapsed", 2499.7, 6.8, 0.9681, 0.0355, 4553, q.QUALITY_DEGENERATE),
]


def _word(n: int, seed: str = "") -> str:
    """A distinct pronounceable-ish token for index *n*.

    Letters only, deliberately: `tokenize` strips digits, so the obvious `f"w{i}"`
    fixture collapses to five hundred copies of "w" and makes every healthy-transcript
    test assert against a maximally degenerate one. It did, and they passed the guard
    for the wrong reason before this docstring existed.
    """
    out = ""
    n += 1
    while n:
        n, r = divmod(n - 1, 26)
        out = chr(ord("a") + r) + out
    return seed + out


def _healthy_text(words: int, seed: str = "") -> str:
    """Prose with no repeated trigram — the shape a healthy decode has."""
    return " ".join(_word(i, seed) for i in range(words))


def _collapsed_text(repeats: int) -> str:
    return " ".join(["hello hello hello"] * repeats)


# --- the real corpus: recall and false alarms, both reported ---------------------


def test_the_collapsed_real_meeting_is_caught():
    """1/1 recall on the meeting that actually broke."""
    res = q.assess(_collapsed_text(95), duration_s=2499.7, live_words=4553)
    assert res.verdict == q.QUALITY_DEGENERATE
    assert res.suspect
    assert res.reasons


def test_the_healthy_real_meetings_are_not_flagged():
    """0/2 false alarms on the real meetings that were fine.

    Reconstructed at the measured word counts and durations rather than asserted from
    the metrics directly, so this exercises `assess` end to end.
    """
    short = q.assess(_healthy_text(101), duration_s=56.7)
    assert short.verdict == q.QUALITY_OK, short.reasons
    assert not short.suspect

    long = q.assess(_healthy_text(15874), duration_s=8081.4, live_words=16000)
    assert long.verdict == q.QUALITY_OK, long.reasons
    assert not long.suspect
    # 16000 vs 15874 is a 1.008x disagreement — agreement, not a signal.
    assert not long.live_disagrees


def test_the_measured_margins_still_hold():
    """The thresholds sit clear of both edges of the real corpus, not against one.

    Fails if someone tightens a threshold to the point where a real healthy meeting
    would trip it, or loosens one past the collapsed sample.
    """
    for name, _dur, _wpm, top, distinct, _live, verdict in _REAL_CORPUS:
        if verdict == q.QUALITY_OK:
            assert top < q.MAX_TOP_NGRAM_SHARE, name
            assert distinct > q.MIN_DISTINCT_NGRAM_RATIO, name
        else:
            assert top >= q.MAX_TOP_NGRAM_SHARE, name
            assert distinct <= q.MIN_DISTINCT_NGRAM_RATIO, name


# --- the empty / tiny cases: a guard that "passes" on nothing is not a guard ------


def test_an_empty_transcript_is_unjudged_not_ok():
    """`ok` would be a claim we did not make. Empty is 'we could not look'."""
    res = q.assess("", duration_s=0.0)
    assert res.verdict == q.QUALITY_UNJUDGED
    assert not res.suspect


def test_a_tiny_transcript_is_unjudged():
    """The 26.6 s / 1-word accidental start — described by `capture`, not by this."""
    res = q.assess("hello", duration_s=26.6)
    assert res.verdict == q.QUALITY_UNJUDGED


def test_a_short_meeting_is_never_called_thin():
    """Thin needs a long recording; a 30 s clip holding one word is an accidental start."""
    res = q.assess("hello there", duration_s=30.0)
    assert res.verdict != q.QUALITY_THIN


def test_assess_never_raises_on_junk_inputs():
    for text, dur, live in [(None, None, None), ("", "x", "y"), ("a b c", -5, -3)]:
        q.assess(text, dur, live)  # must not raise


# --- each signal fires on its own -------------------------------------------------


def test_a_late_collapse_is_caught_by_the_run_length():
    """A meeting that decodes fine then loops near the end.

    The whole-transcript averages stay healthy here — this is exactly the case the
    share and ratio thresholds cannot see, and why the consecutive-run check exists.
    """
    text = _healthy_text(3000) + " " + _collapsed_text(q.MAX_REPEAT_RUN + 5)
    res = q.assess(text, duration_s=1800.0)
    assert res.top_ngram_share < q.MAX_TOP_NGRAM_SHARE
    assert res.distinct_ngram_ratio > q.MIN_DISTINCT_NGRAM_RATIO
    assert res.verdict == q.QUALITY_DEGENERATE
    assert any("back-to-back" in r for r in res.reasons)


def test_a_long_recording_that_decoded_almost_nothing_is_thin():
    res = q.assess(_healthy_text(30), duration_s=3600.0)
    assert res.verdict == q.QUALITY_THIN
    assert res.suspect


def test_live_disagreement_flags_an_otherwise_healthy_looking_transcript():
    """The strongest signal: two decodes of one recording that do not agree."""
    # 200 words over 2 minutes is 100 wpm — a healthy rate, so nothing but the
    # disagreement can be what fires here.
    res = q.assess(_healthy_text(200), duration_s=120.0, live_words=4000)
    assert res.verdict == q.QUALITY_OK      # the text itself looks fine
    assert res.live_disagrees               # but the second decode found 20x more
    assert res.suspect


def test_live_disagreement_needs_enough_batch_words_to_be_stable():
    """A 2-word batch result and a 7-word live one is not a 3.5x finding."""
    res = q.assess("hello there", duration_s=20.0, live_words=7)
    assert not res.live_disagrees


def test_degenerate_wins_over_thin():
    """A collapse is the more specific diagnosis and names the remedy."""
    res = q.assess(_collapsed_text(60), duration_s=3600.0)
    assert res.verdict == q.QUALITY_DEGENERATE


# --- the verdict must reach a human -----------------------------------------------


def test_warning_is_silent_on_a_healthy_transcript():
    assert q.warning(q.assess(_healthy_text(500), duration_s=300.0)) is None


def test_warning_points_at_the_live_transcript_when_it_is_the_better_record():
    res = q.assess(_collapsed_text(95), duration_s=2499.7, live_words=4553)
    msg = q.warning(res)
    assert msg and "live-transcript.md" in msg
    assert "4553" in msg


def test_warning_points_at_the_recording_when_there_is_no_live_transcript():
    msg = q.warning(q.assess(_collapsed_text(95), duration_s=2499.7))
    assert msg and "recording has been kept" in msg.lower()


# --- the record survives a round trip ---------------------------------------------


def test_as_dict_round_trips_and_recomputes_the_policy():
    res = q.assess(_collapsed_text(95), duration_s=2499.7, live_words=4553)
    payload = json.loads(json.dumps(res.as_dict()))
    back = q.from_dict(payload)
    assert back.verdict == res.verdict
    assert back.suspect == res.suspect
    assert back.live_disagrees == res.live_disagrees
    assert q.warning_from_dict(payload) == q.warning(res)


def test_from_dict_ignores_unknown_keys_and_a_lying_suspect_flag():
    """A stored file must not be able to talk the policy out of its own verdict."""
    payload = q.assess(_collapsed_text(95), duration_s=2499.7).as_dict()
    payload["suspect"] = False            # stale / hand-edited
    payload["some_future_field"] = 1
    assert q.from_dict(payload).suspect is True


def test_from_dict_survives_an_empty_or_broken_record():
    assert q.from_dict({}).verdict == q.QUALITY_UNJUDGED
    assert q.from_dict({"words": "not-a-number"}).verdict == q.QUALITY_UNJUDGED


@pytest.mark.parametrize("n", [0, 1, 2, 3, 10])
def test_longest_repeat_run_counts_consecutive_only(n):
    grams = [("a", "b", "c")] * n
    assert q.longest_repeat_run(grams) == n


def test_longest_repeat_run_ignores_scattered_repetition():
    """"Thank you" twenty times across an hour is a meeting, not a loop."""
    text = " ".join(f"thank you very much {_healthy_text(20, seed=_word(i))}" for i in range(20))
    res = q.assess(text, duration_s=240.0)  # 480 words / 4 min = 120 wpm, a healthy rate
    assert res.longest_repeat_run < q.MAX_REPEAT_RUN
    assert res.verdict == q.QUALITY_OK


def test_tokenize_normalises_unicode_forms():
    """Composed and decomposed forms are one word, so distinctness is not inflated."""
    assert q.tokenize("café") == q.tokenize("café")
