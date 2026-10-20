"""The gaze field report as a *reader*: aggregates in, anything that could leak refused (#399).

`test_gaze_field_report.py` pins what `yazses gaze measure` writes. This file pins the other
half of the issue: a report someone attaches to #104 is checked by a validator that

* reports **error distributions and zone hit rates** -- aggregates only, the per-point
  predicted coordinate is never kept (`zone_hit` is a yes/no);
* **refuses a document that would leak**, whoever produced it: a home path or e-mail in any
  value, this machine's hostname/login when known, a key named for raw gaze, and -- the rule
  that actually stops per-sample coordinates -- any list or object under ``metrics`` that the
  schema does not define;
* **fails on unreadable or empty input**: a missing, empty, non-UTF-8 or non-JSON file is a
  problem, never an empty document that passes.

Every refusal test plants one leak in an otherwise valid report and asserts the validator now
objects, so a matcher that silently stopped matching turns these red rather than green.
"""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

from yazses.eyeeval import LocalIdentifiers, Provenance, dump_result
from yazses.eyeeval.gaze_field import (
    ZONE_COLS,
    ZONE_ROWS,
    CalibrationFacts,
    MeasurementSession,
    PointError,
    build_report,
    collect_validation,
    render_markdown,
    report_problems,
    report_problems_file,
    report_problems_text,
    zone_hit,
)

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "tests" / "fixtures" / "gaze_field_report" / "full_session.json"
SCRIPT = ROOT / "scripts" / "check_eye_eval_result.py"

PROV = Provenance(
    yazses_version="9.9.9", git_commit="0123456789ab", python_version="3.12.0",
    os_name="Ubuntu", os_version="24.04", kernel="6.8.0", arch="x86_64",
    cpu_model="Example CPU", logical_cpus=8, ram_gb=16.0, session_type="x11",
    # The envelope's own display entry carries x/y: the raw-gaze key rule must not fire on it.
    displays=({"index": 0, "x": 0, "y": 0, "width": 1920, "height": 1080,
               "scale": 1.0, "primary": True},),
)
NOW = "2026-10-20T09:00:00+00:00"
IDS = LocalIdentifiers(hostname="thinkpad-of-someone", usernames=("evelyn",),
                       home_paths=("/home/evelyn",))
SCREEN = (1920, 1080)


def report(points: list[PointError] | None = None) -> dict[str, Any]:
    session = MeasurementSession(confidence_min=0.5)
    for confidence in (0.9, 0.8, 0.4):
        session.record_confidence(confidence)
    for point in points if points is not None else [
        PointError(t_s=1.0, error_px=10.0, zone_hit=True),
        PointError(t_s=2.0, error_px=20.0, zone_hit=True),
        PointError(t_s=3.0, error_px=30.0, zone_hit=False),
        PointError(t_s=4.0, error_px=40.0, zone_hit=True),
    ]:
        session.record_point(point)
    return build_report(
        provenance=PROV, timestamp=NOW, session=session,
        calibration=CalibrationFacts(source="explicit", age_s=60.0, topology_validity="valid"),
        block_s=2.0,
    )


# --------------------------------------------------------------------------- #
# Aggregates: error distribution and zone hit rate
# --------------------------------------------------------------------------- #


def test_the_clean_report_is_valid_including_the_privacy_sweep_and_this_hosts_names() -> None:
    assert report_problems(report(), IDS) == []


def test_error_percentiles_are_nearest_rank_observed_values() -> None:
    cal = report()["metrics"]["calibration"]
    assert cal["error_px_p50"] == 20.0   # rank ceil(0.5 * 4) = 2
    assert cal["error_px_p90"] == 40.0   # rank ceil(0.9 * 4) = 4
    one = report([PointError(t_s=1.0, error_px=7.0)])["metrics"]["calibration"]
    assert one["error_px_p50"] == one["error_px_p90"] == 7.0


def test_the_zone_hit_rate_counts_only_points_that_carry_a_zone_verdict() -> None:
    cal = report()["metrics"]["calibration"]
    assert (cal["zone_grid"], cal["zone_points"], cal["zone_hits"]) == ("3x3", 4, 3)
    assert cal["zone_hit_rate"] == 0.75
    unzoned = report([PointError(t_s=1.0, error_px=5.0)])["metrics"]["calibration"]
    assert unzoned["zone_points"] == 0
    assert unzoned["zone_hits"] == {"value": None, "reason": "not_measured"}
    assert unzoned["zone_hit_rate"] == {"value": None, "reason": "not_measured"}


def test_an_empty_session_marks_every_distribution_figure_missing_and_stays_valid() -> None:
    doc = report([])
    cal = doc["metrics"]["calibration"]
    for key in ("error_px_p50", "error_px_p90", "zone_hits", "zone_hit_rate"):
        assert cal[key] == {"value": None, "reason": "not_measured"}, key
    assert cal["zone_points"] == 0
    assert report_problems(doc, IDS) == []
    assert "not measured" in render_markdown(doc)


def test_a_zone_hit_is_the_same_cell_of_the_3x3_grid() -> None:
    assert (ZONE_ROWS, ZONE_COLS) == (3, 3)
    assert zone_hit((200.0, 120.0), (192, 108), SCREEN) is True       # both top-left cell
    assert zone_hit((700.0, 120.0), (192, 108), SCREEN) is False      # top-centre cell
    assert zone_hit((960.0, 540.0), (960, 540), SCREEN) is True


@pytest.mark.parametrize("predicted", [(-5.0, 100.0), (100.0, -1.0), (1920.0, 100.0), (100.0, 1080.0)])
def test_a_prediction_off_the_screen_is_a_miss_not_a_clamped_edge_hit(predicted) -> None:
    """`grid_zone` clamps off-screen points into the edge cell; scoring that would count a
    gaze that left the screen as a hit on every edge target."""
    target = (192, 108) if predicted[0] < 1000 else (1728, 108)
    assert zone_hit(predicted, target, SCREEN) is False


class _Backend:
    def __init__(self, x: float, y: float) -> None:
        self.x, self.y = x, y

    def estimate_sample(self):
        return type("S", (), {"x": self.x, "y": self.y, "confidence": 0.9})()


class _Identity:
    def predict(self, x, y):
        return x, y


def test_collect_validation_keeps_only_the_zone_verdict_not_the_predicted_point() -> None:
    session = MeasurementSession()
    targets = [("top-left", (192, 108)), ("centre", (960, 540))]
    collect_validation(_Backend(960.0, 540.0), _Identity(), targets, lambda *_: None, session,
                       lambda: 0.0, per_point=2, screen=SCREEN)
    assert [p.zone_hit for p in session.points] == [False, True]
    assert all(set(vars(p)) == {"t_s", "error_px", "zone_hit"} for p in session.points)

    without = MeasurementSession()
    collect_validation(_Backend(960.0, 540.0), _Identity(), targets, lambda *_: None, without,
                       lambda: 0.0, per_point=2)
    assert [p.zone_hit for p in without.points] == [None, None]


def test_a_non_boolean_zone_verdict_is_refused() -> None:
    with pytest.raises(ValueError, match="zone_hit"):
        PointError(t_s=0.0, error_px=1.0, zone_hit=1)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Refusing a report that would leak
# --------------------------------------------------------------------------- #


def _container_paths(node: Any, path: str = "") -> set[str]:
    out: set[str] = set()
    if isinstance(node, dict):
        if path and not ("value" in node or "reason" in node):
            out.add(path)
        for key, value in node.items():
            out |= _container_paths(value, f"{path}.{key}" if path else str(key))
    elif isinstance(node, list):
        out.add(path)
    return out


def test_the_allowed_containers_are_exactly_the_ones_the_producer_emits() -> None:
    """Derived, not hand-checked: if the producer grows a list the validator does not allow,
    or the allow-list names one the producer no longer writes, this fails."""
    from yazses.eyeeval import gaze_field

    emitted = _container_paths(report()["metrics"])
    emitted = {p for p in emitted if not p.startswith("session.drift_blocks.")}
    assert emitted == set(gaze_field._ALLOWED_LISTS) | set(gaze_field._ALLOWED_OBJECTS)


SERIES_PLANTS = [
    ("calibration", "points", [[812.0, 410.0], [790.5, 402.0]]),
    ("calibration", "predicted", {"0": 812.0, "1": 790.5}),
    ("confidence", "per_sample", [0.9, 0.8, 0.4]),
    ("session", "timeline", [{"t": 1.0, "e": 10.0}]),
    ("routing", "targets", ["pane-a", "pane-b"]),
]


@pytest.mark.parametrize(("group", "key", "value"), SERIES_PLANTS)
def test_a_per_sample_series_is_refused_under_any_name(group, key, value) -> None:
    doc = report()
    doc["metrics"][group][key] = value
    assert any(f"metrics.{group}.{key}" in p for p in report_problems(doc)), (group, key)


def test_a_new_metric_group_that_is_a_container_is_refused() -> None:
    doc = report()
    doc["metrics"]["samples"] = [{"t": 1, "c": 0.9}]
    assert any("metrics.samples" in p for p in report_problems(doc))
    doc = report()
    doc["metrics"]["trace"] = {"a": 1}
    assert any("metrics.trace" in p for p in report_problems(doc))


def test_a_series_hidden_inside_a_missing_marker_is_refused() -> None:
    doc = report()
    doc["metrics"]["calibration"]["age_s"] = {"value": [[1, 2], [3, 4]], "reason": None}
    assert any("metrics.calibration.age_s.value" in p for p in report_problems(doc))


@pytest.mark.parametrize(
    "key", ["x", "y", "yaw", "pitch", "gaze_point", "raw_coordinates", "frame_count",
            "face_mesh_hash", "iris_radius", "pupil_size", "eye_openness", "trajectory_len",
            "image_sha"],
)
def test_a_key_named_for_raw_gaze_is_refused_even_as_a_scalar(key) -> None:
    doc = report()
    doc["metrics"]["calibration"][key] = 1
    assert any(f"metrics.calibration.{key}" in p and "raw gaze" in p for p in report_problems(doc))


def test_the_raw_key_rule_does_not_fire_on_the_envelopes_own_display_origin() -> None:
    doc = report()
    assert doc["display"]["displays"][0]["x"] == 0
    assert report_problems(doc) == []


def test_a_drift_block_cannot_grow_a_field() -> None:
    doc = report()
    doc["metrics"]["session"]["drift_blocks"][0]["errors"] = [10.0]
    assert any("drift_blocks.0" in p for p in report_problems(doc))


def test_drift_blocks_must_add_up_to_the_validation_points() -> None:
    doc = report()
    doc["metrics"]["session"]["drift_blocks"].append(
        {"block": 99, "start_s": 198.0, "points": 1, "error_px_mean": 5.0}
    )
    assert any("do not add up" in p for p in report_problems(doc))


def test_the_histogram_must_add_up_to_the_samples() -> None:
    doc = report()
    doc["metrics"]["confidence"]["histogram"][0] += 1
    assert any("histogram" in p and "add up" in p for p in report_problems(doc))
    doc = report()
    doc["metrics"]["confidence"]["histogram"] = [0.5] * 10
    assert any("histogram" in p for p in report_problems(doc))


def test_zone_counts_cannot_exceed_what_they_count() -> None:
    doc = report()
    doc["metrics"]["calibration"]["zone_hits"] = 5
    assert any("zone_hits" in p for p in report_problems(doc))
    doc = report()
    doc["metrics"]["calibration"]["zone_points"] = 9
    assert any("zone_points" in p for p in report_problems(doc))


@pytest.mark.parametrize(
    "label", ["/home/evelyn/cam", "evelyn@example.com", "C:\\Users\\Evelyn\\cam", "/Users/evelyn"]
)
def test_a_home_path_or_address_is_refused_without_knowing_the_machine(label) -> None:
    doc = report()
    doc["metrics"]["environment"]["camera_label"] = label
    assert report_problems(doc), label


@pytest.mark.parametrize("planted", ["thinkpad-of-someone", "evelyn"])
def test_this_hosts_name_and_login_are_refused_when_the_identifiers_are_known(planted) -> None:
    """A bare hostname matches no pattern, so only the machine that knows it can refuse it --
    which is why `gaze measure` passes `local_identifiers()` and a maintainer's check cannot."""
    doc = report()
    doc["metrics"]["environment"]["camera_label"] = planted
    assert report_problems(doc) == []
    assert any("environment.camera_label" in p for p in report_problems(doc, IDS))


def test_the_envelope_forbidden_fields_still_apply() -> None:
    doc = report()
    doc["machine"]["hostname"] = "box"
    assert any("forbidden field" in p for p in report_problems(doc))


# --------------------------------------------------------------------------- #
# Unreadable or empty input
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "content",
    [b"", b"   \n", b"\xff\xfe\x00garbage", b"not json", b"[]", b"{}", b'{"metrics": {}}',
     b'{"a": 1, "a": 2}', b'{"x": NaN}', b"null"],
)
def test_an_unreadable_or_empty_file_is_a_problem(tmp_path, content) -> None:
    path = tmp_path / "report.json"
    path.write_bytes(content)
    assert report_problems_file(path), content


def test_a_missing_file_and_a_directory_are_problems(tmp_path) -> None:
    assert report_problems_file(tmp_path / "absent.json")
    assert report_problems_file(tmp_path)


def test_text_and_file_readers_agree_with_the_document_validator(tmp_path) -> None:
    doc = report()
    text = dump_result(doc)
    path = tmp_path / "r.json"
    path.write_text(text, encoding="utf-8")
    assert report_problems_text(text, IDS) == report_problems_file(path, IDS) == []
    leaky = copy.deepcopy(doc)
    leaky["metrics"]["calibration"]["points"] = [[1.0, 2.0]]
    path.write_text(dump_result(leaky), encoding="utf-8")
    assert report_problems_file(path) == report_problems(leaky) != []


def test_the_committed_golden_report_passes_the_file_reader() -> None:
    assert report_problems_file(GOLDEN) == []


# --------------------------------------------------------------------------- #
# The attachment checker routes a gaze report through this validator
# --------------------------------------------------------------------------- #


def _script() -> Any:
    spec = importlib.util.spec_from_file_location("check_eye_eval_result_399", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_attachment_checker_refuses_a_gaze_report_carrying_a_series(tmp_path, capsys) -> None:
    script = _script()
    leaky = report()
    leaky["metrics"]["calibration"]["points"] = [[812.0, 410.0]]
    bad = tmp_path / "leaky.json"
    bad.write_text(json.dumps(leaky), encoding="utf-8")
    good = tmp_path / "good.json"
    good.write_text(dump_result(report()), encoding="utf-8")
    assert script.main([str(good)]) == 0
    assert script.main([str(bad)]) == 1
    assert "metrics.calibration.points" in capsys.readouterr().err
