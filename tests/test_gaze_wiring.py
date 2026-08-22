"""Look-to-pane wiring: desktop backend, calibration store, interactive
collection, and the runtime targeter (design/v2-cognitive-layer §3.3).

All backend-agnostic — fakes stand in for xdotool, the webcam, and the desktop,
so the routing/calibration/persistence logic is pinned in CI without a camera,
X11, or the heavy gaze deps.
"""
from __future__ import annotations

import numpy as np

from yazses.gaze.calibrate import CalibrationMap, collect_samples, default_targets, fit_calibration
from yazses.gaze.desktop import XdotoolDesktop, build_desktop
from yazses.gaze.store import calibration_path, load_calibration, save_calibration
from yazses.gaze.targeter import GazeTargeter

# ---- calibration store round-trip ------------------------------------------


def test_save_and_load_calibration_round_trip(tmp_path):
    cal = CalibrationMap(A=np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]))
    path = save_calibration(cal, tmp_path)
    assert path == calibration_path(tmp_path)
    loaded = load_calibration(tmp_path)
    assert loaded is not None
    assert np.allclose(loaded.A, cal.A)


def test_load_calibration_absent_is_none(tmp_path):
    assert load_calibration(tmp_path) is None


def test_load_calibration_rejects_wrong_shape(tmp_path):
    calibration_path(tmp_path).write_text('{"version": 1, "A": [[1, 2]]}', encoding="utf-8")
    assert load_calibration(tmp_path) is None  # not 2x3 → ignored


# ---- target generation ------------------------------------------------------


def test_default_targets_9_point_grid_is_labelled_and_inset():
    targets = default_targets(1000, 800, 9)
    assert len(targets) == 9
    labels = [t[0] for t in targets]
    assert labels[0] == "top-left" and labels[4] == "centre" and labels[8] == "bottom-right"
    # 10% inset, not on the physical edge.
    assert targets[0][1] == (100, 80)
    assert targets[4][1] == (500, 400)


def test_default_targets_four_and_five_point_variants():
    assert len(default_targets(1000, 800, 4)) == 4
    assert len(default_targets(1000, 800, 5)) == 5  # corners + centre


# ---- interactive collection (I/O-agnostic) ---------------------------------


class _ScriptedBackend:
    """Yields preset gaze reads (None = no face) across estimate() calls."""

    def __init__(self, reads):
        self._reads = list(reads)
        self.closed = False

    def estimate(self):
        return self._reads.pop(0) if self._reads else None

    def close(self):
        self.closed = True


def test_collect_samples_averages_reads_and_prompts_each_point():
    targets = [("a", (10, 20)), ("b", (30, 40))]
    # 2 reads per point (per_point=2): point a → mean of (1,1),(3,3)=(2,2)
    backend = _ScriptedBackend([(1.0, 1.0), (3.0, 3.0), (5.0, 5.0), (7.0, 7.0)])
    seen = []
    samples = collect_samples(backend, targets, lambda label, xy: seen.append(label), per_point=2)
    assert seen == ["a", "b"]  # prompted once per target
    assert samples[0] == ((2.0, 2.0), (10.0, 20.0))
    assert samples[1] == ((6.0, 6.0), (30.0, 40.0))


def test_collect_samples_drops_points_with_no_face():
    targets = [("a", (10, 20)), ("b", (30, 40))]
    backend = _ScriptedBackend([None, None, (5.0, 5.0), (5.0, 5.0)])  # a=no face, b=ok
    samples = collect_samples(backend, targets, lambda *_: None, per_point=2)
    assert len(samples) == 1
    assert samples[0][1] == (30.0, 40.0)


def test_collected_samples_fit_a_recoverable_map():
    # end-to-end: collect → fit recovers a known linear gaze→screen mapping.
    def truth(yaw, pitch):
        return (100 * yaw + 500, 100 * pitch + 400)
    targets = [(f"p{i}", truth(y, p)) for i, (y, p) in enumerate([(-1, -1), (1, -1), (0, 1)])]
    backend = _ScriptedBackend([(-1.0, -1.0), (1.0, -1.0), (0.0, 1.0)])
    samples = collect_samples(backend, targets, lambda *_: None, per_point=1)
    cal = fit_calibration(samples)
    assert np.allclose(cal.predict(0.5, 0.5), truth(0.5, 0.5), atol=1e-6)


# ---- XdotoolDesktop parsing (fake runner) ----------------------------------


def _fake_runner(responses):
    def run(argv):
        key = argv[1]  # the xdotool verb
        return responses[key]
    return run


def test_xdotool_screen_size_and_geometry_parse():
    responses = {
        "getdisplaygeometry": "1920 1200\n",
        "search": "111\n222\n",
        "getwindowgeometry": (
            "Window 111\n  Position: 66,32 (screen: 0)\n  Geometry: 800x600\n"
        ),
        "getwindowfocus": "222\n",
    }
    d = XdotoolDesktop(runner=_fake_runner(responses))
    assert d.screen_size() == (1920, 1200)
    wins = d.list_windows()
    assert wins == [(111, 66, 32, 800, 600), (222, 66, 32, 800, 600)]
    assert d.focused_window() == 222


def test_list_windows_drops_fullscreen_desktop_container():
    # The desktop/root window (1674) spans the whole screen; it must be filtered
    # out so it can't shadow the real windows in window_at_point.
    geometries = {
        "1674": "Window 1674\n  Position: 0,0 (screen: 0)\n  Geometry: 1920x1200\n",
        "111": "Window 111\n  Position: 0,0 (screen: 0)\n  Geometry: 960x1080\n",
        "222": "Window 222\n  Position: 960,0 (screen: 0)\n  Geometry: 960x1080\n",
    }

    def run(argv):
        verb = argv[1]
        if verb == "getdisplaygeometry":
            return "1920 1200\n"
        if verb == "search":
            return "1674\n111\n222\n"
        if verb == "getwindowgeometry":
            return geometries[argv[2]]
        raise AssertionError(verb)

    wins = XdotoolDesktop(runner=run).list_windows()
    ids = [w[0] for w in wins]
    assert ids == [111, 222]  # 1674 (full-screen desktop) dropped


def test_xdotool_activate_issues_windowactivate():
    calls = []
    d = XdotoolDesktop(runner=lambda argv: calls.append(argv) or "")
    d.activate(999)
    assert calls == [["xdotool", "windowactivate", "999"]]


def test_build_desktop_none_off_x11(monkeypatch):
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    assert build_desktop() is None


def test_build_desktop_none_without_xdotool(monkeypatch):
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    monkeypatch.setattr("yazses.gaze.desktop.shutil.which", lambda _: None)
    assert build_desktop() is None


# ---- GazeTargeter runtime routing ------------------------------------------


class _FakeDesktop:
    def __init__(self, focused, windows):
        self._focused = focused
        self._windows = windows
        self.activated = []

    def focused_window(self):
        return self._focused

    def list_windows(self):
        return self._windows

    def activate(self, wid):
        self.activated.append(wid)


def _identity_cal():
    # predict(x, y) == (x, y): screen point equals the gaze angle for easy tests.
    return CalibrationMap(A=np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]))


def _two_panes():
    return [("editor", 0, 0, 500, 1000), ("browser", 500, 0, 500, 1000)]


def test_targeter_focuses_looked_at_window():
    backend = _ScriptedBackend([(700, 500)])  # lands in browser (x>=500)
    desktop = _FakeDesktop(focused="editor", windows=_two_panes())
    t = GazeTargeter(backend, _identity_cal(), desktop)
    d = t.retarget()
    assert d.used_gaze is True and d.target == "browser"
    assert desktop.activated == ["browser"]


def test_targeter_no_face_falls_back_to_focus_without_activating():
    backend = _ScriptedBackend([None])  # no confident gaze
    desktop = _FakeDesktop(focused="editor", windows=_two_panes())
    d = GazeTargeter(backend, _identity_cal(), desktop).retarget()
    assert d.used_gaze is False and d.target == "editor"
    assert desktop.activated == []


def test_targeter_gaze_outside_all_windows_falls_back():
    backend = _ScriptedBackend([(9999, 9999)])  # outside every pane
    desktop = _FakeDesktop(focused="editor", windows=_two_panes())
    d = GazeTargeter(backend, _identity_cal(), desktop).retarget()
    assert d.used_gaze is False and d.target == "editor"
    assert desktop.activated == []


def test_targeter_does_not_reactivate_the_already_focused_window():
    backend = _ScriptedBackend([(100, 500)])  # lands in editor, which is focused
    desktop = _FakeDesktop(focused="editor", windows=_two_panes())
    d = GazeTargeter(backend, _identity_cal(), desktop).retarget()
    assert d.target == "editor"
    assert desktop.activated == []  # no redundant re-focus


def test_targeter_activation_failure_falls_back_gracefully():
    class _BoomDesktop(_FakeDesktop):
        def activate(self, wid):
            raise RuntimeError("focus denied")

    backend = _ScriptedBackend([(700, 500)])
    desktop = _BoomDesktop(focused="editor", windows=_two_panes())
    d = GazeTargeter(backend, _identity_cal(), desktop).retarget()
    assert d.used_gaze is False and d.target == "editor"  # never raises


def test_targeter_close_releases_backend():
    backend = _ScriptedBackend([])
    GazeTargeter(backend, _identity_cal(), _FakeDesktop("e", [])).close()
    assert backend.closed is True


# ---- daemon hook: _on_hold_start fires the targeter ------------------------


def test_daemon_hold_start_calls_targeter_when_present():
    from yazses.config import Config
    from yazses.core.daemon import Daemon
    from yazses.platform import get_platform

    class _SpyTargeter:
        def __init__(self):
            self.calls = 0

        def retarget(self, activate=True):
            self.calls += 1

    d = Daemon(config=Config(), platform=get_platform())
    spy = _SpyTargeter()
    d._gaze_targeter = spy
    d._on_hold_start(0)
    assert spy.calls == 1


def test_daemon_hold_start_no_targeter_is_noop():
    from yazses.config import Config
    from yazses.core.daemon import Daemon
    from yazses.platform import get_platform

    d = Daemon(config=Config(), platform=get_platform())
    assert d._gaze_targeter is None
    d._on_hold_start(0)  # must not raise when gaze is dormant


def test_daemon_build_gaze_targeter_dormant_by_default():
    from yazses.config import Config
    from yazses.core.daemon import Daemon
    from yazses.platform import get_platform

    d = Daemon(config=Config(), platform=get_platform())
    # gaze disabled → no targeter even though the method runs.
    assert d._build_gaze_targeter(Config()) is None
