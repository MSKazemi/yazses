"""Software invariants of the synthetic cross-session EEG harness.

These tests check that splits cannot leak, that normalisation is fitted on the
training rows only, and that the activation arithmetic is right. They say
nothing about real EEG; every number comes from an authored generator.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "hci_eeg_cross_session_synthetic.py"


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("hci_eeg_cross_session_synthetic", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


M = _load()


@pytest.fixture(scope="module")
def small() -> Any:
    return M.generate(seed=3, n_subjects=4, n_sessions=2)


@pytest.fixture(scope="module")
def report() -> dict[str, Any]:
    return M.run(0)


def test_generator_is_seeded_and_pure() -> None:
    a, b, c = M.generate(1, 3, 2), M.generate(1, 3, 2), M.generate(2, 3, 2)
    assert np.array_equal(a.x, b.x) and np.array_equal(a.label, b.label)
    assert not np.array_equal(a.x, c.x)


def test_generator_refuses_too_few_subjects_or_sessions() -> None:
    with pytest.raises(ValueError):
        M.generate(0, 1, 3)
    with pytest.raises(ValueError):
        M.generate(0, 3, 1)


def test_windows_never_straddle_a_block_and_overlap_inside_one(small: Any) -> None:
    blk = M._samples(M.BLOCK_S)
    assert np.all(small.start // blk == small.block)
    assert np.all((small.stop - 1) // blk == small.block)
    assert np.all(small.stop - small.start == M._samples(M.WINDOW_S))
    assert set(np.unique(small.label)) == {M.REST, M.IMAGERY}
    # The hop is shorter than the window, so consecutive windows share samples.
    assert M.HOP_S < M.WINDOW_S


@pytest.mark.parametrize("splitter", ["split_by_subject", "split_by_session"])
def test_disjoint_splits_share_no_window_and_no_sample(small: Any, splitter: str) -> None:
    folds = getattr(M, splitter)(small)
    assert len(folds) >= 2
    tested = np.concatenate([test for _, _, test in folds])
    assert np.array_equal(np.sort(tested), np.arange(len(small))), "folds must partition the windows"
    for _, train, test in folds:
        assert np.intersect1d(train, test).size == 0
        assert M.overlapping_window_pairs(small, train, test) == 0
        if splitter == "split_by_subject":
            assert not set(small.subject[train]) & set(small.subject[test])
        else:
            tr = set(zip(small.subject[train].tolist(), small.session[train].tolist(), strict=True))
            te = set(zip(small.subject[test].tolist(), small.session[test].tolist(), strict=True))
            assert not tr & te


def test_leaky_split_is_detected_as_overlapping(small: Any) -> None:
    """Guards the overlap detector against vacuity: the negative control must trip it."""
    folds = M.split_leaky_windows(small, seed=0)
    assert all(np.intersect1d(train, test).size == 0 for _, train, test in folds)
    assert sum(M.overlapping_window_pairs(small, train, test) for _, train, test in folds) > 0


def test_standardizer_is_fit_on_train_rows_only(small: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    feats = M.bandpower_features(small.x)
    name, train, test = M.split_by_session(small)[0]
    seen: list[np.ndarray] = []
    real = M.fit_standardizer

    def spy(rows: np.ndarray) -> Any:
        seen.append(rows.copy())
        return real(rows)

    monkeypatch.setattr(M, "fit_standardizer", spy)
    poisoned = feats.copy()
    poisoned[test] += 1000.0
    for clf in ("lda", "nearest_neighbour"):
        M.evaluate(small, poisoned, [(name, train, test)], clf)
    assert len(seen) == 2
    for rows in seen:
        assert rows.shape == feats[train].shape
        assert np.array_equal(rows, feats[train]), "test rows reached the normaliser"
    scaler = real(feats[train])
    assert np.allclose(scaler.mean, feats[train].mean(axis=0))


def test_lda_needs_both_classes() -> None:
    with pytest.raises(ValueError):
        M.fit_lda(np.zeros((4, 2)), np.zeros(4, dtype=np.int64))


def test_refractory_period_spaces_activations() -> None:
    times = [M.WINDOW_S + i * 0.5 for i in range(20)]
    ones = [1.0] * 20
    assert M.replay_activations(times, ones, threshold=0.7, consecutive=2, refractory_s=2.0) == [1, 5, 9, 13, 17]
    assert M.replay_activations(times, ones, threshold=0.7, consecutive=2, refractory_s=0.0) == list(range(1, 20, 2))
    assert M.replay_activations(times, [0.69] * 20, threshold=0.7) == []


def test_replay_is_causal_and_rejects_time_travel() -> None:
    with pytest.raises(ValueError):
        M.replay_activations([2.0, 1.0], [1.0, 1.0])
    # A below-threshold window breaks the run.
    assert M.replay_activations([1, 2, 3, 4], [1.0, 0.0, 1.0, 0.0], consecutive=2, refractory_s=0.0) == []


def test_exact_poisson_upper_bound() -> None:
    assert math.isclose(M.poisson_upper_bound(0), -math.log(0.05), rel_tol=1e-9)
    assert math.isclose(M.poisson_upper_bound(1), 4.743865, rel_tol=1e-5)
    assert math.isclose(M.poisson_upper_bound(5), 10.51303, rel_tol=1e-5)


def test_false_activations_per_hour_counts_only_rest(small: Any) -> None:
    proba = np.where(small.label == M.REST, 0.0, 1.0)
    clean = M.activation_metrics(small, proba)
    assert clean["false_activations"] == 0
    assert clean["hits"] == clean["imagery_blocks"] > 0
    recordings = 4 * 2  # n_subjects x n_sessions of the fixture
    rest_blocks = len(np.unique(small.block[small.label == M.REST])) * recordings
    assert clean["synthetic_rest_exposure_s"] == pytest.approx(M.BLOCK_S * rest_blocks)
    noisy = M.activation_metrics(small, np.ones(len(small)))
    assert noisy["false_activations"] > 0
    assert noisy["false_activations_per_hour"] == pytest.approx(
        noisy["false_activations"] * 3600.0 / noisy["synthetic_rest_exposure_s"])
    assert noisy["false_activations_per_hour_upper95"] > noisy["false_activations_per_hour"]


def test_report_is_deterministic_and_labelled_synthetic(report: dict[str, Any]) -> None:
    assert report == M.run(0)
    assert report["synthetic"] and report["research_only"]
    assert "not human EEG" in report["notice"]
    assert "#696" in report["predecessor"]
    body = {k: v for k, v in report.items() if k != "report_sha256"}
    assert len(report["report_sha256"]) == 64
    assert json.loads(json.dumps(body)) == body


def test_disjoint_schemes_report_zero_overlap_and_leaky_reports_some(report: dict[str, Any]) -> None:
    schemes = report["schemes"]
    for name in ("subject_disjoint", "session_disjoint"):
        assert schemes[name]["lda"]["overlapping_train_test_window_pairs"] == 0
        assert not schemes[name]["negative_control"]
    assert schemes["leaky_window_split"]["lda"]["overlapping_train_test_window_pairs"] > 0
    assert schemes["leaky_window_split"]["negative_control"]


def test_leaky_negative_control_inflates_nearest_neighbour_accuracy(report: dict[str, Any]) -> None:
    """HYPOTHESIS pinned on seed 0: overlapping windows let 1-NN find a near copy."""
    assert report["leak_inflation_vs_session_disjoint"]["nearest_neighbour"] >= 0.05


def test_authored_non_responder_is_reported_as_failed(report: dict[str, Any]) -> None:
    nr = report["generator"]["non_responder_subject"]
    assert nr in report["schemes"]["subject_disjoint"]["lda"]["failed_subjects"]
    assert str(nr) in report["schemes"]["subject_disjoint"]["lda"]["per_subject_balanced_accuracy"]


def test_cli_writes_utf8_json(tmp_path: Path) -> None:
    out = tmp_path / "r.json"
    assert M.main(["--seed", "1", "--subjects", "3", "--sessions", "2", "--out", str(out)]) == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["generator"]["subjects"] == 3 and data["synthetic"]


def test_harness_has_no_network_or_heavy_imports() -> None:
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    names = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    names |= {(n.module or "").split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert not names & {"socket", "urllib", "http", "requests", "httpx", "sklearn", "torch", "scipy",
                        "mne", "moabb", "brainflow"}
