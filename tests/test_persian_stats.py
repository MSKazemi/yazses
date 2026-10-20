"""FA-05: uncertainty and ZWNJ attribution for the Persian benchmark cells.

The functions are pure, so every expectation here is a hand-computable number rather
than a mock: a known edit distance, an interval that must bracket its own point
estimate, a paired comparison of a model with itself (which must be exactly zero), and
the one case ZWNJ attribution exists for — a hypothesis that differs from the
reference only by a missing U+200C.
"""
from __future__ import annotations

import json

import pytest

from tests.benchmark_deps import load

ZWNJ = "‌"


@pytest.fixture(scope="module")
def stats():
    return load("persian_stats", "persian_stats.py")


def test_word_errors_known_distances(stats):
    assert stats.word_errors("a b c", "a b c") == (0, 3)
    assert stats.word_errors("a b c", "a x c") == (1, 3)  # substitution
    assert stats.word_errors("a b c", "a c") == (1, 3)  # deletion
    assert stats.word_errors("a b", "a b c d") == (2, 2)  # two insertions
    assert stats.word_errors("a b", "") == (2, 2)  # empty hypothesis is all deletions


def test_empty_reference_rows_are_dropped_not_scored(stats):
    counts = stats.per_utterance(["a b", "  "], ["a b", "junk"])
    assert counts == [(0, 2)]


def test_misaligned_inputs_raise(stats):
    with pytest.raises(ValueError, match="align"):
        stats.per_utterance(["a"], [])


def test_bootstrap_brackets_its_point_estimate_and_is_seeded(stats):
    refs = [f"w{i} x{i} y{i} z{i}" for i in range(40)]
    hyps = [r if i % 4 else r.replace("x", "q") for i, r in enumerate(refs)]
    wer, lo, hi = stats.bootstrap_wer(refs, hyps, n=500, seed=7)
    assert wer == pytest.approx(100 * 10 / 160)
    assert lo <= wer <= hi
    assert (wer, lo, hi) == stats.bootstrap_wer(refs, hyps, n=500, seed=7)


def test_perfect_cell_has_a_degenerate_interval(stats):
    refs = ["a b c"] * 10
    assert stats.bootstrap_wer(refs, refs, n=100) == (0.0, 0.0, 0.0)


def test_paired_diff_of_a_model_with_itself_is_exactly_zero(stats):
    refs = [f"a{i} b{i}" for i in range(20)]
    hyps = [r.replace("a", "z") if i % 3 == 0 else r for i, r in enumerate(refs)]
    assert stats.paired_bootstrap_diff(refs, hyps, hyps, n=200) == (0.0, 0.0, 0.0)


def test_paired_diff_excludes_zero_for_a_clearly_worse_model(stats):
    refs = [f"a{i} b{i}" for i in range(50)]
    good = list(refs)
    bad = [r.replace("a", "z") for r in refs]
    diff, lo, hi = stats.paired_bootstrap_diff(refs, bad, good, n=300)
    assert diff == pytest.approx(50.0)
    assert lo > 0 and hi >= diff


def test_zwnj_attribution_isolates_a_dropped_joiner(stats):
    refs = [f"می{ZWNJ}روم رفت"]
    hyps = ["میروم رفت"]  # joiner missing, rest equal
    base, stripped, delta = stats.zwnj_attributable_points(refs, hyps)
    assert base == pytest.approx(50.0)  # 1 of 2 words wrong
    assert stripped == 0.0
    assert delta == pytest.approx(50.0)


def test_zwnj_attribution_is_zero_when_the_errors_are_elsewhere(stats):
    refs = [f"می{ZWNJ}روم رفت"]
    hyps = [f"می{ZWNJ}روم خورد"]
    assert stats.zwnj_attributable_points(refs, hyps)[2] == 0.0


def test_load_hyps_round_trips_a_hyps_out_file(stats, tmp_path):
    p = tmp_path / "h.jsonl"
    rows = [{"id": "r1", "reference": "a b", "hypothesis": "a"}]
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    assert stats.load_hyps(p) == (["r1"], ["a b"], ["a"])
