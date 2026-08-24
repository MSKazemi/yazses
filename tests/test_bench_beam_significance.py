"""The beam table's paired bootstrap (`paper/benchmark/analyze_beam.py`).

Same reason as `test_bench_onset_significance.py`: this module's output is a verdict,
not a measurement, and a verdict is quoted without being re-derived. The specific risk
here is the pairing. A bootstrap that resampled the two conditions *independently*
would still run, still print an interval, and still look right -- it would simply be
several times too wide and would report every real difference in the grid as noise.
Nothing about the output reveals which of the two was computed, so it is pinned here.
"""
from __future__ import annotations

import json

import pytest

from tests.benchmark_deps import load


@pytest.fixture(scope="module")
def mod():
    return load("analyze_beam", "analyze_beam.py")


def _row(beam: int, errors: list[int], words: list[int] | None = None,
         model: str = "base.en", split: str = "test-clean") -> dict:
    words = words if words is not None else [10] * len(errors)
    total_w = sum(words)
    return {
        "model": model, "beam_size": beam, "split": split,
        "wer_pct": round(sum(errors) / total_w * 100, 2),
        "per_utt_errors": errors, "per_utt_ref_words": words,
    }


# --------------------------------------------------------------------------- #
# paired_bootstrap()
# --------------------------------------------------------------------------- #
def test_two_identical_conditions_show_no_difference(mod):
    a = _row(1, [1, 2, 3, 0, 1] * 20)
    got = mod.paired_bootstrap(a, _row(5, [1, 2, 3, 0, 1] * 20), n=2000)
    assert got["diff"] == 0.0
    assert got["diff_ci95"] == [0.0, 0.0]
    assert got["p"] == 1.0


def test_the_pairing_is_what_narrows_the_interval(mod):
    """The load-bearing property, tested against the mistake it prevents.

    Two conditions that differ by exactly one error on exactly one utterance. Under
    the pairing, every replicate scores both conditions on the *same* resample, so
    the only thing that varies is how often that one utterance was drawn. Resampling
    the two conditions independently instead lets the whole between-utterance
    variance of the corpus (0 to 3 errors per utterance here) leak into a difference
    that is really one error wide.

    Asserted as a ratio against an unpaired bootstrap computed here, rather than
    against a hand-picked width: the absolute width depends on the corpus and would
    make this a change-detector, while the *relationship* is the property that must
    hold for any input.
    """
    import random

    errs = [1, 2, 3, 0, 1] * 20
    worse = list(errs)
    worse[0] += 1
    a, b = _row(1, worse), _row(5, errs)

    got = mod.paired_bootstrap(a, b, n=4000)
    lo, hi = got["diff_ci95"]
    assert lo >= 0.0, "one extra error cannot make beam 1 better in any replicate"
    paired_width = hi - lo

    words = a["per_utt_ref_words"]
    rng = random.Random(mod.SEED)
    size = len(errs)
    unpaired = []
    for _ in range(4000):
        ia = [rng.randrange(size) for _ in range(size)]
        ib = [rng.randrange(size) for _ in range(size)]
        unpaired.append(mod._wer(worse, words, ia) - mod._wer(errs, words, ib))
    unpaired.sort()
    unpaired_width = unpaired[int(0.975 * 4000)] - unpaired[int(0.025 * 4000)]

    assert unpaired_width > 4 * paired_width, (
        f"paired interval {paired_width:.3f} wide, unpaired {unpaired_width:.3f}; "
        "these should differ by several times, and if they do not then the "
        "replicates are not being shared between the two conditions"
    )


def test_a_dominated_condition_is_unambiguous(mod):
    a = _row(1, [2] * 100)
    got = mod.paired_bootstrap(a, _row(5, [0] * 100), n=2000)
    assert got["diff"] == pytest.approx(20.0)
    assert got["p"] == 0.0
    assert got["diff_ci95"][0] > 0


def test_the_sign_says_which_condition_was_worse(mod):
    """`diff` is `a - b` on WER, so positive means the baseline made more errors.
    A flipped sign would invert every conclusion drawn from the table."""
    got = mod.paired_bootstrap(_row(1, [3] * 50), _row(5, [1] * 50), n=500)
    assert got["diff"] > 0
    back = mod.paired_bootstrap(_row(1, [1] * 50), _row(5, [3] * 50), n=500)
    assert back["diff"] < 0


def test_the_result_is_reproducible_from_the_seed(mod):
    a, b = _row(1, [1, 0, 2, 3] * 25), _row(5, [1, 1, 2, 2] * 25)
    first = mod.paired_bootstrap(a, b, n=800)
    assert first == mod.paired_bootstrap(a, b, n=800)


def test_word_counts_weight_the_corpus_wer(mod):
    """Corpus WER is total errors over total words, not the mean of per-utterance
    rates. A long utterance must count for more than a short one; averaging rates is
    the classic wrong answer and would move every figure here."""
    a = _row(1, [0, 10], words=[100, 10])   # 10 errors / 110 words = 9.09 %
    got = mod.paired_bootstrap(a, _row(5, [0, 0], words=[100, 10]), n=200)
    assert got["a_wer"] == pytest.approx(9.09, abs=0.01)
    assert got["diff"] == pytest.approx(9.0909, abs=0.01)


def test_rows_that_scored_different_utterances_are_refused(mod):
    """Reference word counts come from the reference, so two rows of one run must
    agree on them. If they do not, the rows are not over the same utterances and a
    pairing would be silently meaningless while still printing an interval."""
    with pytest.raises(ValueError):
        mod.paired_bootstrap(_row(1, [1, 1], words=[10, 10]),
                             _row(5, [1, 1], words=[10, 12]))


def test_rows_of_different_lengths_are_refused(mod):
    with pytest.raises(ValueError):
        mod.paired_bootstrap(_row(1, [1, 1, 1]), _row(5, [1, 1]))


def test_a_row_without_per_utterance_counts_is_refused(mod):
    a = _row(1, [1, 1])
    b = _row(5, [1, 1])
    del b["per_utt_errors"]
    with pytest.raises(ValueError):
        mod.paired_bootstrap(a, b)


# --------------------------------------------------------------------------- #
# analyse()
# --------------------------------------------------------------------------- #
def _artifact(tmp_path, rows):
    path = tmp_path / "beam-test-clean.json"
    path.write_text(json.dumps({"config": {}, "rows": rows,
                                "provenance": {"timestamp": "x"}}), encoding="utf-8")
    return path


def test_every_width_is_compared_against_beam_one_within_its_model(mod, tmp_path):
    rows = [
        _row(1, [1] * 20), _row(2, [1] * 20), _row(5, [1] * 20),
        _row(1, [1] * 20, model="small.en"), _row(5, [1] * 20, model="small.en"),
    ]
    res = mod.analyse(_artifact(tmp_path, rows))
    assert res["n_comparisons"] == 3
    # Never across models: they are different systems, and beam 1 of one is not a
    # baseline for beam 5 of the other.
    for c in res["comparisons"]:
        assert c["a"].split()[0] == c["b"].split()[0]


def test_a_model_with_no_beam_one_row_is_skipped_not_guessed(mod, tmp_path):
    res = mod.analyse(_artifact(tmp_path, [_row(2, [1] * 10), _row(5, [1] * 10)]))
    assert res["n_comparisons"] == 0


def test_a_totals_only_result_stops_rather_than_comparing_levels(mod, tmp_path):
    """`paper/results/beam-test-clean.json` as first archived is exactly this shape."""
    rows = [_row(1, [1] * 10), _row(5, [1] * 10)]
    for row in rows:
        del row["per_utt_errors"]
    with pytest.raises(SystemExit) as exc:
        mod.analyse(_artifact(tmp_path, rows))
    assert "per-utterance" in str(exc.value)
