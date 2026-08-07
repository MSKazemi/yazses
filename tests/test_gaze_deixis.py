"""Gaze deixis ("close this / focus that") + real per-frame gaze confidence.

Pins the two 10x upgrades to Glance-Type: (1) the MediaPipe backend's
eye-agreement confidence replaces the old hard-coded 1.0, so
``[gaze] confidence_min`` actually gates routing for the default backend;
(2) demonstrative commands resolve against the gaze snapshot, with ADR-v2-010's
``needs_confirm`` policy wired for destructive actions. All fakes — no camera,
no X11, no heavy deps.
"""
from __future__ import annotations

from dataclasses import replace

import numpy as np

from yazses.config import Config, GazeConfig
from yazses.core.daemon import Daemon
from yazses.gaze.calibrate import CalibrationMap
from yazses.gaze.confidence import GazeSample, eye_agreement_confidence
from yazses.gaze.deixis import parse_deixis, requires_confirm
from yazses.gaze.desktop import XdotoolDesktop
from yazses.gaze.route import RouteDecision
from yazses.gaze.targeter import GazeTargeter
from yazses.platform import get_platform

# ---- eye-agreement confidence ----------------------------------------------


def test_identical_eyes_give_full_confidence():
    assert eye_agreement_confidence((0.1, 0.2), (0.1, 0.2)) == 1.0


def test_disagreeing_eyes_lose_confidence_linearly():
    # distance 0.2 with scale 0.4 → 0.5
    assert abs(eye_agreement_confidence((0.0, 0.0), (0.2, 0.0)) - 0.5) < 1e-9


def test_disagreement_beyond_scale_is_zero():
    assert eye_agreement_confidence((0.0, 0.0), (0.5, 0.5)) == 0.0


def test_nonpositive_scale_disables_the_gate():
    assert eye_agreement_confidence((0.0, 0.0), (9.0, 9.0), scale=0.0) == 1.0


# ---- targeter consumes per-sample confidence --------------------------------


class _SampleBackend:
    """Backend exposing estimate_sample (the mediapipe shape)."""

    def __init__(self, sample):
        self._sample = sample

    def estimate_sample(self):
        return self._sample

    def close(self):
        pass


class _FakeDesktop:
    def __init__(self, focused, windows):
        self._focused = focused
        self._windows = windows
        self.activated = []
        self.closed = []
        self.minimized = []

    def focused_window(self):
        return self._focused

    def list_windows(self):
        return self._windows

    def activate(self, wid):
        self.activated.append(wid)

    def close(self, wid):
        self.closed.append(wid)

    def minimize(self, wid):
        self.minimized.append(wid)


def _identity_cal():
    return CalibrationMap(A=np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]))


def _two_panes():
    return [("editor", 0, 0, 500, 1000), ("browser", 500, 0, 500, 1000)]


def test_confident_sample_routes_to_looked_at_window():
    backend = _SampleBackend(GazeSample(700, 500, confidence=0.9))
    desktop = _FakeDesktop("editor", _two_panes())
    t = GazeTargeter(backend, _identity_cal(), desktop, confidence_min=0.5)
    decision = t.retarget()
    assert decision.used_gaze and decision.target == "browser"
    assert desktop.activated == ["browser"]
    assert t.last_decision is decision


def test_low_confidence_sample_falls_back_to_focus():
    # The pre-fix behaviour hard-coded confidence 1.0, which would have routed.
    backend = _SampleBackend(GazeSample(700, 500, confidence=0.2))
    desktop = _FakeDesktop("editor", _two_panes())
    t = GazeTargeter(backend, _identity_cal(), desktop, confidence_min=0.5)
    decision = t.retarget()
    assert not decision.used_gaze and decision.target == "editor"
    assert desktop.activated == []


def test_retarget_without_activate_snapshots_but_does_not_focus():
    backend = _SampleBackend(GazeSample(700, 500, confidence=0.9))
    desktop = _FakeDesktop("editor", _two_panes())
    t = GazeTargeter(backend, _identity_cal(), desktop, confidence_min=0.5)
    decision = t.retarget(activate=False)
    assert decision.used_gaze and decision.target == "browser"
    assert desktop.activated == []          # deixis-only mode: no focus steal
    assert t.last_decision is decision


def test_estimate_only_backend_still_counts_as_confident():
    class _EstimateOnly:
        def estimate(self):
            return (700, 500)

    desktop = _FakeDesktop("editor", _two_panes())
    t = GazeTargeter(_EstimateOnly(), _identity_cal(), desktop, confidence_min=0.5)
    decision = t.retarget()
    assert decision.used_gaze and decision.target == "browser"


# ---- deixis parser ----------------------------------------------------------


def test_parse_deixis_matches_demonstrative_commands():
    assert parse_deixis("close this").action == "close"
    assert parse_deixis("Close that window.").action == "close"
    assert parse_deixis("focus this one").action == "focus"
    assert parse_deixis("switch to that").action == "focus"
    assert parse_deixis("go to this pane").action == "focus"
    assert parse_deixis("minimise that").action == "minimize"


def test_parse_deixis_rejects_non_deixis_phrases():
    assert parse_deixis("close the window") is None       # no demonstrative
    assert parse_deixis("this is nice") is None           # demonstrative first
    assert parse_deixis("focus") is None                  # no object
    assert parse_deixis("close this file quickly") is None  # not whole-utterance
    assert parse_deixis("I said close this yesterday") is None


def test_only_close_is_destructive():
    assert parse_deixis("close this").destructive
    assert not parse_deixis("focus this").destructive
    assert not parse_deixis("minimize this").destructive


# ---- confirm policy ---------------------------------------------------------


def _gaze_routed(target="browser"):
    return RouteDecision(target=target, used_gaze=True, confident=True)


def _focus_fallback(target="editor"):
    return RouteDecision(target=target, used_gaze=False, confident=False)


def test_destructive_gaze_routed_action_requires_confirm():
    intent = parse_deixis("close this")
    assert requires_confirm(intent, _gaze_routed(), confirm_destructive=True)


def test_focus_fallback_and_nondestructive_skip_confirm():
    assert not requires_confirm(parse_deixis("close this"), _focus_fallback(), True)
    assert not requires_confirm(parse_deixis("focus this"), _gaze_routed(), True)


def test_confirm_destructive_off_disables_the_gate():
    assert not requires_confirm(parse_deixis("close this"), _gaze_routed(), False)


# ---- window actions ---------------------------------------------------------


def test_window_action_dispatches_to_desktop_methods():
    desktop = _FakeDesktop("editor", _two_panes())
    t = GazeTargeter(_SampleBackend(None), _identity_cal(), desktop)
    assert t.window_action("focus", "w1") and desktop.activated == ["w1"]
    assert t.window_action("close", "w2") and desktop.closed == ["w2"]
    assert t.window_action("minimize", "w3") and desktop.minimized == ["w3"]
    assert not t.window_action("explode", "w4")


def test_window_action_honest_false_when_desktop_lacks_it():
    class _FocusOnlyDesktop:
        def activate(self, wid):
            pass

    t = GazeTargeter(_SampleBackend(None), _identity_cal(), _FocusOnlyDesktop())
    assert not t.window_action("close", "w1")


def test_xdotool_close_and_minimize_argv():
    calls = []
    d = XdotoolDesktop(runner=lambda argv: calls.append(argv) or "")
    d.close(42)
    d.minimize(43)
    assert calls == [
        ["xdotool", "windowclose", "42"],
        ["xdotool", "windowminimize", "43"],
    ]


# ---- daemon _try_deixis -----------------------------------------------------


class _FakeTargeter:
    def __init__(self, decision):
        self.last_decision = decision
        self.actions = []

    def window_action(self, action, target):
        self.actions.append((action, target))
        return True


def _daemon(**gaze) -> Daemon:
    cfg = replace(Config(), gaze=replace(GazeConfig(), **gaze))
    return Daemon(config=cfg, platform=get_platform())


def test_try_deixis_focus_acts_immediately():
    d = _daemon(enabled=True, deixis=True)
    d._gaze_targeter = _FakeTargeter(_gaze_routed("browser"))
    event: dict = {}
    assert d._try_deixis("focus this", event)
    assert d._gaze_targeter.actions == [("focus", "browser")]
    assert event["intent_type"] == "deixis"


def test_try_deixis_close_gaze_routed_defers_to_confirm(mocker):
    notify = mocker.patch("yazses.system.notify.notify")
    d = _daemon(enabled=True, deixis=True)
    d._gaze_targeter = _FakeTargeter(_gaze_routed("browser"))
    assert d._try_deixis("close this", {})
    assert d._gaze_targeter.actions == []          # not closed yet
    assert notify.called                            # confirm toast shown


def test_try_deixis_close_on_focus_fallback_runs_directly():
    # Not gaze-routed → the target IS the focused window; no confirm needed.
    d = _daemon(enabled=True, deixis=True)
    d._gaze_targeter = _FakeTargeter(_focus_fallback("editor"))
    assert d._try_deixis("close this", {})
    assert d._gaze_targeter.actions == [("close", "editor")]


def test_try_deixis_non_deixis_phrase_not_consumed():
    d = _daemon(enabled=True, deixis=True)
    d._gaze_targeter = _FakeTargeter(_gaze_routed())
    assert not d._try_deixis("note to self buy milk", {})


def test_try_deixis_without_targeter_not_consumed():
    d = _daemon(enabled=True, deixis=True)
    d._gaze_targeter = None
    assert not d._try_deixis("close this", {})


def test_try_deixis_no_gaze_target_consumes_without_action():
    d = _daemon(enabled=True, deixis=True)
    d._gaze_targeter = _FakeTargeter(RouteDecision(None, False, False))
    event: dict = {}
    assert d._try_deixis("close this", event)
    assert event["discard_reason"] == "deixis_no_target"
    assert d._gaze_targeter.actions == []
