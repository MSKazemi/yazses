"""Regression tests for synthetic BrainFlow transport anomalies (not physiology)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))
_spec = importlib.util.spec_from_file_location(
    "hci_brainflow_integrity_replay", SCRIPT_DIR / "hci_brainflow_integrity_replay.py"
)
assert _spec is not None and _spec.loader is not None
R = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = R
_spec.loader.exec_module(R)


def test_all_synthetic_scenarios_pass_their_frozen_expectations() -> None:
    for seed in range(8):
        report = R.run(seed)
        assert report["all_expectations_met"], report
        assert len(report["scenarios"]) == 9
        assert report["synthetic"] is True
        assert report["physiological_evidence"] is False
        assert report["os_actions_emitted"] is False
        assert report["raw_samples_exported"] is False


def test_same_seed_has_byte_identical_report() -> None:
    assert json.dumps(R.run(12), sort_keys=True) == json.dumps(R.run(12), sort_keys=True)


def test_forward_gap_is_a_failure_even_when_timestamps_increase() -> None:
    scenario = next(x for x in R.run()["scenarios"] if x["scenario"] == "timestamp_jump")
    assert scenario["observed_transport_valid"] is False
    assert "timestamp gap" in scenario["error"]


def test_large_artifact_pulse_is_not_mistaken_for_a_neural_detection() -> None:
    report = R.run()
    scenario = next(x for x in report["scenarios"] if x["scenario"] == "artifact_burst")
    assert scenario["observed_transport_valid"] is True
    assert report["physiological_evidence"] is False


def test_cli_exit_code_and_no_sensor_output(capsys: pytest.CaptureFixture[str]) -> None:
    assert R.main(["--seed", "2"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["seed"] == 2
    assert output["all_expectations_met"]
    assert "channels" not in output  # raw matrix is never serialized


def test_negative_seed_refused() -> None:
    with pytest.raises(ValueError, match="nonnegative"):
        R.run(-1)
