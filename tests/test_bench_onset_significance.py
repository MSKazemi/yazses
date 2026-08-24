"""The onset grid's significance test (`paper/benchmark/analyze_onset.py`).

Same reason as `test_bench_diarization_scoring.py`: a harness that reports a wrong
number is worse than none, because the number gets quoted. This one is the most
exposed of the three, because its output is not a measurement but a *verdict* --
"the lead-in helps" or "that difference is noise" -- and a p-value is believed
without being re-derived. So the arithmetic is pinned against cases whose answer is
known by hand, and the refusal path is pinned too: the first version of
`bench_onset.py` stored only per-cell counts, and a fallback to an unpaired test on
those counts would have answered a different question in the same confident tone.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.benchmark_deps import load


@pytest.fixture(scope="module")
def mod():
    return load("analyze_onset", "analyze_onset.py")


def _cell(arm: str, cut: int, lead: int, hits: str, run: int = 0) -> dict:
    return {
        "run": run, "arm": arm, "cut_ms": cut, "lead_ms": lead,
        "first_word_ok": hits.count("1"), "n": len(hits), "first_word_hits": hits,
        "wer_pct": 0.0, "empty_hyps": 0, "decode_seconds": 1.0,
    }


# --------------------------------------------------------------------------- #
# exact_mcnemar()
# --------------------------------------------------------------------------- #
def test_no_disagreement_is_not_evidence(mod):
    """Two conditions that never differed on any utterance. 0/0 is not a test
    result, and returning anything below 1.0 here would call every identical pair of
    cells in the grid significant."""
    assert mod.exact_mcnemar(0, 0) == 1.0


def test_a_symmetric_split_is_the_null(mod):
    assert mod.exact_mcnemar(5, 5) == 1.0
    assert mod.exact_mcnemar(1, 1) == 1.0


@pytest.mark.parametrize(
    "b,c,expected",
    [
        # Two-sided exact binomial, computed by hand from the PMF:
        (0, 5, 2 * (1 / 32)),            # 5 flips, all one way
        (0, 6, 2 * (1 / 64)),
        (1, 9, 2 * (1 + 10) / 1024),     # 10 flips, at most one the other way
        (2, 8, 2 * (1 + 10 + 45) / 1024),
    ],
)
def test_the_p_value_matches_the_binomial(mod, b, c, expected):
    assert mod.exact_mcnemar(b, c) == pytest.approx(expected, abs=1e-12)


def test_the_test_is_symmetric_in_its_arguments(mod):
    """Which cell is called the baseline must not change the p-value."""
    for b, c in [(0, 5), (1, 9), (3, 11), (7, 2)]:
        assert mod.exact_mcnemar(b, c) == mod.exact_mcnemar(c, b)


def test_a_p_value_is_never_above_one(mod):
    """`2 * tail` overshoots when the split is near even; the clamp is not cosmetic --
    a reported p of 1.6 would be read as a formatting bug in the table rather than as
    the null it actually is."""
    for b in range(6):
        for c in range(6):
            assert 0.0 <= mod.exact_mcnemar(b, c) <= 1.0


def test_more_evidence_lowers_the_p_value(mod):
    """The same one-sided split, seen more times, must be more surprising."""
    assert mod.exact_mcnemar(0, 8) < mod.exact_mcnemar(0, 5) < mod.exact_mcnemar(0, 3)


# --------------------------------------------------------------------------- #
# compare() -- the pairing itself
# --------------------------------------------------------------------------- #
def test_pairing_ignores_the_utterances_both_got_right(mod):
    """The point of the paired test. These two cells agree on 8 of 10 utterances and
    disagree on 2, both in the same direction. An unpaired reading sees 9 vs 7 out of
    10 and finds nothing; the paired one sees a 2-0 split."""
    a = _cell("intact", 0, 0, "1111111110")
    b = _cell("intact", 0, 300, "1111111000")
    got = mod.compare(a, b)
    assert (got["a_ok"], got["b_ok"], got["n"]) == (9, 7, 10)
    assert (got["only_a"], got["only_b"], got["discordant"]) == (2, 0, 2)
    assert got["p"] == pytest.approx(0.5)  # 2 * (1/4)


def test_identical_cells_are_reported_as_no_difference(mod):
    a = _cell("intact", 0, 0, "1101110111")
    got = mod.compare(a, _cell("intact", 0, 300, "1101110111"))
    assert got["discordant"] == 0
    assert got["p"] == 1.0


def test_equal_counts_can_still_disagree_on_every_utterance(mod):
    """Two cells with the *same* first-word count are not the same result. A table of
    counts cannot show this at all, which is the whole reason the per-utterance
    outcome is stored."""
    got = mod.compare(_cell("intact", 0, 0, "11110"), _cell("intact", 0, 300, "01111"))
    assert got["a_ok"] == got["b_ok"] == 4
    assert got["discordant"] == 2


def test_a_cell_without_outcomes_is_refused(mod):
    a = _cell("intact", 0, 0, "111")
    b = _cell("intact", 0, 300, "110")
    del b["first_word_hits"]
    with pytest.raises(ValueError):
        mod.compare(a, b)


def test_cells_of_different_lengths_are_refused(mod):
    """Two runs over different subset sizes cannot be paired utterance by utterance,
    and zipping them would silently pair the first N and drop the rest."""
    with pytest.raises(ValueError):
        mod.compare(_cell("intact", 0, 0, "1111"), _cell("intact", 0, 300, "111"))


# --------------------------------------------------------------------------- #
# analyse() -- what gets compared with what
# --------------------------------------------------------------------------- #
def _artifact(tmp_path, rows, name="onset.json"):
    path = tmp_path / name
    path.write_text(json.dumps({"config": {}, "rows": rows, "provenance": {"timestamp": "x"}}), encoding="utf-8")
    return path


def test_every_cell_is_compared_against_its_own_baseline(mod, tmp_path):
    rows = [
        _cell("intact", 0, 0, "1110"), _cell("intact", 0, 300, "1111"),
        _cell("clipped", 120, 0, "1000"), _cell("clipped", 120, 300, "1100"),
    ]
    res = mod.analyse(_artifact(tmp_path, rows))
    assert res["n_comparisons"] == 2
    # Never across arms or cuts: those decode different audio, so a difference would
    # not be attributable to the lead-in at all.
    for c in res["comparisons"]:
        assert c["a"].split()[0] == c["b"].split()[0]
        assert c["a"].split()[1] == c["b"].split()[1]


def test_runs_are_not_pooled(mod, tmp_path):
    """`--repeat` decodes the same grid twice. Pooling the repeats would double the
    apparent sample size while the audio stayed the same."""
    rows = [
        _cell("intact", 0, 0, "1110", run=0), _cell("intact", 0, 300, "1111", run=0),
        _cell("intact", 0, 0, "1110", run=1), _cell("intact", 0, 300, "1111", run=1),
    ]
    res = mod.analyse(_artifact(tmp_path, rows))
    assert res["n_comparisons"] == 2
    assert all(c["n"] == 4 for c in res["comparisons"])


def test_a_group_with_no_baseline_is_skipped_not_guessed(mod, tmp_path):
    rows = [_cell("intact", 0, 100, "1110"), _cell("intact", 0, 300, "1111")]
    assert mod.analyse(_artifact(tmp_path, rows))["n_comparisons"] == 0


def test_a_result_without_outcomes_stops_rather_than_falling_back(mod, tmp_path):
    """`paper/results/onset.json` as first published is exactly this shape. The
    refusal is the feature: an unpaired test on the counts would produce a number,
    and the number would be quoted."""
    rows = [_cell("intact", 0, 0, "1110"), _cell("intact", 0, 300, "1111")]
    for row in rows:
        del row["first_word_hits"]
    with pytest.raises(SystemExit) as exc:
        mod.analyse(_artifact(tmp_path, rows))
    assert "first_word_hits" in str(exc.value)


_RESULTS = Path(__file__).resolve().parent.parent / "paper" / "results"


# --- replicates are not independent tests -------------------------------------------
#
# The grid is run end to end twice, so every comparison appears once per run against
# the *same 200 utterances*. The first version of `_report` treated those 32 rows as 32
# tests: it advised a Bonferroni threshold of alpha/32 (over-correcting by a factor of
# two) and, in the other direction, would have let a single lucky cell be quoted as two
# independent findings. Both errors point the same way -- toward reading noise as a
# result -- which is exactly what this analysis exists to prevent.


def _grid(*, runs: int, only_a: int, only_b: int) -> dict:
    """A minimal onset artifact: one arm, one cut, one lead, repeated `runs` times.

    `only_a` utterances go to the baseline and `only_b` to the cell, with the rest
    concordant, so the McNemar counts are dictated rather than inferred.
    """
    n = 40
    rows = []
    for r in range(runs):
        base = "1" * only_a + "0" * only_b + "1" * (n - only_a - only_b)
        cell = "0" * only_a + "1" * only_b + "1" * (n - only_a - only_b)
        rows.append({"run": r, "arm": "clipped", "cut_ms": 120, "lead_ms": 0,
                     "first_word_hits": base, "n": n})
        rows.append({"run": r, "arm": "clipped", "cut_ms": 120, "lead_ms": 600,
                     "first_word_hits": cell, "n": n})
    return {"config": {}, "rows": rows}


def _analyse_grid(mod, tmp_path, grid: dict) -> dict:
    path = tmp_path / "onset.json"
    path.write_text(json.dumps(grid), encoding="utf-8")
    return mod.analyse(path)


def test_two_replicates_of_one_comparison_count_as_one_comparison(mod, tmp_path) -> None:
    res = _analyse_grid(mod, tmp_path, _grid(runs=2, only_a=10, only_b=1))
    assert res["n_comparisons"] == 2, "both replicate rows should still be reported"
    assert res["n_distinct"] == 1, "but they test one condition, not two"


def test_the_bonferroni_threshold_is_over_conditions_not_over_rows(mod, tmp_path) -> None:
    """The concrete arithmetic error: alpha/32 where 16 questions were asked."""
    res = _analyse_grid(mod, tmp_path, _grid(runs=2, only_a=10, only_b=1))
    assert res["bonferroni_alpha"] == pytest.approx(mod.ALPHA / res["n_distinct"])
    assert res["bonferroni_alpha"] != pytest.approx(mod.ALPHA / res["n_comparisons"])


def test_more_replicates_do_not_loosen_the_threshold(mod, tmp_path) -> None:
    """A stronger statement than the last: the correction must be *invariant* to how
    many times the grid was repeated. Repeating a measurement is not asking a new
    question, and a denominator that grows with repeats would make a finding easier
    to reach by simply running the harness again."""
    two = _analyse_grid(mod, tmp_path, _grid(runs=2, only_a=10, only_b=1))
    ten = _analyse_grid(mod, tmp_path, _grid(runs=10, only_a=10, only_b=1))
    assert ten["bonferroni_alpha"] == two["bonferroni_alpha"]
    assert ten["n_distinct"] == two["n_distinct"] == 1


def test_a_finding_must_hold_in_every_replicate_to_be_counted(mod, tmp_path) -> None:
    """`n_distinct_significant` is the count a reader is invited to trust, so it must
    require the replicate to agree -- one run out of two is the failure this whole
    file is about."""
    grid = _grid(runs=2, only_a=10, only_b=1)
    # Weaken the second replicate to a 5/4 split: nowhere near significant.
    for row in grid["rows"]:
        if row["run"] == 1:
            n = row["n"]
            if row["lead_ms"] == 0:
                row["first_word_hits"] = "1" * 5 + "0" * 4 + "1" * (n - 9)
            else:
                row["first_word_hits"] = "0" * 5 + "1" * 4 + "1" * (n - 9)
    res = _analyse_grid(mod, tmp_path, grid)
    assert res["distinct"][0]["significant_runs"] == 1
    assert res["distinct"][0]["runs"] == 2
    assert res["n_distinct_significant"] == 0


def test_a_sign_flip_between_replicates_is_flagged(mod, tmp_path) -> None:
    """Two runs can agree that something happened and disagree on which way. A p-value
    reported without direction would hide that; `direction_consistent` is the flag."""
    grid = _grid(runs=2, only_a=10, only_b=1)
    for row in grid["rows"]:  # swap the second replicate's two arms
        if row["run"] == 1:
            row["first_word_hits"] = row["first_word_hits"].translate(str.maketrans("01", "10"))
    res = _analyse_grid(mod, tmp_path, grid)
    assert res["distinct"][0]["direction_consistent"] is False


def test_direction_is_consistent_when_it_really_is(mod, tmp_path) -> None:
    """The negative control for the flag above -- otherwise it could be hardcoded False."""
    res = _analyse_grid(mod, tmp_path, _grid(runs=2, only_a=10, only_b=1))
    assert res["distinct"][0]["direction_consistent"] is True


def test_the_committed_onset_verdict_survives_no_correction(mod, tmp_path) -> None:
    """Pins the published conclusion to the published artifact.

    Not a restatement of the numbers -- it asserts the *shape* of the claim that
    docs/benchmarks.md now makes: nothing in the onset grid survives multiplicity
    correction, so no cell of it may be quoted as an established effect.
    """
    res = mod.analyse(_RESULTS / "onset.json")
    survivors = [d for d in res["distinct"] if d["p_max"] < res["bonferroni_alpha"]]
    assert not survivors, (
        "a cell of the onset grid now survives Bonferroni; docs/benchmarks.md says "
        f"none does and must be rewritten: {[d['comparison'] for d in survivors]}"
    )


def test_the_two_replicated_uncorrected_signals_still_point_the_same_way(mod, tmp_path) -> None:
    """The one directional statement the page does make: where the lead-in reaches
    uncorrected significance in both runs, it makes the opening word *worse*, not
    better. If that ever flips, the page's reading of the mechanism is wrong."""
    res = mod.analyse(_RESULTS / "onset.json")
    held = [d for d in res["distinct"] if d["significant_runs"] == d["runs"]]
    assert held, "no comparison holds in both replicates any more"
    for d in held:
        assert all(a > b for a, b in zip(d["baseline_wins_per_run"], d["cell_wins_per_run"])), (
            f"{d['comparison']} now favours the lead-in; docs/benchmarks.md says the "
            "replicated signals all run the other way"
        )
