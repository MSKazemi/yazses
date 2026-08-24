"""`bench_diarization.time_weighted_der` — the aggregation the literature uses.

The summary's headline DER is the **unweighted mean across recordings**, which
`docs/benchmarks.md` names explicitly as a deliberate choice. It is not the quantity
NIST `md-eval`, AMI or DIHARD tables report; those aggregate over speech time. A reader
comparing this page's 26.71 % to a published AMI DER without noticing would be
comparing two different things, so both are now reported.

The two agree only when every recording is the same length. These tests pin that: a
corpus of equal-length recordings must give the same number both ways, and a corpus
where the long recording is the good one must give a *lower* time-weighted figure than
the per-recording mean. If those two ever coincide on unequal lengths, the weighting
has been dropped.
"""
from __future__ import annotations

import pytest

from tests.benchmark_deps import load


@pytest.fixture(scope="module")
def mod():
    return load("bench_diarization", "bench_diarization.py")


def _rows(*pairs: tuple[float, float]) -> list[dict]:
    """(der_percent, scored_seconds) per recording, under the `strict` key."""
    return [{"strict": {"der": d, "scored_seconds": s}} for d, s in pairs]


def test_equal_length_recordings_make_the_two_aggregations_agree(mod) -> None:
    rows = _rows((20.0, 600.0), (40.0, 600.0), (30.0, 600.0))
    assert mod.time_weighted_der(rows) == 30.0


def test_a_long_good_recording_pulls_the_weighted_figure_down(mod) -> None:
    """The whole reason the two numbers differ. Ten minutes at 60 % and fifty at 20 %
    is a 40 % mean per recording and a 26.67 % corpus DER -- and the second is what a
    published table would say."""
    rows = _rows((60.0, 600.0), (20.0, 3000.0))
    per_recording_mean = round((60.0 + 20.0) / 2, 2)
    assert per_recording_mean == 40.0
    assert mod.time_weighted_der(rows) == 26.67


def test_a_long_bad_recording_pulls_it_up(mod) -> None:
    """The other direction, so the test cannot pass on a function that always
    returns something smaller than the mean."""
    rows = _rows((20.0, 600.0), (60.0, 3000.0))
    assert mod.time_weighted_der(rows) == 53.33


def test_an_empty_corpus_is_zero_rather_than_a_zero_division(mod) -> None:
    assert mod.time_weighted_der([]) == 0.0


def test_a_corpus_of_silence_does_not_divide_by_zero(mod) -> None:
    """`scored_seconds` is md-eval's denominator: reference *speech* time. A
    recording whose reference holds no speech contributes nothing and must not
    take the aggregation down with it."""
    assert mod.time_weighted_der(_rows((0.0, 0.0))) == 0.0
    assert mod.time_weighted_der(_rows((0.0, 0.0), (40.0, 600.0))) == 40.0


def test_it_reads_the_collar_key_it_is_given(mod) -> None:
    """Both aggregations are reported for both collars. A function that ignored its
    key argument would silently report the strict figure twice."""
    rows = [
        {"strict": {"der": 40.0, "scored_seconds": 600.0},
         "collar250ms": {"der": 30.0, "scored_seconds": 600.0}},
    ]
    assert mod.time_weighted_der(rows, "strict") == 40.0
    assert mod.time_weighted_der(rows, "collar250ms") == 30.0


def test_the_scorer_records_the_denominator_this_needs(mod) -> None:
    """Guard the seam rather than the arithmetic. `time_weighted_der` is only
    re-derivable from an old artifact for as long as `score()` keeps writing
    `scored_seconds` into every per-meeting row."""
    import inspect

    src = inspect.getsource(mod.score)
    assert '"scored_seconds"' in src, (
        "score() no longer records the scored reference time, so the corpus-aggregated "
        "DER cannot be computed -- from a new run or from any artifact already committed."
    )
