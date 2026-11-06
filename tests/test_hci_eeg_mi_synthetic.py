"""Software-only safety tests for a deliberately artificial MI EEG replay.

These tests verify code invariants, not motor-imagery classification accuracy.
"""
from __future__ import annotations

import copy
import hashlib
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


# --- Drift-amplitude sweep (research-only, synthetic; follows from authored thresholds) ---

# sha256 of `python scripts/hci_eeg_mi_synthetic.py --seed 0` stdout (indent=2, sorted keys).
# Seen identical on CPython 3.12.3, 3.13.15 and 3.14.7. A change here means the default
# synthetic output changed; update the doc table and this hash deliberately, never silently.
SEED0_DEFAULT_SHA256 = "64ad91e04d8c732a6c4661470a37134c69b11d3d94793e9a762ff7edb556d9b6"


def test_default_output_is_byte_identical_golden_hash() -> None:
    text = json.dumps(M.run(0), indent=2, sort_keys=True) + "\n"
    assert hashlib.sha256(text.encode("utf-8")).hexdigest() == SEED0_DEFAULT_SHA256


def test_cli_default_stdout_matches_golden_hash() -> None:
    p = subprocess.run([sys.executable, str(SCRIPT), "--seed", "0"],
                       capture_output=True, text=True, check=True, timeout=30)
    assert hashlib.sha256(p.stdout.encode("utf-8")).hexdigest() == SEED0_DEFAULT_SHA256


def test_drift_amplitude_none_equals_authored_value() -> None:
    authored = next(amp for label, _, amp in M.BLOCKS if label == "drift_rest")
    assert M.run(3) == M.run(3, drift_amplitude=None)
    assert M.generate(3) == M.generate(3, drift_amplitude=authored)


def test_drift_sweep_is_monotone_fires_at_050_not_at_085() -> None:
    seeds = range(5)
    low = M.drift_sweep([0.50], seeds)[0]
    high = M.drift_sweep([0.85], seeds)[0]
    assert low == {"drift_amplitude": 0.50, "seeds_firing": 5, "seeds": 5}
    assert high == {"drift_amplitude": 0.85, "seeds_firing": 0, "seeds": 5}
    rows = M.drift_sweep([0.30, 0.50, 0.70, 0.75, 0.80, 0.90, 1.00], seeds)
    firing = [r["seeds_firing"] for r in rows]
    assert firing == sorted(firing, reverse=True), firing


def test_drift_sweep_is_deterministic_and_leaves_other_controls_clean() -> None:
    assert M.drift_sweep([0.5, 0.8], range(3)) == M.drift_sweep([0.5, 0.8], range(3))
    for amp in (0.5, 0.85):
        scores = M.run(0, drift_amplitude=amp)["scores"]
        assert scores["imagery_hits"] == {"numerator": 2, "denominator": 2}
        others = {k: v for k, v in scores["false_candidates_by_control"].items() if k != "drift_rest"}
        assert not any(others.values()), others


def test_cli_drift_amplitude_and_sweep_flags() -> None:
    one = subprocess.run([sys.executable, str(SCRIPT), "--seed", "1", "--drift-amplitude", "0.85"],
                         capture_output=True, text=True, check=True, timeout=30)
    assert json.loads(one.stdout) == M.run(1, drift_amplitude=0.85)
    sweep = subprocess.run([sys.executable, str(SCRIPT), "--sweep-drift", "0.5,0.85", "--sweep-seeds", "2"],
                           capture_output=True, text=True, check=True, timeout=60)
    body = json.loads(sweep.stdout)
    assert body["synthetic"] and "not physiology" in body["note"]
    assert body["sweep"] == M.drift_sweep([0.5, 0.85], range(2))


# --- Reference-channel ablation, reliability and unknown-state rates (synthetic only) ---

ARTIFACT_BLOCKS = ("blink", "clench", "speaking")


def test_default_arguments_keep_the_pinned_output() -> None:
    """The new knobs at their defaults must not perturb the hash-pinned report."""
    assert M.run(0, reference_gate=True, artifact_leakage=None) == M.run(0)
    assert M.generate(2, artifact_leakage=1.0) == M.generate(2)


def test_no_reference_channel_ignores_eog_and_emg_entirely() -> None:
    data = M.generate(0)
    for name in ("eog", "emg"):
        data["channels"][name] = [None] * len(data["channels"][name])
    with pytest.raises(ValueError, match="no usable calibration"):
        M.replay(data)   # with the gate on, a missing reference fails closed at calibration
    ungated = M.replay(data, reference_gate=False)
    assert ungated["eligible_windows"] > 0
    assert "ocular_artifact" not in ungated["abstention_reasons"]
    assert "muscle_artifact" not in ungated["abstention_reasons"]


def test_no_reference_run_is_labelled_and_keeps_inference_label_free() -> None:
    report = M.run(0, reference_gate=False)
    assert report["reference_channel"] == "absent: EOG/EMG quality gate removed"
    d = M.generate(0)
    r1 = M.replay(d, reference_gate=False)
    d["blocks"] = [dict(b, label="x") for b in d["blocks"]]
    assert r1 == M.replay(d, reference_gate=False)


def test_leakage_sweep_reports_per_block_and_labelled_hourly_arithmetic() -> None:
    body = M.leakage_sweep([1.0, 8.0], range(2))
    assert body["synthetic"] and "not an estimate" in body["rate_note"]
    for row in body["rows"]:
        for gate in ("reference_gate_on", "reference_gate_off"):
            per = row[gate]["false_candidates_by_block"]
            assert set(per) == set(ARTIFACT_BLOCKS)
            for block in ARTIFACT_BLOCKS:
                count = per[block]
                exposure_s = 2 * 8
                assert row[gate]["synthetic_rate_per_hour"][block] == round(3600 * count / exposure_s, 3)
            assert 0.0 <= row[gate]["abstention_rate"] <= 1.0
            assert 0.0 <= row[gate]["unknown_state_rate"] <= 1.0
    authored = body["rows"][0]
    assert authored["artifact_leakage"] == 1.0
    # With the gate on, the scripted artifacts never fire at the authored leakage.
    assert not any(authored["reference_gate_on"]["false_candidates_by_block"].values())
    # Removing the gate removes the ocular/muscle abstentions.
    assert authored["reference_gate_off"]["abstention_rate"] < authored["reference_gate_on"]["abstention_rate"]


def test_gate_off_at_the_authored_leakage_gives_no_artifact_false_candidates() -> None:
    # The results page's correction: blink/clench/speaking stay at 0 at the authored
    # leakage even with the EOG/EMG gate removed, so the gate is not what keeps them at 0.
    authored = M.leakage_sweep([1.0], range(2))["rows"][0]
    assert authored["reference_gate_off"]["false_candidates_by_block"] == {
        "blink": 0, "clench": 0, "speaking": 0}


def test_nyquist_rate_clench_adds_nothing_at_10_hz() -> None:
    # Clench alternates sign every sample (50 Hz at FS=100), which the 10 Hz
    # quadrature projection cancels over a whole 1 s window.
    assert M._power_10hz([2.5 * (-1) ** j for j in range(M.FS)]) < 1e-20


def test_state_summary_partitions_every_post_calibration_window() -> None:
    s = M.state_summary(M.generate(0))
    assert s["abstained"] + s["candidate_band"] + s["unknown_band"] + s["rest_band"] == s["windows"]
    assert s["windows"] == 416
    assert s["abstained"] == 96   # documented seed-0 figure, gate on
    assert s["abstention_rate"] == round(96 / 416, 6)
    assert s["unknown_state_rate"] == round(s["unknown_band"] / s["windows"], 6)


def test_reliability_fits_on_train_seeds_and_scores_held_out_seeds_only() -> None:
    rel = M.reliability(range(0, 3), range(3, 5), bins=5)
    assert rel["train_seeds"] == [0, 1, 2] and rel["test_seeds"] == [3, 4]
    assert not set(rel["train_seeds"]) & set(rel["test_seeds"])
    assert "uncalibrated" in rel["note"]
    table = rel["held_out_raw_bins"]
    assert len(table) == 5
    assert sum(b["count"] for b in table) == rel["held_out_windows"]
    for b in table:
        if b["count"]:
            assert 0.0 <= b["mean_score"] <= 1.0 and 0.0 <= b["imagery_fraction"] <= 1.0
    assert 0.0 <= rel["held_out_ece_raw"] <= 1.0
    assert 0.0 <= rel["held_out_ece_binned"] <= 1.0
    # The fitted map must depend on training seeds only: changing the test set leaves it unchanged.
    assert rel["fitted_bin_map"] == M.reliability(range(0, 3), range(7, 9), bins=5)["fitted_bin_map"]


def test_reliability_rejects_overlapping_seed_sets() -> None:
    with pytest.raises(ValueError, match="disjoint"):
        M.reliability(range(0, 3), range(2, 4))


def test_ece_is_zero_for_a_perfectly_calibrated_toy_and_positive_otherwise() -> None:
    assert M.expected_calibration_error([0.0, 0.0, 1.0, 1.0], [0, 0, 1, 1], bins=2) == 0.0
    assert M.expected_calibration_error([0.9, 0.9], [0, 0], bins=10) == pytest.approx(0.9)


def test_cli_ablation_and_reliability_flags() -> None:
    one = subprocess.run([sys.executable, str(SCRIPT), "--seed", "0", "--no-reference-channel"],
                         capture_output=True, text=True, check=True, timeout=30)
    assert json.loads(one.stdout) == M.run(0, reference_gate=False)
    sweep = subprocess.run([sys.executable, str(SCRIPT), "--sweep-leakage", "1,8", "--sweep-seeds", "2"],
                           capture_output=True, text=True, check=True, timeout=60)
    assert json.loads(sweep.stdout) == M.leakage_sweep([1.0, 8.0], range(2))
    rel = subprocess.run([sys.executable, str(SCRIPT), "--reliability", "--sweep-seeds", "4",
                          "--train-seeds", "2"], capture_output=True, text=True, check=True, timeout=60)
    assert json.loads(rel.stdout) == M.reliability(range(0, 2), range(2, 4))
