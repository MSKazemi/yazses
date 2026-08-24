"""`probes/largev3_repeat.py::summarise` — the claim the probe exists to test.

The probe answers whether `large-v3`'s run-to-run WER spread on LibriSpeech
`test-other` is confined to **insertions**. That is a claim about three error classes
at once: insertions may move, substitutions and deletions may not. An earlier version
of the summary reported the spread of insertions and substitutions and left deletions
in the per-run rows, which would have let a reader check two thirds of a claim and
quote all of it.

`summarise` is pure over the run rows, so it is tested on synthetic rows rather than an
hour of decode, and — because it is pure — a committed artifact's summary can be
re-derived from its own `runs` array without re-measuring.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.benchmark_deps import load

ARTIFACT = Path(__file__).resolve().parents[1] / "paper" / "results" / "probes" / \
    "largev3-instability-test-other.json"


@pytest.fixture(scope="module")
def mod():
    return load("largev3_repeat", "probes/largev3_repeat.py")


def _runs(*triples: tuple[float, int, int, int]) -> list[dict]:
    return [
        {"wer": w, "insertions": i, "substitutions": s, "deletions": d}
        for w, i, s, d in triples
    ]


def test_it_reports_the_spread_of_all_three_error_classes(mod) -> None:
    out = mod.summarise(_runs((6.53, 141, 87, 15), (7.69, 184, 87, 15)))
    assert out["insertions_spread"] == 43
    assert out["substitutions_spread"] == 0
    assert out["deletions_spread"] == 0
    assert out["wer_spread"] == 1.16


def test_deletions_are_summarised_not_only_recorded(mod) -> None:
    """The regression this file was written for. Deletions in the per-run rows and
    absent from the summary is the shape that lets the claim be half-checked."""
    out = mod.summarise(_runs((6.53, 141, 87, 15), (7.69, 184, 87, 15)))
    for field in ("deletions_min", "deletions_max", "deletions_spread"):
        assert field in out, f"summary omits {field}: {sorted(out)}"


def test_the_headline_flag_is_true_only_when_both_classes_hold_still(mod) -> None:
    steady = mod.summarise(_runs((6.53, 141, 87, 15), (7.69, 184, 87, 15)))
    assert steady["non_insertion_errors_constant"] is True

    subs_moved = mod.summarise(_runs((6.53, 141, 87, 15), (7.69, 184, 88, 15)))
    assert subs_moved["non_insertion_errors_constant"] is False

    dels_moved = mod.summarise(_runs((6.53, 141, 87, 15), (7.69, 184, 87, 16)))
    assert dels_moved["non_insertion_errors_constant"] is False, (
        "a deletion that moved must refute 'only the hallucination is unstable' just "
        "as a substitution does -- a deletion is a word the model failed to recognise, "
        "not a word it invented."
    )


def test_a_single_run_summarises_to_zero_spread_rather_than_failing(mod) -> None:
    """`repeats=1` is a legitimate invocation and must not raise: a spread of zero
    over one run is honest, an exception mid-probe throws away the decode."""
    out = mod.summarise(_runs((6.53, 141, 87, 15)))
    assert out["wer_spread"] == 0.0
    assert out["non_insertion_errors_constant"] is True


@pytest.mark.skipif(not ARTIFACT.exists(), reason="probe has not been run yet")
def test_the_committed_artifact_summary_matches_its_own_runs(mod) -> None:
    """A summary is a claim about the rows beside it. Re-derive rather than trust."""
    result = json.loads(ARTIFACT.read_text(encoding="utf-8"))["result"]
    assert mod.summarise(result["runs"]) == result["summary"]
