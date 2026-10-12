"""The gaze field-measurement report: a schema, a golden file, and nothing personal (#399).

Issue #104 collects field evidence about webcam gaze, and so far it has collected
anecdotes. `src/yazses/eyeeval/gaze_field.py` turns a local session into a fixed-schema
document of derived numbers that two testers' reports can be compared on. This file holds
it to the four things the issue asks for:

* **a documented schema, pinned by a golden file** — the whole document, so a field
  appearing or vanishing shows up in a diff rather than in a report somebody publishes;
* **empty and partial sessions** — every key is present even with no data, each unmeasured
  figure is an explicit ``{"value": null, "reason": ...}`` marker and never ``0``, and every
  zero-denominator rate is defined;
* **privacy assertions that can fail** — the sweeps are paired with mutations (a planted home
  directory, e-mail address, hostname and forbidden field must each be caught), because a
  clean bill of health from a broken matcher is the worst failure a privacy check has;
* **local only** — building, validating and writing the report touches no network (the
  module is scanned for network libraries and the CLI path is run with sockets disabled).

Every machine fact comes from a fake ``Provenance``, so the golden file is byte-stable on any
host. The numeric streams are mechanism fixtures; they say nothing about how well anyone's
eyes track.
"""
from __future__ import annotations

import ast
import json
import math
import socket
from pathlib import Path

import pytest

import yazses.eyeeval.gaze_field as gaze_field
from yazses.eyeeval import (
    LocalIdentifiers,
    Provenance,
    dump_result,
    privacy_problems,
    write_result,
)
from yazses.eyeeval.gaze_field import (
    CONFIDENCE_BINS,
    CalibrationFacts,
    Environment,
    Geometry,
    MeasurementSession,
    PointError,
    RoutingCounts,
    build_report,
    collect_validation,
    degrees_from_px,
    render_markdown,
    report_problems,
)
from yazses.eyeeval.schema import FORBIDDEN_FIELD_TOKENS, MISSING_REASONS

GOLDEN = Path(__file__).resolve().parent / "fixtures" / "gaze_field_report" / "full_session.json"

FAKE_MACHINE = Provenance(
    yazses_version="9.9.9",
    git_commit="0123456789abcdef0123456789abcdef01234567",
    python_version="3.12.0",
    os_name="Ubuntu",
    os_version="24.04",
    kernel="6.8.0",
    arch="x86_64",
    cpu_model="Example CPU",
    logical_cpus=8,
    ram_gb=16.0,
    session_type="x11",
    displays=({"width_px": 1920, "height_px": 1080, "scale": 1.0},),
    packages={"mediapipe": "0.10.0"},
)
NOW = "2026-10-12T09:00:00+00:00"
FAKE_IDS = LocalIdentifiers(
    hostname="thinkpad-of-someone", usernames=("evelyn",), home_paths=("/home/evelyn",)
)


def full_session() -> MeasurementSession:
    session = MeasurementSession(confidence_min=0.5)
    for confidence in (0.95, 0.9, 0.85, 0.55, 0.3, 0.05, 1.0, 0.0):
        session.record_confidence(confidence)
    session.record_point(PointError(t_s=10.0, error_px=40.0))
    session.record_point(PointError(t_s=20.0, error_px=60.0))
    session.record_point(PointError(t_s=400.0, error_px=100.0))
    session.set_duration(900.0)
    return session


def full_report() -> dict:
    return build_report(
        provenance=FAKE_MACHINE,
        timestamp=NOW,
        session=full_session(),
        calibration=CalibrationFacts(source="explicit", age_s=3600.0, topology_validity="valid"),
        camera_class="integrated",
        settings={"confidence_min": 0.5, "zones": "grid3x3", "model_path": "/home/evelyn/m.task"},
        routing=RoutingCounts(attempts=40, fallback_no_route=6, wrong_target_corrections=3),
        geometry=Geometry(
            screen_diagonal_in=15.6, screen_width_px=1920, screen_height_px=1080,
            viewing_distance_cm=60.0,
        ),
        environment=Environment(
            glasses="glasses", lighting="normal", viewing_distance_cm=60.0,
            camera_label="Integrated 720p",
        ),
        block_s=300.0,
    )


def empty_report() -> dict:
    return build_report(
        provenance=FAKE_MACHINE,
        timestamp=NOW,
        session=MeasurementSession(),
        calibration=CalibrationFacts(),
    )


# --------------------------------------------------------------------------- #
# Schema + golden
# --------------------------------------------------------------------------- #


def test_the_full_report_is_valid_under_the_shared_envelope_and_this_schema() -> None:
    assert report_problems(full_report()) == []


def test_the_golden_document_still_matches() -> None:
    """The whole envelope. To change the schema: change the module, bump
    ``TASK_VERSION``, and regenerate this file deliberately (see the docstring there)."""
    assert dump_result(full_report()) == GOLDEN.read_text(encoding="utf-8")


def test_every_documented_metric_key_is_present() -> None:
    metrics = full_report()["metrics"]
    for group, keys in gaze_field.REQUIRED_METRICS.items():
        assert set(keys) <= set(metrics[group]), group


def test_the_report_names_the_feature_and_task_so_it_sorts_with_other_gaze_results() -> None:
    doc = full_report()
    assert doc["feature"] == {"name": "gaze"}
    assert doc["protocol"]["task"] == gaze_field.TASK
    assert doc["software"]["generator"] == gaze_field.GENERATOR
    assert doc["privacy"] == {
        "data_class": "B", "raw_media_retained": False,
        "contains_personal_identifiers": False, "aggregates_only": True,
    }


def test_coordinate_error_correct_window_rate_and_availability_stay_three_things() -> None:
    """METRICS.md: never one generic 'gaze accuracy %'."""
    metrics = full_report()["metrics"]
    assert {"calibration", "routing", "confidence"} <= set(metrics)
    assert "accuracy" not in json.dumps(metrics).lower()


# --------------------------------------------------------------------------- #
# The numbers
# --------------------------------------------------------------------------- #


def test_calibration_error_statistics_are_computed_over_the_validation_points() -> None:
    cal = full_report()["metrics"]["calibration"]
    assert cal["validation_points"] == 3
    assert cal["error_px_mean"] == pytest.approx(66.67, abs=0.01)
    assert cal["error_px_max"] == 100.0
    assert cal["error_px_rmse"] == pytest.approx(math.sqrt((1600 + 3600 + 10000) / 3), abs=0.01)


def test_degrees_need_geometry_and_follow_the_visual_angle_formula() -> None:
    geometry = Geometry(
        screen_diagonal_in=15.6, screen_width_px=1920, screen_height_px=1080, viewing_distance_cm=60.0
    )
    pitch = 15.6 * 2.54 / math.hypot(1920, 1080)
    assert geometry.pitch_cm == pytest.approx(pitch)
    assert degrees_from_px(100.0, geometry) == pytest.approx(math.degrees(math.atan(100 * pitch / 60)))
    assert degrees_from_px(0.0, geometry) == 0.0
    with_geometry = full_report()["metrics"]["calibration"]["error_deg_mean"]
    assert with_geometry == pytest.approx(degrees_from_px(200.0 / 3, geometry), abs=0.001)

    without = build_report(
        provenance=FAKE_MACHINE, timestamp=NOW, session=full_session(),
        calibration=CalibrationFacts(),
    )["metrics"]["calibration"]["error_deg_mean"]
    assert without == {"value": None, "reason": "not_measured"}, (
        "an angle without screen size and viewing distance would be a made-up number"
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"screen_diagonal_in": 0.0}, {"screen_diagonal_in": -1.0}, {"viewing_distance_cm": 0.0},
        {"screen_width_px": 0}, {"screen_height_px": -5}, {"viewing_distance_cm": float("nan")},
    ],
)
def test_nonsense_geometry_is_refused(kwargs) -> None:
    base = dict(screen_diagonal_in=15.6, screen_width_px=1920, screen_height_px=1080,
                viewing_distance_cm=60.0)
    with pytest.raises(ValueError):
        Geometry(**{**base, **kwargs})


def test_confidence_is_a_histogram_and_a_running_mean_not_a_series() -> None:
    conf = full_report()["metrics"]["confidence"]
    assert conf["samples"] == 8
    assert conf["histogram"] == [2, 0, 0, 1, 0, 1, 0, 0, 1, 3]
    assert sum(conf["histogram"]) == conf["samples"]
    assert len(conf["histogram"]) == CONFIDENCE_BINS
    assert conf["mean"] == pytest.approx(sum((0.95, 0.9, 0.85, 0.55, 0.3, 0.05, 1.0, 0.0)) / 8, abs=1e-4)
    assert (conf["min"], conf["max"]) == (0.0, 1.0)
    assert conf["below_threshold_fraction"] == pytest.approx(3 / 8)
    assert conf["threshold"] == 0.5


def test_a_confidence_of_exactly_one_lands_in_the_last_bin_not_off_the_end() -> None:
    s = MeasurementSession()
    s.record_confidence(1.0)
    assert s.confidence_block()["histogram"][-1] == 1


@pytest.mark.parametrize("bad", [-0.01, 1.01, float("nan"), float("inf")])
def test_an_out_of_range_confidence_is_refused(bad) -> None:
    with pytest.raises(ValueError):
        MeasurementSession().record_confidence(bad)


def test_drift_is_the_mean_error_per_time_block_and_skips_blocks_with_no_point() -> None:
    blocks = full_report()["metrics"]["session"]["drift_blocks"]
    assert blocks == [
        {"block": 0, "start_s": 0.0, "points": 2, "error_px_mean": 50.0},
        {"block": 1, "start_s": 300.0, "points": 1, "error_px_mean": 100.0},
    ]


def test_routing_rates_are_defined_by_the_counts_the_tester_gave() -> None:
    routing = full_report()["metrics"]["routing"]
    assert routing["attempts"] == 40
    assert routing["gaze_routed"] == 34
    assert routing["fallback_no_route"] == 6
    assert routing["wrong_target_corrections"] == 3
    assert routing["wrong_target_rate"] == pytest.approx(3 / 40)
    assert routing["fallback_rate"] == pytest.approx(6 / 40)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"attempts": -1}, {"attempts": True}, {"attempts": 1.5},
        {"attempts": 5, "fallback_no_route": 6},
        {"attempts": 5, "wrong_target_corrections": 6},
    ],
)
def test_impossible_routing_counts_are_refused(kwargs) -> None:
    with pytest.raises(ValueError):
        RoutingCounts(**kwargs)


# --------------------------------------------------------------------------- #
# Empty and partial sessions
# --------------------------------------------------------------------------- #


def _walk_missing(node, path=""):
    if isinstance(node, dict):
        if "reason" in node and "value" in node:
            yield path, node
            return
        for key, value in node.items():
            yield from _walk_missing(value, f"{path}.{key}" if path else key)


def test_an_empty_session_still_produces_a_valid_complete_document() -> None:
    doc = empty_report()
    assert report_problems(doc) == []
    metrics = doc["metrics"]
    for group, keys in gaze_field.REQUIRED_METRICS.items():
        assert set(keys) <= set(metrics[group]), f"{group} lost a key on an empty session"


def test_in_an_empty_session_every_unmeasured_figure_is_a_marker_and_not_a_zero() -> None:
    metrics = empty_report()["metrics"]
    cal, conf, routing, session = (metrics[k] for k in ("calibration", "confidence", "routing", "session"))
    assert cal["validation_points"] == 0 and conf["samples"] == 0
    assert conf["histogram"] == [0] * CONFIDENCE_BINS
    assert session["drift_blocks"] == []
    marked = dict(_walk_missing(metrics))
    for path in (
        "calibration.error_px_rmse", "calibration.error_px_mean", "calibration.error_px_max",
        "calibration.error_deg_mean", "calibration.age_s", "confidence.mean",
        "confidence.below_threshold_fraction", "routing.attempts", "routing.wrong_target_rate",
        "routing.fallback_rate", "session.duration_s",
    ):
        assert path in marked, f"{path} should be an explicit not-measured marker"
        assert marked[path]["value"] is None and marked[path]["reason"] in MISSING_REASONS
    assert 0 not in (cal["error_px_mean"], conf["mean"], routing["wrong_target_rate"])


def test_zero_attempts_makes_every_rate_a_marker_not_a_division_by_zero() -> None:
    doc = build_report(
        provenance=FAKE_MACHINE, timestamp=NOW, session=MeasurementSession(),
        calibration=CalibrationFacts(),
        routing=RoutingCounts(attempts=0, fallback_no_route=0, wrong_target_corrections=0),
    )
    routing = doc["metrics"]["routing"]
    assert routing["attempts"] == 0, "a counted zero is a real zero"
    assert routing["wrong_target_rate"] == {"value": None, "reason": "not_measured"}
    assert routing["fallback_rate"] == {"value": None, "reason": "not_measured"}
    assert report_problems(doc) == []


def test_a_partial_session_reports_what_it_has_and_marks_the_rest() -> None:
    session = MeasurementSession()
    session.record_confidence(0.8)
    doc = build_report(
        provenance=FAKE_MACHINE, timestamp=NOW, session=session, calibration=CalibrationFacts(),
        routing=RoutingCounts(attempts=10),
    )
    metrics = doc["metrics"]
    assert metrics["confidence"]["samples"] == 1
    assert metrics["calibration"]["validation_points"] == 0
    assert metrics["routing"]["attempts"] == 10
    assert metrics["routing"]["wrong_target_corrections"]["value"] is None
    assert metrics["routing"]["gaze_routed"]["value"] is None, (
        "attempts alone cannot say how many were routed by gaze"
    )
    assert report_problems(doc) == []


def test_the_markdown_summary_handles_the_empty_session_without_inventing_a_number() -> None:
    text = render_markdown(empty_report())
    assert "not measured" in text
    assert "None" not in text and "nan" not in text.lower()


# --------------------------------------------------------------------------- #
# Collecting a validation pass
# --------------------------------------------------------------------------- #


class FakeBackend:
    def __init__(self, samples):
        self._samples = list(samples)

    def estimate_sample(self):
        return self._samples.pop(0) if self._samples else None


class S:
    def __init__(self, x, y, confidence):
        self.x, self.y, self.confidence = x, y, confidence


class Identity:
    def predict(self, x, y):
        return x, y


def test_a_validation_pass_measures_the_distance_from_each_target_to_where_gaze_lands() -> None:
    session = MeasurementSession()
    backend = FakeBackend([S(100, 100, 0.9), S(104, 100, 0.8), S(0, 0, 0.7), S(0, 0, 0.7)])
    ticks = iter([5.0, 6.0])
    produced = collect_validation(
        backend, Identity(), [("a", (100, 100)), ("b", (0, 3))], lambda *_: None, session,
        lambda: next(ticks), per_point=2, started_at=1.0,
    )
    assert produced == 2
    first, second = session.points
    assert first.error_px == pytest.approx(2.0)          # mean (102, 100) vs (100, 100)
    assert first.t_s == pytest.approx(4.0)
    assert second.error_px == pytest.approx(3.0)
    assert session.confidence_block()["samples"] == 4


def test_a_target_with_no_usable_sample_produces_no_point_not_a_zero_error_point() -> None:
    session = MeasurementSession()
    produced = collect_validation(
        FakeBackend([]), Identity(), [("a", (1, 1))], lambda *_: None, session, lambda: 0.0
    )
    assert produced == 0
    assert session.points == ()
    assert empty_like(session)


def empty_like(session: MeasurementSession) -> bool:
    return session.confidence_block()["samples"] == 0


# --------------------------------------------------------------------------- #
# Environment: volunteered, validated, optional
# --------------------------------------------------------------------------- #


def test_omitted_environment_fields_read_not_stated_and_not_a_guess() -> None:
    env = empty_report()["metrics"]["environment"]
    assert env["glasses"] == "not_stated" and env["lighting"] == "not_stated"
    assert env["viewing_distance_cm"]["value"] is None
    assert env["camera_label"]["value"] is None


@pytest.mark.parametrize(
    "kwargs",
    [
        {"glasses": "monocle"},
        {"lighting": "disco"},
        {"viewing_distance_cm": 0.0},
        {"viewing_distance_cm": float("nan")},
        {"camera_label": ""},
        {"camera_label": "x" * 49},
        {"camera_label": "/home/evelyn/cam"},
        {"camera_label": "me@example.com"},
        {"camera_label": "C920\nSN 1234"},
    ],
)
def test_environment_values_outside_the_vocabulary_are_refused(kwargs) -> None:
    with pytest.raises(ValueError):
        Environment(**kwargs)


# --------------------------------------------------------------------------- #
# Privacy: each sweep paired with a mutation that must trip it
# --------------------------------------------------------------------------- #


def test_the_clean_report_passes_the_privacy_sweep() -> None:
    assert privacy_problems(full_report(), FAKE_IDS) == []


def test_the_report_has_no_field_name_the_programme_promised_never_to_collect() -> None:
    def keys(node):
        if isinstance(node, dict):
            for key, value in node.items():
                yield str(key).lower()
                yield from keys(value)
        elif isinstance(node, list):
            for item in node:
                yield from keys(item)

    for doc in (full_report(), empty_report()):
        for key in keys(doc):
            for token in FORBIDDEN_FIELD_TOKENS:
                assert token not in key, f"{key!r} contains forbidden token {token!r}"


def test_the_model_path_setting_is_dropped_by_shape_not_by_name() -> None:
    """``model_path`` is an absolute path under the user's home on a real install."""
    settings = full_report()["config"]["settings"]
    assert "model_path" not in settings
    assert "/home/" not in json.dumps(full_report())


@pytest.mark.parametrize(
    "plant",
    [
        ("metrics.environment.camera_label", "/home/evelyn/camera"),
        ("metrics.environment.camera_label", "evelyn@example.com"),
        ("metrics.environment.camera_label", "thinkpad-of-someone"),
        ("metrics.environment.camera_label", "C:\\Users\\Evelyn\\cam"),
    ],
)
def test_the_value_sweep_catches_a_planted_identifier(plant) -> None:
    doc = full_report()
    node = doc
    *parents, leaf = plant[0].split(".")
    for part in parents:
        node = node[part]
    node[leaf] = plant[1]
    assert privacy_problems(doc, FAKE_IDS), f"the sweep missed {plant[1]!r}"


def test_a_forbidden_field_name_is_caught_by_the_report_validator() -> None:
    doc = full_report()
    doc["metrics"]["confidence"]["landmark_trace"] = [0.1, 0.2]
    assert any("forbidden field" in p for p in report_problems(doc))


def test_a_bare_null_metric_is_refused_because_unmeasured_must_say_why() -> None:
    doc = full_report()
    doc["metrics"]["calibration"]["error_px_mean"] = None
    assert any("bare null" in p for p in report_problems(doc))


def test_a_report_missing_a_documented_key_is_flagged() -> None:
    doc = full_report()
    del doc["metrics"]["routing"]["wrong_target_rate"]
    assert any("routing.wrong_target_rate" in p for p in report_problems(doc))


def test_writing_refuses_a_leaking_report_and_creates_no_file(tmp_path) -> None:
    doc = full_report()
    doc["metrics"]["environment"]["camera_label"] = "/home/evelyn/cam"
    target = tmp_path / "report.json"
    with pytest.raises(Exception, match="refusing to write"):
        write_result(doc, target, identifiers=FAKE_IDS)
    assert not target.exists()


def test_writing_a_clean_report_creates_exactly_the_json(tmp_path) -> None:
    target = tmp_path / "report.json"
    write_result(full_report(), target, identifiers=FAKE_IDS)
    assert json.loads(target.read_text(encoding="utf-8"))["feature"] == {"name": "gaze"}
    assert [p.name for p in tmp_path.iterdir()] == ["report.json"]


# --------------------------------------------------------------------------- #
# Local only
# --------------------------------------------------------------------------- #


def test_the_module_imports_no_network_screen_or_camera_library() -> None:
    forbidden = {
        "socket", "ssl", "http", "urllib", "requests", "httpx", "subprocess", "cv2", "mediapipe",
        "PIL", "mss", "pyautogui",
    }
    tree = ast.parse(Path(gaze_field.__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported.isdisjoint(forbidden), sorted(imported & forbidden)


def test_building_validating_and_writing_a_report_opens_no_socket(tmp_path, monkeypatch) -> None:
    def no_network(*_a, **_k):
        raise AssertionError("a network socket was opened while building a local report")

    monkeypatch.setattr(socket, "socket", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    doc = full_report()
    assert report_problems(doc) == []
    write_result(doc, tmp_path / "r.json", identifiers=FAKE_IDS)
    render_markdown(doc)
