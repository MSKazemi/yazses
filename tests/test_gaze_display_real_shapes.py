"""Display topology as a real X server and a real person produce it (EYE-DISPLAY-001, #415).

`test_gaze_topology.py` proves the decision on *fabricated* ``Display`` objects. That is
necessary and not sufficient: a fabricated topology is always well-formed, always in the
order the test wrote it, and never changes while a wizard is running. The shapes below are
the ones a fake hides:

* ``xrandr`` text exactly as the tool prints it -- a rotated panel, an output that is
  connected but switched off (a closed laptop lid), an output whose rotation is invisible in
  its rectangle;
* an upgrade -- a calibration file written before a field existed must keep its meaning;
* time -- a monitor plugged in *during* the calibration wizard, a topology read that times
  out in the middle of a session;
* geometry no panel covers -- unequal monitors have dead corners in their union;
* the platform that cannot report a layout at all.

No display server, no camera, no monitor: the runner and the provider are injected.
"""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from typer.testing import CliRunner

import yazses.cli as cli
from yazses.config import Config, GazeConfig
from yazses.gaze.calibrate import CalibrationMap, default_targets, targets_on_displays
from yazses.gaze.display import (
    XrandrTopology,
    build_topology_provider,
    current_context,
    parse_xrandr,
)
from yazses.gaze.store import (
    RefinementInfo,
    calibration_path,
    calibration_state,
    load_calibration_record,
    promote_refinement,
    save_calibration,
)
from yazses.gaze.topology import (
    CalibrationContext,
    Display,
    DisplayTopology,
    SessionTopologyGuard,
    Validity,
    check_context,
    settle_context,
)

runner = CliRunner()

IDENT = CalibrationMap(A=np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]))

# Verbatim shapes of `xrandr --query` (mode lists trimmed). The primary sits to the RIGHT of
# a second monitor, which is how a "monitor to the left" really looks on X11: the left one is
# +0+0 and the primary is +1920+0. Nothing is negative.
DOCKED = """\
Screen 0: minimum 16 x 16, current 4480 x 1440, maximum 32767 x 32767
eDP-1 disconnected (normal left inverted right x axis y axis)
DP-1 connected 1920x1080+0+0 (normal left inverted right x axis y axis) 527mm x 296mm
   1920x1080     60.00*+
HDMI-1 connected primary 2560x1440+1920+0 (normal left inverted right x axis y axis) 597mm x 336mm
   2560x1440     59.95*+
"""
LAPTOP_ONLY = """\
Screen 0: minimum 16 x 16, current 1920 x 1080, maximum 32767 x 32767
eDP-1 connected primary 1920x1080+0+0 (normal left inverted right x axis y axis) 290mm x 170mm
   1920x1080     59.96*+
"""
# The same two monitors with the left one turned 90 degrees: xrandr prints the ROTATED size.
LEFT_TURNED_LEFT = DOCKED.replace(
    "DP-1 connected 1920x1080+0+0 (", "DP-1 connected 1080x1920+0+0 left ("
)
LEFT_TURNED_RIGHT = DOCKED.replace(
    "DP-1 connected 1920x1080+0+0 (", "DP-1 connected 1080x1920+0+0 right ("
)
LEFT_UPSIDE_DOWN = DOCKED.replace(
    "DP-1 connected 1920x1080+0+0 (", "DP-1 connected 1920x1080+0+0 inverted ("
)
# Lid closed with an external monitor: the panel is still `connected`, but switched off, so
# xrandr prints no geometry for it at all.
LID_CLOSED = """\
Screen 0: minimum 16 x 16, current 2560 x 1440, maximum 32767 x 32767
eDP-1 connected (normal left inverted right x axis y axis) 290mm x 170mm
   1920x1080     59.96 +
HDMI-1 connected primary 2560x1440+0+0 (normal left inverted right x axis y axis) 597mm x 336mm
   2560x1440     59.95*+
"""
LAPTOP_LID_OPEN_WITH_EXTERNAL = """\
Screen 0: minimum 16 x 16, current 4480 x 1440, maximum 32767 x 32767
eDP-1 connected primary 1920x1080+0+0 (normal left inverted right x axis y axis) 290mm x 170mm
   1920x1080     59.96*+
HDMI-1 connected 2560x1440+1920+0 (normal left inverted right x axis y axis) 597mm x 336mm
   2560x1440     59.95*+
"""


def ctx_from(text: str, camera_id: str = "0") -> CalibrationContext:
    return CalibrationContext(
        topology=parse_xrandr(text), camera_id=camera_id, camera_width=1280, camera_height=720
    )


# --------------------------------------------------------------------------- #
# What xrandr actually prints
# --------------------------------------------------------------------------- #


def test_a_docked_desktop_keeps_xrandrs_framebuffer_origin_and_is_never_negative() -> None:
    topo = parse_xrandr(DOCKED)
    left, right = topo.displays
    assert (left.identifier, left.x, left.y) == ("DP-1", 0, 0)
    assert (right.identifier, right.x, right.y, right.primary) == ("HDMI-1", 1920, 0, True)
    # The X11 canonical origin is the framebuffer's, NOT the primary's. If someone "fixes"
    # that by shifting to a primary-relative origin, xrandr stops agreeing with the window
    # rectangles xdotool reports and every window lookup lands on the wrong monitor.
    assert topo.bounds() == (0, 0, 4480, 1440)
    assert all(d.x >= 0 and d.y >= 0 for d in topo.displays)


def test_a_rotated_panel_is_read_at_its_rotated_size_and_remembers_the_turn() -> None:
    (turned, _primary) = parse_xrandr(LEFT_TURNED_LEFT).displays
    assert (turned.width, turned.height, turned.rotation) == (1080, 1920, "left")
    assert parse_xrandr(DOCKED).displays[0].rotation == "normal"


@pytest.mark.parametrize(
    "turned",
    [LEFT_TURNED_LEFT, LEFT_TURNED_RIGHT, LEFT_UPSIDE_DOWN],
    ids=["left", "right", "inverted"],
)
def test_any_rotation_makes_a_calibration_stale_and_names_it(turned: str) -> None:
    check = check_context(ctx_from(DOCKED), ctx_from(turned))
    assert check.validity is Validity.STALE
    assert "DP-1" in check.reason


def test_left_and_right_are_the_same_rectangle_so_only_the_rotation_tells_them_apart() -> None:
    """Why `rotation` exists: size alone cannot see this change, and the map is wrong after it."""
    left = parse_xrandr(LEFT_TURNED_LEFT).displays[0]
    right = parse_xrandr(LEFT_TURNED_RIGHT).displays[0]
    assert (left.x, left.y, left.width, left.height) == (right.x, right.y, right.width, right.height)
    inverted = parse_xrandr(LEFT_UPSIDE_DOWN).displays[0]
    normal = parse_xrandr(DOCKED).displays[0]
    assert (inverted.width, inverted.height) == (normal.width, normal.height)
    check = check_context(ctx_from(LEFT_TURNED_LEFT), ctx_from(LEFT_TURNED_RIGHT))
    assert check.stale and "rotated left -> right" in check.reason


def test_closing_the_lid_removes_the_panel_instead_of_keeping_a_phantom() -> None:
    """A connected-but-off output has no geometry; it occupies no desktop coordinates."""
    assert [d.identifier for d in parse_xrandr(LID_CLOSED).displays] == ["HDMI-1"]
    check = check_context(ctx_from(LAPTOP_LID_OPEN_WITH_EXTERNAL), ctx_from(LID_CLOSED))
    assert check.stale
    assert "eDP-1" in check.reason and "removed" in check.reason


def test_the_supported_rotations_list_is_not_mistaken_for_the_current_one() -> None:
    """`(normal left inverted right ...)` lists what an output SUPPORTS."""
    line = (
        "HDMI-1 connected primary 2560x1440+0+0 (normal left inverted right x axis y axis) "
        "597mm x 336mm"
    )
    assert parse_xrandr(line).displays[0].rotation == "normal"


# --------------------------------------------------------------------------- #
# An upgrade must not strand every existing calibration
# --------------------------------------------------------------------------- #


def test_a_calibration_saved_before_rotation_existed_is_still_valid_on_an_unrotated_desktop(
    tmp_path: Path,
) -> None:
    """The file on disk is what a user upgrades with; adding a field must not void it."""
    current = ctx_from(LAPTOP_ONLY)
    modern = current.as_dict()
    for entry in modern["topology"]["displays"]:
        entry.pop("rotation")  # exactly the pre-rotation on-disk shape
    legacy_file = {
        "version": 3,
        "space": modern["space"],
        "source": "explicit",
        "saved_at": "2026-09-01T00:00:00+00:00",
        "A": IDENT.A.tolist(),
        "context": modern,
    }
    calibration_path(tmp_path).write_text(json.dumps(legacy_file))
    _cal, check = calibration_state(tmp_path, current)
    assert check.validity is Validity.VALID, check.reason


def test_the_same_legacy_file_is_stale_on_a_desktop_that_is_now_rotated(tmp_path: Path) -> None:
    unrotated = ctx_from(DOCKED)
    modern = unrotated.as_dict()
    for entry in modern["topology"]["displays"]:
        entry.pop("rotation")
    calibration_path(tmp_path).write_text(
        json.dumps({"version": 3, "A": IDENT.A.tolist(), "context": modern})
    )
    _cal, check = calibration_state(tmp_path, ctx_from(LEFT_UPSIDE_DOWN))
    assert check.stale


# --------------------------------------------------------------------------- #
# Time: the layout changes while YazSes is running
# --------------------------------------------------------------------------- #


class _Server:
    """A scripted X server: each call to `xrandr --query` pops the next reply (or raises)."""

    def __init__(self, *replies: str | Exception) -> None:
        self.replies = list(replies)
        self.calls = 0

    def __call__(self, _argv: list[str]) -> str:
        self.calls += 1
        reply = self.replies[min(self.calls, len(self.replies)) - 1]
        if isinstance(reply, Exception):
            raise reply
        return reply


def _guard_over(server: _Server, accepted: CalibrationContext) -> SessionTopologyGuard:
    provider = XrandrTopology(runner=server)
    return SessionTopologyGuard(
        accepted,
        lambda: current_context(camera_id="0", camera_size=(1280, 720), provider=provider),
        min_interval=0.0,
    )


def test_a_monitor_hot_plugged_mid_session_suspends_routing_through_the_real_parser() -> None:
    server = _Server(LAPTOP_ONLY, LAPTOP_ONLY, LAPTOP_LID_OPEN_WITH_EXTERNAL)
    guard = _guard_over(server, ctx_from(LAPTOP_ONLY))
    assert guard.suspended() is False
    assert guard.suspended() is False
    assert guard.suspended() is True
    assert guard.last_check is not None and "HDMI-1" in guard.last_check.reason


def test_a_timed_out_read_mid_session_neither_suspends_nor_resumes() -> None:
    """A busy X server makes `xrandr` time out. That is not a change -- and not a recovery."""
    timeout = TimeoutError("xrandr timed out")
    server = _Server(LAPTOP_ONLY, timeout, LAPTOP_LID_OPEN_WITH_EXTERNAL, timeout)
    guard = _guard_over(server, ctx_from(LAPTOP_ONLY))
    assert guard.suspended() is False  # unchanged
    assert guard.suspended() is False  # unreadable: unknown, so no invented change
    assert guard.suspended() is True  # a real change
    assert guard.suspended() is True  # an unreadable read after it must not clear it


def test_undocking_and_redocking_does_not_resume_routing_without_a_recalibration() -> None:
    server = _Server(LAPTOP_LID_OPEN_WITH_EXTERNAL, LAPTOP_ONLY, LAPTOP_LID_OPEN_WITH_EXTERNAL)
    guard = _guard_over(server, ctx_from(LAPTOP_ONLY))
    assert guard.suspended() is True  # docked: stale
    # Sticky: it does not even ask the server again, so un/re-docking cannot flip it.
    assert guard.suspended() is True
    assert guard.suspended() is True
    assert server.calls == 1
    guard.accept(ctx_from(LAPTOP_LID_OPEN_WITH_EXTERNAL))
    server.replies = [LAPTOP_LID_OPEN_WITH_EXTERNAL]
    server.calls = 0
    assert guard.suspended() is False


@pytest.mark.parametrize(
    ("before", "after"),
    [
        (LAPTOP_ONLY, LAPTOP_ONLY.replace("1920x1080+0+0", "1280x720+0+0")),
        (DOCKED, LEFT_UPSIDE_DOWN),
        (LAPTOP_LID_OPEN_WITH_EXTERNAL, LID_CLOSED),
    ],
    ids=["resolution-change", "rotation", "lid-closed"],
)
def test_each_kind_of_change_mid_session_suspends_routing(before: str, after: str) -> None:
    guard = _guard_over(_Server(after), ctx_from(before))
    assert guard.suspended() is True


# --------------------------------------------------------------------------- #
# The platform that cannot report a layout
# --------------------------------------------------------------------------- #


def test_a_wayland_session_reports_an_unknown_layout_not_an_empty_desktop(monkeypatch) -> None:
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    assert build_topology_provider() is None
    context = current_context(camera_id="0")
    assert context.topology.known is False
    # Unknown is a state of its own: nothing is stale (no monitor was removed) and nothing
    # is claimed valid (nothing was compared).
    check = check_context(ctx_from(LAPTOP_ONLY), context)
    assert check.validity is Validity.UNVERIFIED
    assert "unknown" in check.reason
    assert "bound to a known layout" in check.reason


def test_an_unreadable_layout_against_a_legacy_calibration_does_not_claim_it_was_bound() -> None:
    check = check_context(CalibrationContext(), CalibrationContext())
    assert check.validity is Validity.UNVERIFIED
    assert "bound to a known layout" not in check.reason


def test_gaze_routing_has_no_desktop_backend_on_wayland(monkeypatch) -> None:
    """The reason an unknown layout never reaches routing: no window control exists there."""
    from yazses.gaze.desktop import build_desktop

    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    assert build_desktop() is None


def test_an_unreadable_context_in_the_file_is_reported_as_damaged_not_as_legacy(
    tmp_path: Path,
) -> None:
    good = ctx_from(LAPTOP_ONLY).as_dict()
    good["topology"]["displays"][0].pop("w")  # a record that WAS written, then damaged
    calibration_path(tmp_path).write_text(
        json.dumps({"version": 3, "A": IDENT.A.tolist(), "context": good})
    )
    record = load_calibration_record(tmp_path)
    assert record is not None and record.context is None and record.context_unreadable
    cal, check = calibration_state(tmp_path, ctx_from(LAPTOP_ONLY))
    assert cal is not None  # the map survives; only the binding is lost
    assert check.validity is Validity.UNVERIFIED
    assert "damaged" in check.reason
    assert "before YazSes recorded" not in check.reason


def test_a_genuinely_legacy_file_still_gets_the_legacy_reason(tmp_path: Path) -> None:
    calibration_path(tmp_path).write_text(json.dumps({"version": 1, "A": IDENT.A.tolist()}))
    record = load_calibration_record(tmp_path)
    assert record is not None and not record.context_unreadable
    _cal, check = calibration_state(tmp_path, ctx_from(LAPTOP_ONLY))
    assert "before YazSes recorded" in check.reason


def test_an_unrecorded_camera_size_is_not_reported_as_a_checked_camera() -> None:
    """Production never records a capture size (0x0); 'camera unchanged' would be a claim
    about a comparison nobody made."""
    bare = dataclasses.replace(ctx_from(LAPTOP_ONLY), camera_width=0, camera_height=0)
    verdict = check_context(bare, bare)
    assert verdict.validity is Validity.VALID
    assert "identified by index only" in verdict.reason
    full = check_context(ctx_from(LAPTOP_ONLY), ctx_from(LAPTOP_ONLY))
    assert full.reason == "the screen layout and camera are unchanged"


# --------------------------------------------------------------------------- #
# Calibration targets must be somewhere a person can look
# --------------------------------------------------------------------------- #

#: Two unequal monitors: the union is 4480x1440 but the left one is only 1080 tall, so the
#: union's bottom-left corner region has no pixels in it.
UNEQUAL = parse_xrandr(DOCKED).displays


def test_the_default_grid_puts_targets_where_no_monitor_is() -> None:
    topo = DisplayTopology(UNEQUAL)
    w, h = topo.bounds()[2:]
    off_screen = [
        label for label, (x, y) in default_targets(w, h, 9) if topo.display_at(x, y) is None
    ]
    assert off_screen, "the fixture must reproduce the defect, or this test proves nothing"


@pytest.mark.parametrize("points", [4, 5, 9])
def test_targets_on_displays_are_all_on_a_screen(points: int) -> None:
    topo = DisplayTopology(UNEQUAL)
    placed = targets_on_displays(topo, points)
    assert placed
    assert all(topo.display_at(x, y) is not None for _label, (x, y) in placed)


def test_targets_follow_a_negative_origin_instead_of_assuming_zero() -> None:
    # The OS-origin-is-main-display shape (macOS/Windows): a monitor LEFT of and ABOVE it.
    topo = DisplayTopology(
        (
            Display("left", -1920, -200, 1920, 1080, primary=False),
            Display("main", 0, 0, 2560, 1440, primary=True),
        )
    )
    placed = targets_on_displays(topo, 9)
    assert all(topo.display_at(x, y) is not None for _l, (x, y) in placed)
    assert min(x for _l, (x, _y) in placed) < 0, "left monitor must get targets too"


def test_a_single_monitor_at_the_origin_keeps_the_historical_grid() -> None:
    topo = DisplayTopology((Display("eDP-1", 0, 0, 1920, 1080, primary=True),))
    assert targets_on_displays(topo, 9) == default_targets(1920, 1080, 9)


def test_an_unknown_topology_yields_no_targets_so_the_caller_falls_back() -> None:
    assert targets_on_displays(DisplayTopology(), 9) == []


# --------------------------------------------------------------------------- #
# The wizard takes minutes; the layout it stamps must be the one it measured
# --------------------------------------------------------------------------- #


def test_settle_context_prefers_the_layout_the_samples_were_taken_on() -> None:
    started, finished = ctx_from(LAPTOP_ONLY), ctx_from(LAPTOP_LID_OPEN_WITH_EXTERNAL)
    context, check = settle_context(started, finished)
    assert check.stale and context is started


def test_settle_context_survives_one_unreadable_end() -> None:
    known, unknown = ctx_from(LAPTOP_ONLY), CalibrationContext()
    assert settle_context(known, unknown)[0] is known
    assert settle_context(unknown, known)[0] is known
    both = settle_context(unknown, unknown)
    assert both[1].validity is Validity.UNVERIFIED


def _config() -> Config:
    return dataclasses.replace(Config(), gaze=dataclasses.replace(GazeConfig(), enabled=True))


class _Backend:
    name = "fake"

    def close(self) -> None:
        pass


def _wire_wizard(monkeypatch, tmp_path: Path, reads: list[CalibrationContext], captured: dict):
    """Run `yazses gaze calibrate` against scripted topology reads and canned samples."""
    monkeypatch.setattr(
        cli, "get_platform", lambda: SimpleNamespace(
            paths=SimpleNamespace(config_file=tmp_path / "c.toml", data_dir=tmp_path)
        )
    )
    monkeypatch.setattr("yazses.config.load_config", lambda _p: _config())
    monkeypatch.setattr(
        "yazses.gaze.desktop.build_desktop",
        lambda: SimpleNamespace(screen_size=lambda: (4480, 1440)),
    )
    monkeypatch.setattr(cli, "_install_feature_deps", lambda feat, *, skip: None)
    monkeypatch.setattr("yazses.gaze.factory.build_gaze", lambda _cfg: _Backend())
    monkeypatch.setattr("yazses.gaze.display.build_topology_provider", lambda: object())
    queue = list(reads)

    def read(**_kw):
        captured["reads"] = captured.get("reads", 0) + 1
        return queue.pop(0) if len(queue) > 1 else queue[0]

    monkeypatch.setattr("yazses.gaze.display.current_context", read)

    def collect(_backend, targets, _before):
        captured["targets"] = targets
        # Five well-spread samples so the affine fit is determined.
        grid = [(-0.2, -0.1), (0.2, -0.1), (0.0, 0.0), (-0.2, 0.1), (0.2, 0.1)]
        return [(g, (float(100 + 700 * (g[0] + 0.2) / 0.4), float(100 + 400 * (g[1] + 0.1) / 0.2)))
                for g in grid]

    monkeypatch.setattr("yazses.gaze.calibrate.collect_samples", collect)


def test_a_monitor_plugged_in_during_the_wizard_refuses_to_save(monkeypatch, tmp_path) -> None:
    captured: dict = {}
    # 1st read: before sampling (laptop). 2nd read: after (an external monitor appeared).
    _wire_wizard(
        monkeypatch, tmp_path,
        [ctx_from(LAPTOP_ONLY), ctx_from(LAPTOP_LID_OPEN_WITH_EXTERNAL)], captured,
    )
    result = runner.invoke(cli.app, ["gaze", "calibrate", "--no-install"])
    assert result.exit_code == 1, result.output
    assert "changed while you were calibrating" in result.output
    assert not calibration_path(tmp_path).exists(), (
        "a map must not be saved stamped with a layout it was not measured on"
    )
    assert captured["reads"] == 2


def test_an_undisturbed_wizard_binds_the_map_to_the_starting_layout(monkeypatch, tmp_path) -> None:
    captured: dict = {}
    layout = ctx_from(LAPTOP_LID_OPEN_WITH_EXTERNAL)
    _wire_wizard(monkeypatch, tmp_path, [layout, layout], captured)
    result = runner.invoke(cli.app, ["gaze", "calibrate", "--no-install"])
    assert result.exit_code == 0, result.output
    record = load_calibration_record(tmp_path)
    assert record is not None and record.context == layout
    _cal, check = calibration_state(tmp_path, layout)
    assert check.validity is Validity.VALID


def test_the_wizard_asks_for_targets_on_the_real_displays(monkeypatch, tmp_path) -> None:
    captured: dict = {}
    layout = ctx_from(DOCKED)  # 1920x1080 beside 2560x1440: the union has a dead corner
    _wire_wizard(monkeypatch, tmp_path, [layout, layout], captured)
    result = runner.invoke(cli.app, ["gaze", "calibrate", "--no-install"])
    assert result.exit_code == 0, result.output
    assert captured["targets"]
    assert all(layout.topology.display_at(x, y) is not None for _l, (x, y) in captured["targets"])


# --------------------------------------------------------------------------- #
# `yazses gaze rollback` tells the user what the restored map will do
# --------------------------------------------------------------------------- #


def _platform(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(paths=SimpleNamespace(config_file=tmp_path / "c.toml", data_dir=tmp_path))


def _rollback_world(monkeypatch, tmp_path: Path, saved: CalibrationContext, now: CalibrationContext):
    save_calibration(IDENT, tmp_path, saved)
    shifted = CalibrationMap(A=np.array([[1.0, 0.0, 40.0], [0.0, 1.0, 0.0]]))
    promote_refinement(tmp_path, shifted, RefinementInfo(60, 20, 140.0, 12.5))
    monkeypatch.setattr(cli, "get_platform", lambda: _platform(tmp_path))
    monkeypatch.setattr("yazses.config.load_config", lambda _p: _config())
    monkeypatch.setattr("yazses.gaze.display.current_context", lambda **_kw: now)


def test_rollback_onto_a_changed_desktop_says_the_restored_map_will_not_be_used(
    monkeypatch, tmp_path
) -> None:
    _rollback_world(
        monkeypatch, tmp_path, ctx_from(LAPTOP_ONLY), ctx_from(LAPTOP_LID_OPEN_WITH_EXTERNAL)
    )
    result = runner.invoke(cli.app, ["gaze", "rollback"])
    assert result.exit_code == 0, result.output
    assert "Restored the previous calibration" in result.output
    assert "will not be used" in result.output
    assert "HDMI-1" in result.output
    assert "yazses gaze calibrate" in result.output


def test_rollback_on_an_unchanged_desktop_adds_no_warning(monkeypatch, tmp_path) -> None:
    same = ctx_from(LAPTOP_ONLY)
    _rollback_world(monkeypatch, tmp_path, same, same)
    result = runner.invoke(cli.app, ["gaze", "rollback"])
    assert result.exit_code == 0, result.output
    assert "will not be used" not in result.output
    assert "could not be checked" not in result.output


def test_a_refinement_keeps_the_context_it_was_collected_under(tmp_path: Path) -> None:
    """The store never re-stamps a refined map with a newer layout."""
    original = ctx_from(LAPTOP_ONLY)
    save_calibration(IDENT, tmp_path, original)
    record = promote_refinement(
        tmp_path,
        CalibrationMap(A=np.array([[1.0, 0.0, 5.0], [0.0, 1.0, 0.0]])),
        RefinementInfo(60, 20, 10.0, 5.0),
    )
    assert record.context == original
    _cal, check = calibration_state(tmp_path, ctx_from(LAPTOP_LID_OPEN_WITH_EXTERNAL))
    assert check.stale


# --------------------------------------------------------------------------- #
# Mixed DPI: the one place the multiplication happens
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("scale", [1.0, 1.25, 1.5, 2.0, 3.0])
@pytest.mark.parametrize("origin", [(0, 0), (-1920, -200), (3840, 1080)])
def test_physical_and_logical_round_trip_for_any_scale_and_origin(scale, origin) -> None:
    d = Display("X", origin[0], origin[1], 1920, 1080, scale=scale)
    for px, py in [(0.0, 0.0), (17.0, 33.0), (1919.0 * scale, 1079.0 * scale)]:
        x, y = d.from_physical(px, py)
        assert d.contains(x, y)
        assert d.to_physical(x, y) == pytest.approx((px, py))


def test_the_seam_between_a_1x_and_a_2x_monitor_belongs_to_exactly_one() -> None:
    topo = DisplayTopology(
        (
            Display("one", 0, 0, 1920, 1080, scale=1.0, primary=True),
            Display("two", 1920, 0, 1920, 1080, scale=2.0),
        )
    )
    assert topo.display_at(1919.0, 10).identifier == "one"
    assert topo.display_at(1920.0, 10).identifier == "two"
    # The same logical point is one physical pixel of difference on the 1x panel and two on
    # the 2x one -- converting with the wrong display's scale is the bug this guards.
    assert topo.display_at(1921.0, 0).to_physical(1921.0, 0) == (2.0, 0.0)
