"""One desktop coordinate space, and a damaged calibration that never reads as valid (#415).

`test_gaze_topology.py` proves the stale/valid decision and `test_gaze_display_real_shapes.py`
proves it against real ``xrandr`` output. This file covers the two halves EYE-DISPLAY-001
still left open:

* **conversions between spaces at the topology level** -- canonical desktop, one panel's
  physical pixels, and offsets from the virtual desktop's (possibly negative) origin -- over
  a mixed 1.0 / 1.25 / 2.0 layout with a monitor left of and above the main one;
* **a damaged file**: every way the bytes on disk can be wrong must end in "no map" or "the
  binding is damaged", never in VALID and never in an exception out of the daemon.

Fabricated topologies and hand-written files only: no display server, no camera.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from yazses.gaze.calibrate import CalibrationMap
from yazses.gaze.store import (
    calibration_path,
    calibration_state,
    load_calibration_record,
    save_calibration,
)
from yazses.gaze.topology import (
    CANONICAL_SPACE,
    CalibrationContext,
    Display,
    DisplayTopology,
    PhysicalPoint,
    Validity,
    digest,
)
from yazses.handsfree.probe import calibration_facts

# ---- a mixed-scale desktop ---------------------------------------------------------
#
# Windows/macOS-shaped (origin at the main display): a 1.25-scale panel up and to the
# LEFT of the main one, so both of its origin coordinates are negative, and a 2.0-scale
# 4K panel to the right whose 3840x2160 physical pixels occupy 1920x1080 logical ones.

MAIN = Display("main", 0, 0, 1920, 1080, scale=1.0, primary=True)
LEFT_UP = Display("left", -1536, -400, 1536, 864, scale=1.25)  # 1920x1080 physical
RIGHT_4K = Display("right", 1920, 0, 1920, 1080, scale=2.0)  # 3840x2160 physical
DESK = DisplayTopology((RIGHT_4K, MAIN, LEFT_UP))

IDENT = CalibrationMap(A=np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]))


def context(*displays: Display) -> CalibrationContext:
    return CalibrationContext(topology=DisplayTopology(displays or DESK.displays), camera_id="0")


# ---- conversions -------------------------------------------------------------------


def test_the_virtual_desktop_origin_is_negative_when_a_monitor_sits_left_and_above() -> None:
    assert DESK.origin == (-1536, -400)
    assert DESK.bounds() == (-1536, -400, 1536 + 1920 + 1920, 400 + 1080)


@pytest.mark.parametrize(
    ("point", "expected"),
    [
        ((0, 0), PhysicalPoint("main", 0.0, 0.0)),  # 1.0: identity at the main origin
        ((100, 50), PhysicalPoint("main", 100.0, 50.0)),
        ((-1536, -400), PhysicalPoint("left", 0.0, 0.0)),  # negative origin -> panel (0, 0)
        ((-768, 32), PhysicalPoint("left", 960.0, 540.0)),  # 1.25: centre of 1920x1080
        ((1920, 0), PhysicalPoint("right", 0.0, 0.0)),
        ((2880, 540), PhysicalPoint("right", 1920.0, 1080.0)),  # 2.0: centre of 3840x2160
        ((3839, 1079), PhysicalPoint("right", 3838.0, 2158.0)),
    ],
)
def test_canonical_points_convert_to_the_physical_pixels_of_the_panel_they_land_on(
    point: tuple[float, float], expected: PhysicalPoint
) -> None:
    assert DESK.to_physical(*point) == expected


@pytest.mark.parametrize(
    "point",
    [
        (-1, 500),  # below the left panel (it ends at y=464), left of main: a dead corner
        (0, -1),  # above main, right of the left panel
        (3840, 0),  # one past the right edge of the desktop
        (-1537, 0),  # one past the left edge
    ],
)
def test_a_point_on_no_panel_has_no_physical_pixel(point: tuple[float, float]) -> None:
    # Not the nearest panel: snapping is a placement decision, not a unit conversion.
    assert DESK.to_physical(*point) is None


def test_conversion_round_trips_deterministically_at_every_scale() -> None:
    """Over a grid on every display: canonical -> physical -> canonical is exact, twice."""
    for display in DESK.displays:
        for fx in (0.0, 0.25, 0.5, 0.999):
            for fy in (0.0, 0.33, 0.75, 0.999):
                x = display.x + fx * display.width
                y = display.y + fy * display.height
                first = DESK.to_physical(x, y)
                again = DESK.to_physical(x, y)
                assert first == again and first is not None
                assert first.display == display.identifier
                back = DESK.from_physical(first.display, first.x, first.y)
                assert back == pytest.approx((x, y), abs=1e-9)


def test_from_physical_refuses_geometry_from_another_layout() -> None:
    assert DESK.from_physical("HDMI-9", 0, 0) is None  # a display this layout lacks
    assert DESK.from_physical("right", 3840, 0) is None  # one past a 3840-wide panel
    assert DESK.from_physical("right", 0, -1) is None
    assert DESK.from_physical("right", 3839, 2159) == pytest.approx((1920 + 1919.5, 1079.5))


def test_desktop_relative_offsets_are_never_negative_on_the_desktop_and_round_trip() -> None:
    for display in DESK.displays:
        for corner in ((display.x, display.y), (display.right - 1, display.bottom - 1)):
            rel = DESK.to_desktop_relative(*corner)
            assert rel is not None and rel[0] >= 0 and rel[1] >= 0
            assert DESK.from_desktop_relative(*rel) == corner
    assert DESK.to_desktop_relative(-1536, -400) == (0, 0)


def test_an_unknown_topology_converts_nothing() -> None:
    unknown = DisplayTopology()
    assert unknown.origin is None
    assert unknown.to_physical(0, 0) is None
    assert unknown.from_physical("main", 0, 0) is None
    assert unknown.to_desktop_relative(0, 0) is None
    assert unknown.from_desktop_relative(0, 0) is None


def test_an_x11_shaped_layout_has_a_zero_origin_and_converts_as_identity() -> None:
    # X11's canonical space is the framebuffer: the left monitor is at +0, never negative.
    x11 = DisplayTopology((Display("DP-2", 0, 0, 1280, 1024), Display("eDP-1", 1280, 0, 1920, 1080, primary=True)))
    assert x11.origin == (0, 0)
    assert x11.to_desktop_relative(1500, 20) == (1500, 20)
    assert x11.to_physical(1500, 20) == PhysicalPoint("eDP-1", 220.0, 20.0)


# ---- a display that cannot exist ---------------------------------------------------


@pytest.mark.parametrize("scale", [float("nan"), float("inf"), -1.0, 0.0])
def test_a_display_refuses_a_scale_no_panel_has(scale: float) -> None:
    # NaN passed the old `scale <= 0` check, and every coordinate it touched became NaN.
    with pytest.raises(ValueError):
        Display("x", 0, 0, 10, 10, scale=scale)


def test_a_display_refuses_a_rotation_that_is_not_one_of_the_four() -> None:
    with pytest.raises(ValueError):
        Display("x", 0, 0, 10, 10, rotation="sideways")


# ---- strict rebuilding from disk ---------------------------------------------------


def _entry(**overrides) -> dict:
    entry = MAIN.as_dict()
    entry.update(overrides)
    return entry


@pytest.mark.parametrize(
    "damage",
    [
        {"x": 1.5},  # int() would truncate to 1: a different desktop, silently
        {"x": True},  # int(True) == 1
        {"w": "1920"},  # int("1920") == 1920
        {"w": float("inf")},  # int(inf) raises OverflowError, not ValueError
        {"scale": "2"},
        {"scale": float("nan")},
        {"primary": "yes"},
        {"id": 7},
        {"id": ""},
        {"rotation": "sideways"},
        {"rotation": 90},
    ],
)
def test_a_damaged_display_entry_is_refused_not_coerced(damage: dict) -> None:
    with pytest.raises(ValueError):
        Display.from_dict(_entry(**damage))


def test_an_integral_float_is_the_same_number_and_is_accepted() -> None:
    assert Display.from_dict(_entry(x=0.0, w=1920.0)) == MAIN


def test_a_topology_naming_one_display_twice_is_refused() -> None:
    raw = {"displays": [MAIN.as_dict(), MAIN.as_dict()]}
    with pytest.raises(ValueError):
        DisplayTopology.from_dict(raw)


@pytest.mark.parametrize(
    "damage",
    [
        {"camera": {"id": 0, "w": 0, "h": 0}},  # a number where a string was written
        {"camera": {"id": "0", "w": 1280.5, "h": 720}},
        {"version": "1"},
        {"model": None},
    ],
)
def test_a_damaged_context_is_refused(damage: dict) -> None:
    raw = context().as_dict()
    raw.update(damage)
    with pytest.raises(ValueError):
        CalibrationContext.from_dict(raw)


# ---- a damaged calibration file ----------------------------------------------------


def _write(tmp_path: Path, text: str) -> None:
    calibration_path(tmp_path).write_text(text, encoding="utf-8")


def _saved(tmp_path: Path) -> dict:
    save_calibration(IDENT, tmp_path, context())
    return json.loads(calibration_path(tmp_path).read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "matrix_json",
    [
        "[[NaN, 0, 0], [0, 1, 0]]",  # Python's json accepts the bare token
        "[[1, 0, 0], [0, Infinity, 0]]",
        '[["1", "0", "0"], ["0", "1e999", "0"]]',  # numpy would coerce, 1e999 -> inf
        "[[true, 0, 0], [0, 1, 0]]",
        "[[1, 0], [0, 1], [0, 0]]",  # 3x2, not 2x3
        "[[1, 0, 0], [0, 1]]",  # ragged
        "[]",
        "null",
    ],
)
def test_a_damaged_map_is_no_map_and_the_verdict_says_why(tmp_path: Path, matrix_json: str) -> None:
    raw = _saved(tmp_path)
    text = json.dumps(raw).replace(json.dumps(raw["A"]), matrix_json)
    assert matrix_json in text
    _write(tmp_path, text)
    assert load_calibration_record(tmp_path) is None
    cal, check = calibration_state(tmp_path, context())
    assert cal is None, "a NaN/inf/coerced map would route every gaze sample somewhere wrong"
    assert check.stale and "damaged" in check.reason


@pytest.mark.parametrize(
    "garbage",
    [
        b"\xff\xfe\x00 not utf-8",
        b"{ truncated",
        b'"a json string"',
        b"[" * 100_000 + b"]" * 100_000,  # nested past the recursion limit
        b"",
    ],
    ids=["not-utf8", "truncated", "json-string", "nested-past-recursion-limit", "empty"],
)
def test_an_unreadable_file_neither_crashes_nor_reads_as_never_calibrated(
    tmp_path: Path, garbage: bytes
) -> None:
    calibration_path(tmp_path).write_bytes(garbage)
    cal, check = calibration_state(tmp_path, context())
    assert cal is None
    assert check.stale and "damaged or unreadable" in check.reason
    assert "before YazSes recorded" not in check.reason


def test_a_directory_where_the_file_should_be_is_damaged_not_a_crash(tmp_path: Path) -> None:
    calibration_path(tmp_path).mkdir()
    cal, check = calibration_state(tmp_path, context())
    assert cal is None and check.stale


def test_no_file_at_all_is_still_not_stale(tmp_path: Path) -> None:
    cal, check = calibration_state(tmp_path, context())
    assert cal is None and not check.stale


def test_an_edited_context_that_now_matches_this_desktop_is_not_valid(tmp_path: Path) -> None:
    """The case that used to read VALID: the stored binding was changed after it was saved
    and happens to equal the current desktop. Its fingerprint gives it away."""
    raw = _saved(tmp_path)  # bound to the three-monitor DESK
    laptop_only = context(MAIN)
    raw["context"] = laptop_only.as_dict()  # context_fingerprint left as saved
    _write(tmp_path, json.dumps(raw))
    cal, check = calibration_state(tmp_path, laptop_only)
    assert cal is not None  # the map is kept, as for any damaged binding...
    assert check.validity is Validity.UNVERIFIED  # ...but is never VALID
    assert "damaged" in check.reason


def test_a_fingerprint_whose_context_is_gone_is_damaged_not_legacy(tmp_path: Path) -> None:
    raw = _saved(tmp_path)
    del raw["context"]
    _write(tmp_path, json.dumps(raw))
    record = load_calibration_record(tmp_path)
    assert record is not None and record.context_unreadable
    _cal, check = calibration_state(tmp_path, context())
    assert check.validity is Validity.UNVERIFIED
    assert "damaged" in check.reason and "before YazSes recorded" not in check.reason


def test_a_file_from_before_rotation_keeps_its_recorded_fingerprint_valid(tmp_path: Path) -> None:
    """Exactly what the writer produced before `rotation` existed: the fingerprint was taken
    over the context *without* the field. Verifying against a rebuild (which adds
    ``rotation: normal``) would call every such file damaged; verifying the stored dict
    does not."""
    current = context(MAIN, RIGHT_4K)
    old = current.as_dict()
    for entry in old["topology"]["displays"]:
        del entry["rotation"]
    old_file = {
        "version": 3,
        "space": CANONICAL_SPACE,
        "source": "explicit",
        "saved_at": "2026-10-01T00:00:00+00:00",
        "A": IDENT.A.tolist(),
        "context": old,
        "context_fingerprint": digest(old),
    }
    assert old_file["context_fingerprint"] != current.fingerprint()  # the trap is real
    _write(tmp_path, json.dumps(old_file, indent=2))
    cal, check = calibration_state(tmp_path, current)
    assert cal is not None and check.validity is Validity.VALID, check.reason


def test_a_freshly_saved_file_verifies_its_own_fingerprint(tmp_path: Path) -> None:
    raw = _saved(tmp_path)
    assert raw["context_fingerprint"] == digest(raw["context"]) == context().fingerprint()
    record = load_calibration_record(tmp_path)
    assert record is not None and not record.context_unreadable


def test_a_map_in_another_coordinate_space_is_stale(tmp_path: Path) -> None:
    raw = _saved(tmp_path)
    raw["space"] = "desktop-physical-px"
    _write(tmp_path, json.dumps(raw))
    cal, check = calibration_state(tmp_path, context())
    assert cal is not None and check.stale
    assert "desktop-physical-px" in check.reason


def test_a_schema_1_file_without_a_space_is_not_stale_for_lacking_one(tmp_path: Path) -> None:
    _write(tmp_path, json.dumps({"version": 1, "A": IDENT.A.tolist()}))
    _cal, check = calibration_state(tmp_path, context())
    assert check.validity is Validity.UNVERIFIED


# ---- what doctor / status are told -------------------------------------------------


def test_the_health_probe_reports_a_damaged_file_as_stale_not_missing(tmp_path: Path) -> None:
    _write(tmp_path, "{ truncated")
    validity, reason = calibration_facts(tmp_path, "0", read_context=lambda: context())
    assert validity == "stale"
    assert "damaged" in reason and "nothing has been calibrated" not in reason


def test_the_health_probe_still_reports_no_file_as_missing(tmp_path: Path) -> None:
    validity, _reason = calibration_facts(tmp_path, "0", read_context=lambda: context())
    assert validity == "missing"
