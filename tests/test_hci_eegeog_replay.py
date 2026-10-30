"""Synthetic P0/P1 replay for the EEG/EOG feasibility protocol (#696): the pipeline, not the physiology.

Everything is generated or hand-built here. These tests prove the CODE: determinism, causality, that
thresholds come only from the calibration block, the refractory and minimum-hold rules, that artifact
rejection can only remove candidates, and that no hourly rate is printed from too little exposure.
They say nothing about whether EEG or EOG can serve as a switch, and no test asserts that a detector
is "good".
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "hci_eegeog_replay.py"


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("hci_eegeog_replay", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


E = _load()
FS = int(E.PARAMS["fs_hz"])


# -- determinism and the report's honesty ------------------------------------------------


def test_the_same_seed_gives_the_same_report_and_another_seed_a_different_one() -> None:
    a = json.dumps(E.run(3), sort_keys=True)
    assert a == json.dumps(E.run(3), sort_keys=True)
    assert a != json.dumps(E.run(4), sort_keys=True)


def test_the_report_says_it_is_synthetic_and_claims_nothing_about_eeg() -> None:
    report = E.run(0)
    assert report["synthetic"] is True
    assert "SYNTHETIC DATA" in report["notice"]
    assert "nothing about whether EEG or EOG can be used as a switch" in report["notice"]
    assert any("Nothing here supports a claim about real EEG or EOG" in s for s in report["limitations"])
    assert report["parameters"]["noise_sigma"] == 1.0, "every choice is recorded so it can be challenged"


def test_no_hourly_rate_is_ever_printed_for_generated_data() -> None:
    for seed in range(4):
        for config in E.run(seed)["p1_injected"].values():
            rate = config["false_activations_per_hour"]
            assert rate["value"] is None
            assert "invented number" in rate["note"]
            assert rate["exposure_s"] == 240 and rate["minimum_exposure_s"] == E.DEFAULT_MIN_EXPOSURE_S
    # Even with plenty of exposure the helper refuses: injected bursts are not a rate.
    assert E._per_hour(5, 100 * E.DEFAULT_MIN_EXPOSURE_S)["value"] is None


def test_every_count_carries_its_denominator() -> None:
    for config in E.run(1)["p1_injected"].values():
        assert config["hits"]["denominator"] == 10 and config["missed_switches"]["denominator"] == 10
        false = config["false_activations"]
        assert false["blink"]["denominator"] == 10 and false["clench"]["denominator"] == 10
        assert false["rest"]["denominator"] == 60 and false["speaking"]["denominator"] == 60
        assert false["between_events"]["denominator"] == 120
        assert config["hits"]["numerator"] + config["missed_switches"]["numerator"] == 10


def test_no_count_exceeds_its_denominator_over_many_seeds() -> None:
    for seed in range(25):
        for name, config in E.run(seed)["p1_injected"].items():
            false = config["false_activations"]
            for klass in ("blink", "clench", "rest", "speaking", "between_events"):
                assert false[klass]["numerator"] <= false[klass]["denominator"], (seed, name, klass)
            total = sum(false[k]["numerator"] for k in ("blink", "clench", "rest", "speaking", "between_events"))
            assert false["total"] == total, (seed, name)
            assert config["hits"]["numerator"] <= 10
            # every candidate is a hit, a classified false activation, or reported as unattributed
            assert config["candidates"] == config["hits"]["numerator"] + total + config["unattributed_candidates"], (seed, name)


# -- the generator ------------------------------------------------------------------------


def test_ground_truth_lists_exactly_the_injected_events() -> None:
    data = E.synthesize(0)
    kinds = [e["kind"] for e in data["events"]]
    assert kinds.count("blink") == kinds.count("clench") == kinds.count("intended") == 10
    assert len(kinds) == 30
    times = [e["t_s"] for e in data["events"]]
    assert times == sorted(times)


def test_a_noise_only_stream_has_no_events() -> None:
    data = E.synthesize(0, inject=False)
    assert data["events"] == []


def test_calibration_noise_does_not_depend_on_what_comes_after_it() -> None:
    # Thresholds are set from the calibration block, so it must be identical however the rest is built.
    full = E.synthesize(5)
    short = E.synthesize(5, E.BLOCKS[:2])
    n = 60 * FS
    for name in E.CHANNELS:
        assert full["channels"][name][:n] == short["channels"][name][:n]


def test_thresholds_come_from_the_calibration_block_only() -> None:
    data = E.synthesize(2)
    env = {n: E.envelope(data["channels"][n], FS, E.PARAMS["envelope_window_s"]) for n in E.CHANNELS}
    base = E.thresholds_from(env, 0, 60 * FS, E.PARAMS["threshold_k"])
    tampered = {n: e[: 60 * FS] + [999.0] * (len(e) - 60 * FS) for n, e in env.items()}
    assert E.thresholds_from(tampered, 0, 60 * FS, E.PARAMS["threshold_k"]) == base
    assert E.run(2)["thresholds"] == {k: round(v, 6) for k, v in base.items()}


def test_the_envelope_is_causal() -> None:
    x = [float(i % 7) for i in range(500)]
    y = list(x)
    y[300:] = [1000.0] * 200  # change the future
    a, b = E.envelope(x, FS, 0.1), E.envelope(y, FS, 0.1)
    assert a[:300] == b[:300]
    assert a[300] != b[300]


# -- the detector rules, on hand-built envelopes ------------------------------------------


def _flat(n: int, level: float = 0.0) -> list[float]:
    return [level] * n


def _bump(n: int, start: int, length: int, level: float = 10.0) -> list[float]:
    env = _flat(n)
    env[start : start + length] = [level] * length
    return env


THR = {"eeg": 1.0, "eog": 1.0, "emg": 1.0}
HOLD = int(round(E.PARAMS["min_hold_s"] * FS))


def test_a_crossing_shorter_than_the_minimum_hold_never_fires() -> None:
    env = {"eeg": _bump(1000, 200, HOLD - 1), "eog": _flat(1000), "emg": _flat(1000)}
    assert E.detect(env, THR, FS, 0, 1000, artifact_aware=False) == []
    env["eeg"] = _bump(1000, 200, HOLD)
    assert len(E.detect(env, THR, FS, 0, 1000, artifact_aware=False)) == 1


def test_two_crossings_inside_the_refractory_period_fire_once() -> None:
    eeg = _bump(2000, 200, 40)  # fires at sample 219 (after the minimum hold); quiet until sample 319
    eeg[250:290] = [10.0] * 40  # a second crossing wholly inside the quiet period
    env = {"eeg": eeg, "eog": _flat(2000), "emg": _flat(2000)}
    assert len(E.detect(env, THR, FS, 0, 2000, artifact_aware=False)) == 1
    far = _bump(2000, 200, 40)
    far[900:940] = [10.0] * 40
    env["eeg"] = far
    assert len(E.detect(env, THR, FS, 0, 2000, artifact_aware=False)) == 2


def test_artifact_awareness_removes_a_candidate_next_to_an_eog_or_emg_burst() -> None:
    for channel in ("eog", "emg"):
        env = {"eeg": _bump(1000, 400, 40), "eog": _flat(1000), "emg": _flat(1000)}
        env[channel] = _bump(1000, 390, 30)
        assert len(E.detect(env, THR, FS, 0, 1000, artifact_aware=False)) == 1
        assert E.detect(env, THR, FS, 0, 1000, artifact_aware=True) == []


def test_the_detector_is_causal_a_later_burst_cannot_remove_an_earlier_candidate() -> None:
    n = 1000
    base = {"eeg": _bump(n, 400, 40), "eog": _flat(n), "emg": _flat(n)}
    decided = E.detect(base, THR, FS, 0, n, artifact_aware=True)
    assert len(decided) == 1
    fired_at = int(round(decided[0] * FS))
    # An EMG burst that begins AFTER the decision sample must not change what was already decided.
    later = {**base, "emg": _bump(n, fired_at + 1, 20)}
    assert E.detect(later, THR, FS, 0, n, artifact_aware=True) == decided
    # And the decision does not depend on anything after its own sample, for either detector.
    for aware in (False, True):
        full = E.detect(base, THR, FS, 0, n, artifact_aware=aware)
        truncated = E.detect(base, THR, FS, 0, fired_at + 1, artifact_aware=aware)
        assert truncated == full


def test_one_sustained_burst_gives_one_candidate_not_a_stream_of_them() -> None:
    n = 3000
    env = {"eeg": _bump(n, 200, 1500), "eog": _flat(n), "emg": _flat(n)}  # 15 s above threshold
    assert len(E.detect(env, THR, FS, 0, n, artifact_aware=False)) == 1


def test_the_detector_re_arms_after_the_envelope_falls_back() -> None:
    n = 3000
    eeg = _bump(n, 200, 40)
    eeg[1400:1440] = [10.0] * 40  # well after the refractory period, with a gap below threshold between
    env = {"eeg": eeg, "eog": _flat(n), "emg": _flat(n)}
    assert len(E.detect(env, THR, FS, 0, n, artifact_aware=False)) == 2


def test_artifact_awareness_keeps_a_clean_candidate() -> None:
    env = {"eeg": _bump(1000, 400, 40), "eog": _flat(1000), "emg": _flat(1000)}
    assert E.detect(env, THR, FS, 0, 1000, artifact_aware=True) == E.detect(env, THR, FS, 0, 1000, artifact_aware=False)


def test_artifact_rejection_can_only_remove_candidates_never_add_or_delay_them() -> None:
    for seed in range(6):
        data = E.synthesize(seed)
        env = {n: E.envelope(data["channels"][n], FS, E.PARAMS["envelope_window_s"]) for n in E.CHANNELS}
        thr = E.thresholds_from(env, 0, 60 * FS, E.PARAMS["threshold_k"])
        start = int(data["blocks"][1]["start_s"] * FS)
        naive = E.detect(env, thr, FS, start, len(env["eeg"]), artifact_aware=False)
        aware = E.detect(env, thr, FS, start, len(env["eeg"]), artifact_aware=True)
        assert set(aware) <= set(naive), seed
        assert E.score(aware, data)["hits"]["numerator"] <= E.score(naive, data)["hits"]["numerator"]


# -- scoring against ground truth ---------------------------------------------------------


def test_scoring_attributes_candidates_to_the_right_class() -> None:
    data = {
        "events": [
            {"t_s": 10.0, "kind": "intended"},
            {"t_s": 20.0, "kind": "blink"},
            {"t_s": 30.0, "kind": "clench"},
            {"t_s": 40.0, "kind": "intended"},
        ],
        "blocks": [
            {"label": "calibration_rest", "start_s": 0.0, "end_s": 5.0},
            {"label": "rest", "start_s": 5.0, "end_s": 15.0},
            {"label": "speaking", "start_s": 15.0, "end_s": 18.0},
            {"label": "blink", "start_s": 18.0, "end_s": 25.0},
            {"label": "clench", "start_s": 25.0, "end_s": 35.0},
            {"label": "intended", "start_s": 35.0, "end_s": 45.0},
        ],
    }
    out = E.score([10.3, 20.4, 30.2, 6.0, 16.0], data)
    assert out["hits"] == {"numerator": 1, "denominator": 2}
    assert out["missed_switches"]["numerator"] == 1
    false = out["false_activations"]
    assert (false["blink"]["numerator"], false["clench"]["numerator"]) == (1, 1)
    assert (false["rest"]["numerator"], false["speaking"]["numerator"]) == (1, 1)
    assert false["total"] == 4
    assert out["latency_ms"]["n"] == 1 and out["latency_ms"]["median"] == pytest.approx(300.0, abs=0.1)


def test_a_candidate_that_matches_nothing_is_counted_not_dropped() -> None:
    data = {
        "events": [{"t_s": 40.0, "kind": "intended"}],
        "blocks": [
            {"label": "calibration_rest", "start_s": 0.0, "end_s": 5.0},
            {"label": "rest", "start_s": 5.0, "end_s": 15.0},
            {"label": "intended", "start_s": 35.0, "end_s": 45.0},
        ],
    }
    out = E.score([37.0], data)  # inside the intended block, outside any event window
    assert out["candidates"] == 1 and out["unattributed_candidates"] == 1
    assert out["hits"]["numerator"] == 0


# -- plumbing -----------------------------------------------------------------------------


def test_the_p0_stage_reports_plumbing_only() -> None:
    p0 = E.run(0)["p0_noise_only"]
    assert p0["scored_seconds"] == 120
    assert "Says nothing about EEG" in p0["note"]
    # Recompute it independently from a noise-only stream and the calibration-block thresholds.
    noise = E.synthesize(0, (("calibration_rest", 60, 0), ("rest", 120, 0)), inject=False)
    env = {n: E.envelope(noise["channels"][n], FS, E.PARAMS["envelope_window_s"]) for n in E.CHANNELS}
    thr = E.thresholds_from(env, 0, 60 * FS, E.PARAMS["threshold_k"])
    assert p0["candidates"] == len(E.detect(env, thr, FS, 60 * FS, 180 * FS, artifact_aware=False))


def test_the_cli_prints_the_same_json_as_run(capsys: pytest.CaptureFixture[str]) -> None:
    assert E.main(["--seed", "2"]) == 0
    assert json.loads(capsys.readouterr().out) == json.loads(json.dumps(E.run(2)))


def test_a_candidate_inside_a_control_block_but_between_events_is_counted_as_such() -> None:
    data = {
        "events": [{"t_s": 20.0, "kind": "blink"}],
        "blocks": [
            {"label": "calibration_rest", "start_s": 0.0, "end_s": 5.0},
            {"label": "rest", "start_s": 5.0, "end_s": 15.0},
            {"label": "blink", "start_s": 15.0, "end_s": 30.0},
        ],
    }
    out = E.score([16.0, 20.5, 26.0], data)  # 16 and 26 are in the blink block, outside any event window
    false = out["false_activations"]
    assert false["between_events"]["numerator"] == 2
    assert false["blink"]["numerator"] == 1 and false["blink"]["numerator"] <= false["blink"]["denominator"]
    assert out["unattributed_candidates"] == 0


@pytest.mark.parametrize("p,n", [(7, 100), (50, 10), (95, 10), (14, 100), (95, 20)])
def test_the_replay_percentile_is_exact(p: int, n: int) -> None:
    assert E._nearest_rank(list(range(1, n + 1)), p) == max(1, -(-p * n // 100))


def test_the_script_is_offline_clockless_and_dependency_light() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    for token in ("import socket", "import urllib", "import requests", "import time", "datetime", "numpy", "brainflow", "mne", "sklearn"):
        assert token not in text, token
    assert "random.Random(seed)" in text, "randomness must be seeded"
    assert "random.seed(" not in text and "random.random(" not in text
