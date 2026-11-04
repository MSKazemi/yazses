"""Software-only safety tests for a deliberately artificial MI EEG replay.

These tests verify code invariants, not motor-imagery classification accuracy.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "hci_eeg_mi_synthetic.py"


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("hci_eeg_mi_synthetic", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


M = _load()


def test_repeatable_seed_and_different_seed() -> None:
    assert M.run(4) == M.run(4)
    assert M.run(4) != M.run(5)


def test_all_outputs_label_synthetic_and_refuse_real_eeg_claims() -> None:
    report = M.run(0)
    assert report["synthetic"] and report["research_only"]
    assert "NOT proof of brain decoding" in report["notice"]
    assert "human" in " ".join(report["limitations"]).lower()
    assert report["scores"]["false_activations_per_hour"] is None
    assert report["scores"]["synthetic_control_exposure_s"] > 0
    assert "short" in report["scores"]["false_rate_note"]


def test_the_intentionally_adversarial_drift_fires_a_false_candidate() -> None:
    """Demonstrates a failure, NOT a successful EEG decoder."""
    r = M.run(0)
    assert r["scores"]["imagery_hits"] == {"numerator": 2, "denominator": 2}
    assert r["scores"]["false_candidates_by_control"]["drift_rest"] >= 1
    assert r["scores"]["false_candidates_total"] >= 1


def test_ocular_muscle_dropout_and_flatline_cannot_emit_candidates() -> None:
    report = M.run(0)
    false = report["scores"]["false_candidates_by_control"]
    for control in ("blink", "clench", "speaking", "dropout", "flatline"):
        assert false[control] == 0, control
    rejected = report["events"]["abstention_reasons"]
    for reason in ("ocular_artifact", "muscle_artifact", "missing_or_nonfinite", "flatline"):
        assert rejected[reason] > 0, reason


def test_future_mutation_does_not_change_earlier_candidates_or_calibration() -> None:
    data = M.generate(0)
    before = M.replay(data)
    changed = copy.deepcopy(data)
    cut = 42 * M.FS
    for channel in changed["channels"].values():
        channel[cut:] = [0.0] * (len(channel) - cut)
    after = M.replay(changed)
    assert before["reference_power"] == after["reference_power"]
    assert [v for v in before["proposals"] if v["t_s"] <= 42] == [
        v for v in after["proposals"] if v["t_s"] <= 42
    ]


def test_external_stop_blocks_every_later_candidate() -> None:
    stopped = M.run(0, stop_at_s=33.0)
    assert stopped["events"]["abstention_reasons"]["external_stop"] > 0
    assert all(e["t_s"] < 33.0 for e in stopped["events"]["proposals"])
    assert stopped["scores"]["false_activations_per_hour"] is None
    assert stopped["scores"]["imagery_hits"]["denominator"] == 1


def test_quality_gate_rejects_missing_nan_and_a_recent_flatline() -> None:
    d = M.generate(0)
    c = d["channels"]
    assert M.feature_at(c, 8 * M.FS)[0] is not None
    invalid = copy.deepcopy(c)
    invalid["c3"][790] = None
    assert M.feature_at(invalid, 800) == (None, "missing_or_nonfinite")
    invalid["c3"][790] = math.nan
    assert M.feature_at(invalid, 800) == (None, "missing_or_nonfinite")
    flat = copy.deepcopy(c)
    flat["c3"][775:800] = [0.0] * 25
    assert M.feature_at(flat, 800) == (None, "flatline")


def test_detector_never_receives_ground_truth_labels() -> None:
    d = M.generate(0)
    r1 = M.replay(d)
    d["blocks"] = [dict(b, label="other_label") for b in d["blocks"]]
    r2 = M.replay(d)
    assert r1 == r2, "inference must never use a ground-truth segment label"


def test_cli_produces_json_without_network_sensor_or_model() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    for keyword in ("import socket", "import requests", "import urllib", "import brainflow", "import mne", "import torch"):
        assert keyword not in source
    p = subprocess.run([sys.executable, str(SCRIPT), "--seed", "0"],
                       capture_output=True, text=True, check=True, timeout=30)
    report = json.loads(p.stdout)
    assert report == M.run(0)
    assert "SYNTHETIC" not in p.stderr


@pytest.mark.parametrize("seed", [0, 1, 2, 7])
def test_all_candidate_timestamps_are_sorted_and_bounded(seed: int) -> None:
    report = M.run(seed)
    times = [item["t_s"] for item in report["events"]["proposals"]]
    assert times == sorted(times)
    assert all(0 <= t <= sum(duration for _, duration, _ in M.BLOCKS) for t in times)
    assert report["scores"]["false_candidates_total"] >= 0
