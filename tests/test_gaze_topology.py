"""A gaze calibration knows which desktop it was made on, and says so (ADR-v2-149).

The bug this file exists to prevent does not look like a bug. A calibration fitted on
a single laptop panel keeps returning screen coordinates after the laptop is docked to
two 4K monitors; they are simply the wrong coordinates, and the dictation lands in the
wrong window with no error anywhere. So the fixtures here are *fabricated topologies* —
no display server, no camera, no second monitor — and they check the three things that
can go wrong: the coordinate maths (HiDPI, negative origins), the identity (does the
fingerprint actually move when the desktop does), and the decision (valid / unverified /
stale, and never "silently rescale").
"""
from __future__ import annotations

import json

import numpy as np
import pytest

from yazses.gaze.calibrate import CalibrationMap
from yazses.gaze.display import parse_xrandr
from yazses.gaze.store import (
    calibration_path,
    calibration_state,
    load_calibration,
    load_calibration_record,
    save_calibration,
)
from yazses.gaze.targeter import GazeTargeter
from yazses.gaze.topology import (
    CANONICAL_SPACE,
    CalibrationContext,
    Display,
    DisplayTopology,
    SessionTopologyGuard,
    Validity,
    check_context,
)

# ---- fabricated desktops -------------------------------------------------

LAPTOP = Display("eDP-1", 0, 0, 1920, 1080, scale=1.0, primary=True)
LAPTOP_HIDPI = Display("eDP-1", 0, 0, 1920, 1080, scale=2.0, primary=True)
RIGHT_4K = Display("HDMI-1", 1920, 0, 1920, 1080, scale=2.0)
#: The case a naive implementation gets wrong: a monitor to the LEFT has a
#: negative origin, so every bound is a min(), never an abs().
LEFT_MONITOR = Display("DP-2", -1280, -200, 1280, 1024, scale=1.0)


def ctx(*displays, camera_id: str = "0", camera_size: tuple[int, int] = (1280, 720)):
    return CalibrationContext(
        topology=DisplayTopology(displays),
        camera_id=camera_id,
        camera_width=camera_size[0],
        camera_height=camera_size[1],
    )


# ---- coordinate space ----------------------------------------------------


def test_scale_one_display_converts_as_identity():
    x, y = LAPTOP.to_physical(100.0, 200.0)
    assert (x, y) == (100.0, 200.0)
    assert LAPTOP.from_physical(x, y) == (100.0, 200.0)


def test_hidpi_display_converts_logical_to_physical_pixels():
    # A 2.0-scale panel occupies 1920x1080 *logical* px and 3840x2160 physical.
    assert LAPTOP_HIDPI.to_physical(1919.0, 1079.0) == (3838.0, 2158.0)
    assert LAPTOP_HIDPI.from_physical(3838.0, 2158.0) == (1919.0, 1079.0)


def test_secondary_hidpi_display_subtracts_its_origin_before_scaling():
    # Canonical (1920, 0) is the top-left *of that monitor*, i.e. physical (0, 0).
    assert RIGHT_4K.to_physical(1920.0, 0.0) == (0.0, 0.0)
    assert RIGHT_4K.to_physical(2920.0, 100.0) == (2000.0, 200.0)
    assert RIGHT_4K.from_physical(2000.0, 200.0) == (2920.0, 100.0)


def test_negative_origin_monitor_is_inside_the_desktop_bounds():
    topo = DisplayTopology((LAPTOP, LEFT_MONITOR))
    assert topo.bounds() == (-1280, -200, 1920 + 1280, 1080 + 200)
    assert topo.display_at(-100.0, -100.0) is LEFT_MONITOR
    assert topo.display_at(10.0, 10.0) is LAPTOP
    assert topo.display_at(5000.0, 0.0) is None


def test_primary_is_the_flagged_display_not_the_first_one():
    topo = DisplayTopology((LEFT_MONITOR, LAPTOP))
    assert topo.primary is LAPTOP
    # ...and with nothing flagged, the first in canonical order.
    assert DisplayTopology((LEFT_MONITOR,)).primary is LEFT_MONITOR


def test_unknown_topology_is_empty_not_a_desktop_with_no_monitors():
    unknown = DisplayTopology()
    assert unknown.known is False
    assert unknown.bounds() is None
    assert unknown.primary is None


def test_a_display_cannot_have_a_zero_size_or_scale():
    with pytest.raises(ValueError):
        Display("bad", 0, 0, 0, 1080)
    with pytest.raises(ValueError):
        Display("bad", 0, 0, 1920, 1080, scale=0.0)


# ---- identity ------------------------------------------------------------


def test_fingerprint_ignores_the_order_the_displays_were_listed_in():
    assert ctx(LAPTOP, RIGHT_4K).fingerprint() == ctx(RIGHT_4K, LAPTOP).fingerprint()


def test_fingerprint_survives_a_json_round_trip():
    # It must be recomputable in the *next* process; hash() is salted per process
    # and would silently invalidate every calibration on restart.
    before = ctx(LAPTOP, LEFT_MONITOR)
    after = CalibrationContext.from_dict(json.loads(json.dumps(before.as_dict())))
    assert after == before
    assert after.fingerprint() == before.fingerprint()


@pytest.mark.parametrize(
    "changed",
    [
        pytest.param(ctx(LAPTOP, RIGHT_4K), id="monitor-added"),
        pytest.param(ctx(Display("eDP-1", 0, 0, 1280, 720, primary=True)), id="resolution"),
        pytest.param(ctx(LAPTOP_HIDPI), id="scale"),
        pytest.param(ctx(Display("eDP-1", 100, 0, 1920, 1080, primary=True)), id="moved"),
        pytest.param(ctx(Display("eDP-1", 0, 0, 1920, 1080)), id="primary-flag"),
        pytest.param(ctx(LAPTOP, camera_id="2"), id="camera"),
        pytest.param(ctx(LAPTOP, camera_size=(640, 480)), id="camera-size"),
    ],
)
def test_every_material_change_moves_the_fingerprint(changed):
    assert changed.fingerprint() != ctx(LAPTOP).fingerprint()


# ---- the decision --------------------------------------------------------


def test_an_unchanged_desktop_reuses_the_calibration():
    check = check_context(ctx(LAPTOP, RIGHT_4K), ctx(RIGHT_4K, LAPTOP))
    assert check.validity is Validity.VALID
    assert check.usable and not check.stale


def test_a_new_monitor_makes_the_calibration_stale_and_names_it():
    check = check_context(ctx(LAPTOP), ctx(LAPTOP, RIGHT_4K))
    assert check.validity is Validity.STALE
    assert not check.usable
    assert any("HDMI-1" in c and "added" in c for c in check.changes), check.changes


def test_a_removed_monitor_is_stale():
    check = check_context(ctx(LAPTOP, RIGHT_4K), ctx(LAPTOP))
    assert check.stale
    assert any("HDMI-1" in c and "removed" in c for c in check.changes), check.changes


def test_a_resolution_change_is_stale_and_reports_both_sizes():
    check = check_context(ctx(LAPTOP), ctx(Display("eDP-1", 0, 0, 1280, 720, primary=True)))
    assert check.stale
    assert any("1920x1080 -> 1280x720" in c for c in check.changes), check.changes


def test_a_scale_change_is_stale_rather_than_silently_rescaled():
    # The ADR rejects auto-scaling coefficients as a general rule: this is the test
    # that would fail if someone "helpfully" multiplied the map by 2 instead.
    check = check_context(ctx(LAPTOP), ctx(LAPTOP_HIDPI))
    assert check.stale
    assert any("scale 1x -> 2x" in c for c in check.changes), check.changes


def test_a_moved_monitor_is_stale_and_reports_signed_origins():
    moved = Display("DP-2", -1280, 0, 1280, 1024)
    check = check_context(ctx(LAPTOP, LEFT_MONITOR), ctx(LAPTOP, moved))
    assert check.stale
    assert any("-1280-200 -> -1280+0" in c for c in check.changes), check.changes


def test_a_new_primary_monitor_is_stale():
    swapped_a = Display("eDP-1", 0, 0, 1920, 1080)
    swapped_b = Display("HDMI-1", 1920, 0, 1920, 1080, scale=2.0, primary=True)
    check = check_context(ctx(LAPTOP, RIGHT_4K), ctx(swapped_a, swapped_b))
    assert check.stale
    assert any("primary monitor changed" in c for c in check.changes), check.changes


def test_a_different_camera_is_stale():
    check = check_context(ctx(LAPTOP), ctx(LAPTOP, camera_id="2"))
    assert check.stale
    assert any("camera changed" in c for c in check.changes), check.changes


def test_a_calibration_without_a_stored_context_is_unverified_not_stale():
    # The legacy file on an existing install. Refusing it would delete a working
    # setup to prove a point; pretending it is valid would be a lie.
    check = check_context(None, ctx(LAPTOP))
    assert check.validity is Validity.UNVERIFIED
    assert check.usable
    assert "recalibrate" in check.reason


def test_an_unreadable_display_layout_is_unverified_not_stale():
    # No xrandr / not X11. Not being able to look is not evidence of a change.
    check = check_context(ctx(LAPTOP), ctx())
    assert check.validity is Validity.UNVERIFIED
    assert check.usable
    check = check_context(ctx(LAPTOP), None)
    assert check.validity is Validity.UNVERIFIED


def test_a_stale_verdict_always_carries_a_reason_a_user_can_read():
    check = check_context(ctx(LAPTOP), ctx(LAPTOP, RIGHT_4K))
    assert check.reason.startswith("the calibration was made on a different setup:")
    assert check.changes


# ---- persistence ---------------------------------------------------------


def _map() -> CalibrationMap:
    return CalibrationMap(A=np.arange(6, dtype="float64").reshape(2, 3))


def test_saving_with_a_context_round_trips_and_validates(tmp_path):
    context = ctx(LAPTOP, RIGHT_4K)
    save_calibration(_map(), tmp_path, context)
    record = load_calibration_record(tmp_path)
    assert record is not None
    assert record.context == context
    cal, check = calibration_state(tmp_path, context)
    assert cal is not None and check.validity is Validity.VALID


def test_saved_context_never_contains_frames_or_landmarks(tmp_path):
    # ADR-v2-149: the whole point of a fingerprint is that it is not biometric.
    save_calibration(_map(), tmp_path, ctx(LAPTOP))
    raw = calibration_path(tmp_path).read_text(encoding="utf-8")
    for forbidden in ("frame", "landmark", "image", "blendshape", "pixels_b64"):
        assert forbidden not in raw.lower()
    assert CANONICAL_SPACE in raw


def test_a_legacy_version_1_file_still_loads_and_reads_as_unverified(tmp_path):
    # Exactly what `save_calibration` wrote before this ADR.
    calibration_path(tmp_path).write_text(
        json.dumps({"version": 1, "A": [[1, 2, 3], [4, 5, 6]]}), encoding="utf-8"
    )
    assert load_calibration(tmp_path) is not None  # the old entry point is unchanged
    record = load_calibration_record(tmp_path)
    assert record is not None and record.context is None
    cal, check = calibration_state(tmp_path, ctx(LAPTOP))
    assert cal is not None, "a user's existing calibration must not be thrown away"
    assert check.validity is Validity.UNVERIFIED


def test_a_corrupt_context_loses_the_binding_not_the_calibration(tmp_path):
    calibration_path(tmp_path).write_text(
        json.dumps({"version": 2, "A": [[1, 2, 3], [4, 5, 6]], "context": "not an object"}),
        encoding="utf-8",
    )
    record = load_calibration_record(tmp_path)
    assert record is not None and record.context is None
    assert check_context(record.context, ctx(LAPTOP)).validity is Validity.UNVERIFIED


def test_calibration_state_refuses_a_map_from_a_different_desktop(tmp_path):
    save_calibration(_map(), tmp_path, ctx(LAPTOP))
    cal, check = calibration_state(tmp_path, ctx(LAPTOP, RIGHT_4K))
    assert cal is not None      # the file is still there...
    assert check.stale          # ...and the caller is told not to route with it


def test_calibration_state_with_no_file_returns_no_map(tmp_path):
    cal, _check = calibration_state(tmp_path, ctx(LAPTOP))
    assert cal is None


# ---- the display-server backend (pure parser half) -----------------------

XRANDR_TWO_MONITORS = """\
Screen 0: minimum 320 x 200, current 3840 x 1200, maximum 16384 x 16384
eDP-1 connected primary 1920x1200+0+0 (normal left inverted right x axis y axis) 302mm x 189mm
   1920x1200     60.00*+
   1920x1080     60.00
HDMI-1 connected 1920x1080+1920+0 (normal left inverted right x axis y axis) 597mm x 336mm
   1920x1080     60.00*+
DP-1 disconnected (normal left inverted right x axis y axis)
DP-2 connected (normal left inverted right x axis y axis)
"""


def test_xrandr_parses_connected_outputs_with_their_primary_flag():
    topo = parse_xrandr(XRANDR_TWO_MONITORS)
    assert [d.identifier for d in topo.displays] == ["eDP-1", "HDMI-1"]
    assert topo.primary is not None and topo.primary.identifier == "eDP-1"
    assert topo.displays[1].x == 1920


def test_xrandr_ignores_disconnected_and_mode_lines():
    topo = parse_xrandr(XRANDR_TWO_MONITORS)
    names = {d.identifier for d in topo.displays}
    assert "DP-1" not in names          # disconnected
    assert "DP-2" not in names          # connected but no active mode
    assert len(topo.displays) == 2      # not one display per mode line


def test_xrandr_parses_a_negative_origin():
    topo = parse_xrandr(
        "eDP-1 connected primary 1920x1080+0+0 (normal) 302mm x 189mm\n"
        "DP-2 connected 1280x1024-1280-200 (normal) 300mm x 200mm\n"
    )
    left = [d for d in topo.displays if d.identifier == "DP-2"][0]
    assert (left.x, left.y) == (-1280, -200)


def test_unreadable_xrandr_output_is_unknown_not_an_empty_desktop():
    topo = parse_xrandr("command not found\n")
    assert topo.known is False
    assert check_context(ctx(LAPTOP), CalibrationContext(topology=topo)).usable


# ---- suspension while the session is running -----------------------------


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_the_guard_does_not_suspend_while_the_desktop_is_unchanged():
    guard = SessionTopologyGuard(ctx(LAPTOP), lambda: ctx(LAPTOP), min_interval=0.0)
    assert guard.suspended() is False


def test_the_guard_suspends_when_a_monitor_appears_mid_session():
    live = [ctx(LAPTOP)]
    guard = SessionTopologyGuard(ctx(LAPTOP), lambda: live[0], min_interval=0.0)
    assert guard.suspended() is False
    live[0] = ctx(LAPTOP, RIGHT_4K)
    assert guard.suspended() is True
    assert guard.last_check is not None and guard.last_check.stale


def test_suspension_is_sticky_until_a_recalibration_accepts_the_new_layout():
    live = [ctx(LAPTOP, RIGHT_4K)]
    guard = SessionTopologyGuard(ctx(LAPTOP), lambda: live[0], min_interval=0.0)
    assert guard.suspended() is True
    # Unplugging the monitor again does NOT resume routing: the map was never
    # revalidated, and resuming on a coincidence is how wrong coordinates return.
    live[0] = ctx(LAPTOP)
    assert guard.suspended() is True
    guard.accept(ctx(LAPTOP))
    assert guard.suspended() is False


def test_the_guard_rate_limits_its_polling():
    clock = _Clock()
    calls = []

    def read():
        calls.append(clock.now)
        return ctx(LAPTOP)

    guard = SessionTopologyGuard(ctx(LAPTOP), read, min_interval=5.0, clock=clock)
    assert guard.suspended() is False
    guard.suspended()
    guard.suspended()
    assert len(calls) == 1, "a dictation hold must not spawn a subprocess every time"
    clock.now = 6.0
    guard.suspended()
    assert len(calls) == 2


def test_a_failing_topology_read_never_invents_a_change():
    def boom():
        raise OSError("xrandr died")

    guard = SessionTopologyGuard(ctx(LAPTOP), boom, min_interval=0.0)
    assert guard.suspended() is False


# ---- the runtime refuses to route with a suspended guard -----------------


class _FakeDesktop:
    def __init__(self) -> None:
        self.activated: list[int] = []

    def screen_size(self):
        return (1920, 1080)

    def list_windows(self):
        return [(7, 0, 0, 800, 600)]

    def focused_window(self):
        return 42

    def activate(self, window_id):
        self.activated.append(window_id)


class _FakeGaze:
    name = "fake"

    def __init__(self) -> None:
        self.samples = 0

    def estimate(self):
        self.samples += 1
        return (0.0, 0.0)

    def close(self):
        pass


def _always_hits_window_7():
    # A map whose prediction lands inside the fake window, so a *successful* route
    # is the observable difference between suspended and not.
    return CalibrationMap(A=np.array([[0.0, 0.0, 100.0], [0.0, 0.0, 100.0]]))


def test_a_suspended_targeter_keeps_the_focused_window_and_never_opens_the_camera():
    desktop, backend = _FakeDesktop(), _FakeGaze()
    guard = SessionTopologyGuard(ctx(LAPTOP), lambda: ctx(LAPTOP, RIGHT_4K), min_interval=0.0)
    targeter = GazeTargeter(
        backend, _always_hits_window_7(), desktop, 0.5, topology_guard=guard
    )
    decision = targeter.retarget()
    assert decision.target == 42 and decision.used_gaze is False
    assert desktop.activated == []
    assert backend.samples == 0, "no frame should be captured for a route that cannot be used"


def test_the_same_targeter_routes_normally_once_the_layout_is_accepted():
    desktop, backend = _FakeDesktop(), _FakeGaze()
    live = [ctx(LAPTOP, RIGHT_4K)]
    guard = SessionTopologyGuard(ctx(LAPTOP), lambda: live[0], min_interval=0.0)
    targeter = GazeTargeter(
        backend, _always_hits_window_7(), desktop, 0.5, topology_guard=guard
    )
    assert targeter.retarget().used_gaze is False
    guard.accept(live[0])
    decision = targeter.retarget()
    assert decision.used_gaze is True and decision.target == 7
    assert desktop.activated == [7]


def test_a_targeter_without_a_guard_behaves_exactly_as_before():
    desktop, backend = _FakeDesktop(), _FakeGaze()
    targeter = GazeTargeter(backend, _always_hits_window_7(), desktop, 0.5)
    assert targeter.retarget().target == 7
