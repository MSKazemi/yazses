"""Metric code for the camera/gaze comparison protocol (#695): what it computes and what it refuses.

Every number here is constructed in this file with a known answer. These tests prove the CODE
(the geometry, the percentile rule, the leakage guard, the report shape) and say nothing about how
well any gaze backend works.
"""

from __future__ import annotations

import copy
import importlib.util
import math
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "hci_gaze_compare.py"


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("hci_gaze_compare", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolves annotations through sys.modules
    spec.loader.exec_module(module)
    return module


G = _load()


# -- percentiles ------------------------------------------------------------------------


def test_nearest_rank_returns_an_observed_value() -> None:
    values = [5.0, 1.0, 3.0, 2.0, 4.0]
    assert G.nearest_rank(values, 50) == 3.0
    assert G.nearest_rank(values, 100) == 5.0
    assert G.nearest_rank(values, 20) == 1.0
    assert G.nearest_rank(values, 95) in values


def test_p95_of_few_points_is_the_maximum_not_an_extrapolation() -> None:
    # With fewer than 20 points the 95th percentile IS the largest observed value; the summary
    # says n so a reader can see that.
    out = G.summarize_errors([1.0, 2.0, 3.0])
    assert out == {"n": 3, "median": 2.0, "p95": 3.0}


def test_an_empty_sample_is_none_not_zero() -> None:
    assert G.summarize_errors([]) == {"n": 0, "median": None, "p95": None}


@pytest.mark.parametrize("bad", [0, -5, 101])
def test_nearest_rank_rejects_a_bad_percentile(bad: float) -> None:
    with pytest.raises(ValueError):
        G.nearest_rank([1.0], bad)


# -- angular error ----------------------------------------------------------------------


def test_angular_error_matches_a_hand_computed_case() -> None:
    geometry = G.Geometry(pixel_pitch_mm=0.25, viewing_distance_mm=600)
    # 100 px * 0.25 mm = 25 mm; atan(25 / 600) = 2.3862... degrees
    assert G.angular_error_deg(100, geometry) == pytest.approx(math.degrees(math.atan(25 / 600)))
    assert G.angular_error_deg(100, geometry) == pytest.approx(2.386, abs=1e-3)


def test_an_offset_equal_to_the_distance_is_forty_five_degrees() -> None:
    geometry = G.Geometry(pixel_pitch_mm=1.0, viewing_distance_mm=1000)
    assert G.angular_error_deg(1000, geometry) == pytest.approx(45.0)
    assert G.angular_error_deg(0, geometry) == 0.0


def test_there_is_no_angle_without_the_geometry() -> None:
    with pytest.raises(G.MissingGeometry):
        G.angular_error_deg(10, None)


@pytest.mark.parametrize("pitch,distance", [(0, 600), (-1, 600), (0.25, 0), (float("nan"), 600), (0.25, float("inf"))])
def test_a_bad_geometry_is_refused(pitch: float, distance: float) -> None:
    with pytest.raises(ValueError):
        G.Geometry(pitch, distance)


def test_a_session_without_geometry_reports_pixels_only_and_says_why() -> None:
    pairs = [((0, 0), (3, 4)), ((10, 10), (10, 10))]
    out = G.summarize_session(pairs, None)
    assert out["coordinate_error_px"] == {"n": 2, "median": 0.0, "p95": 5.0}
    assert out["angular_error_deg"]["n"] == 0
    assert out["angular_error_deg"]["median"] is None
    assert "geometry" in out["angular_error_deg"]["reason"]


def test_a_session_with_geometry_reports_both() -> None:
    geometry = G.Geometry(0.25, 600)
    out = G.summarize_session([((0, 0), (3, 4))], geometry)
    assert out["coordinate_error_px"]["median"] == 5.0
    assert out["angular_error_deg"]["n"] == 1
    assert out["angular_error_deg"]["median"] == pytest.approx(math.degrees(math.atan(5 * 0.25 / 600)))


# -- leakage ----------------------------------------------------------------------------


def _rec(participant: str, session: str, split: str) -> dict[str, str]:
    return {"participant": participant, "session": session, "split": split}


def test_a_clean_split_has_no_problems() -> None:
    records = [_rec("p1", "s1", "dev"), _rec("p1", "s1", "dev"), _rec("p2", "s2", "eval")]
    assert G.check_split(records) == []


def test_a_participant_in_both_splits_is_leakage() -> None:
    records = [_rec("p1", "s1", "dev"), _rec("p1", "s2", "eval")]
    problems = G.check_split(records)
    assert any("participant 'p1' appears in both splits" in p for p in problems)


def test_a_session_in_both_splits_is_leakage_even_for_different_participant_labels() -> None:
    records = [_rec("p1", "s1", "dev"), _rec("p2", "s1", "eval")]
    assert any("session 's1' appears in both splits" in p for p in G.check_split(records))


def test_adjacent_frames_of_one_session_cannot_straddle_the_boundary() -> None:
    # Frames 0..9 of one session, the last three assigned to eval: the typical shuffled-frames mistake.
    records = [{"participant": "p1", "session": "s1", "split": "dev" if i < 7 else "eval", "frame": i} for i in range(10)]
    assert G.check_split(records) != []


def test_unknown_split_and_missing_ids_are_reported() -> None:
    problems = G.check_split([{"participant": "p1", "session": "s1", "split": "test"}, {"split": "dev"}])
    assert any("split 'test'" in p for p in problems)
    assert any("missing participant" in p for p in problems)
    assert any("missing session" in p for p in problems)


def test_calibration_and_validation_points_must_be_disjoint() -> None:
    assert G.check_calibration_validation_disjoint([(0, 0), (50, 50)], [(100, 100)]) == []
    problems = G.check_calibration_validation_disjoint([(0, 0), (50, 50)], [(50, 50)])
    assert problems and "(50, 50)" in problems[0]


# -- the report shape -------------------------------------------------------------------


def _good_report() -> dict[str, Any]:
    return {
        "protocol_version": G.PROTOCOL_VERSION,
        "question": "Which backend selects the right coarse target more often?",
        "candidates": [{"name": "mediapipe", "revision_or_hash": "sha256:" + "0" * 64, "licence": "Apache-2.0"}],
        "sessions": {"participants": 0, "devices": 0, "sessions": 0},
        "metrics": {"coordinate_error_px": {"n": 0, "median": None, "p95": None}},
        "negative_results": [],
        "limitations": ["No live study has been run; every figure here is a placeholder."],
        "non_claims": ["no pixel-precision claim", "no emotion, identity or attention inference"],
    }


def test_a_complete_report_validates() -> None:
    assert G.validate_report(_good_report()) == []


@pytest.mark.parametrize("key", list(_good_report()))
def test_each_required_section_is_required(key: str) -> None:
    report = _good_report()
    del report[key]
    assert f"missing {key}" in G.validate_report(report)


def test_a_report_without_limitations_is_incomplete() -> None:
    report = _good_report()
    report["limitations"] = []
    assert any("limitations" in p for p in G.validate_report(report))


def test_a_moving_ref_is_not_a_revision() -> None:
    report = _good_report()
    report["candidates"][0]["revision_or_hash"] = "latest"
    assert any("moving ref" in p for p in G.validate_report(report))
    report["candidates"][0]["revision_or_hash"] = ""
    assert any("lacks revision_or_hash" in p for p in G.validate_report(report))


def test_the_number_of_units_must_be_stated() -> None:
    report = _good_report()
    report["sessions"].pop("participants")
    report["sessions"]["devices"] = True  # a bool is not a count
    problems = G.validate_report(report)
    assert any("sessions.participants" in p for p in problems)
    assert any("sessions.devices" in p for p in problems)


@pytest.mark.parametrize("key", ["frames", "Image", "landmarks", "video", "audio", "embedding"])
def test_raw_data_never_appears_in_a_report_at_any_depth(key: str) -> None:
    report = copy.deepcopy(_good_report())
    report["metrics"]["per_participant"] = [{"id": "p1", key: [1, 2, 3]}]
    assert any("raw or identifying data" in p for p in G.validate_report(report))


def test_the_module_is_offline_and_has_no_clock_or_randomness() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    for token in ("import socket", "import urllib", "import requests", "import random", "time.time", "datetime", "cv2", "mediapipe"):
        assert token not in text, token
