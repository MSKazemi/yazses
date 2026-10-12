"""Face-switch intents and their mapping to actions (#407, EYE-FACE-002).

ADR-v2-147: the face detector emits abstract switch intents and never executes a desktop
action. These pin that boundary from both sides --

* `facegesture/switches.py`, the pure mapping layer, driven with recording handlers;
* `facegesture/backend.py`, which must emit intents and nothing else;
* the daemon seam, where an existing single-gesture `[facegesture]` install must come out
  unchanged.

Every trace is a hand-written numeric fixture, so none of this is evidence that a threshold or
a mapping is right for a real face.
"""
from __future__ import annotations

import ast
import logging
from dataclasses import fields, replace
from pathlib import Path
from types import SimpleNamespace

import pytest

import yazses.facegesture as _facegesture_pkg
from yazses.config import Config, FacegestureConfig
from yazses.core.daemon import Daemon
from yazses.facegesture.backend import FaceGestureBackend
from yazses.facegesture.switches import (
    ACTIONS,
    COMMIT_ACTIONS,
    HOLD_ACTIONS,
    PRESS,
    RELEASE,
    SAFE_ACTIONS,
    SwitchAction,
    SwitchIntent,
    SwitchMapper,
    legacy_action,
    make_intent,
    parse_bindings,
)
from yazses.handsfree.safety import HandsFreeSafety
from yazses.platform import get_platform

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


class _Calls:
    """Handlers that record what was asked of them."""

    def __init__(self):
        self.log: list[str] = []

    def hold(self, name):
        return SwitchAction(
            press=lambda: self.log.append(f"{name}:press"),
            release=lambda: self.log.append(f"{name}:release"),
        )

    def pulse(self, name):
        return SwitchAction(press=lambda: self.log.append(f"{name}:press"))


def _intent(gesture, phase, conf=0.9):
    return SwitchIntent(gesture=gesture, phase=phase, timestamp_s=1.0, confidence=conf)


def _mapper(bindings, calls, gate=None, on_freeze=None, **extra):
    handlers = {
        "hold_to_talk": calls.hold("talk"),
        "hold_to_command": calls.hold("command"),
        "select": calls.pulse("select"),
        "confirm": calls.pulse("confirm"),
        "cancel": calls.pulse("cancel"),
        "pause_pointer": calls.pulse("pause"),
    }
    handlers.update(extra)
    return SwitchMapper(bindings, handlers, gate=gate, on_freeze=on_freeze)


class _Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def _armed_gate():
    clock = _Clock()
    gate = HandsFreeSafety(("facegesture",), clock=clock)
    gate.sample("facegesture")
    assert gate.resume().ok
    return gate, clock


# ---------------------------------------------------------------------------
# parse_bindings: the mapping is validated data
# ---------------------------------------------------------------------------


def test_no_switches_is_exactly_the_single_gesture_install():
    assert parse_bindings([], "jaw_open", "full_text") == ({"jaw_open": "hold_to_talk"}, [])
    assert parse_bindings(None, "smile", "command") == ({"smile": "hold_to_command"}, [])


@pytest.mark.parametrize("mode", ["command", " Command ", "COMMAND"])
def test_the_legacy_command_mode_maps_to_the_command_hold(mode):
    assert legacy_action(mode) == "hold_to_command"


@pytest.mark.parametrize("mode", ["full_text", "", None, "comand", 3])
def test_any_other_legacy_mode_dictates_as_the_daemon_does(mode):
    assert legacy_action(mode) == "hold_to_talk"


def test_switches_add_to_the_legacy_binding_and_hold_to_talk_is_one_mapping_among_several():
    got, problems = parse_bindings(
        [{"gesture": "brow_raise", "intent": "confirm"}, {"gesture": "smile", "intent": "select"}],
        "jaw_open", "full_text",
    )
    assert problems == []
    assert got == {"jaw_open": "hold_to_talk", "brow_raise": "confirm", "smile": "select"}


def test_a_switch_for_the_primary_gesture_replaces_the_legacy_binding():
    got, _ = parse_bindings([{"gesture": "jaw_open", "intent": "cancel"}], "jaw_open")
    assert got == {"jaw_open": "cancel"}


def test_none_unmaps_a_gesture_explicitly():
    got, problems = parse_bindings([{"gesture": "jaw_open", "intent": "none"}], "jaw_open")
    assert got == {} and problems == []


def test_names_are_case_insensitive():
    got, problems = parse_bindings([{"gesture": "Brow_Raise", "intent": "CONFIRM"}], "jaw_open")
    assert problems == [] and got["brow_raise"] == "confirm"


@pytest.mark.parametrize(
    "entry",
    [
        {"gesture": "wink", "intent": "confirm"},         # unknown gesture
        {"gesture": "brow_raise", "intent": "launch"},   # unknown action
        {"gesture": "brow_raise"},                        # no action
        {"intent": "confirm"},                            # no gesture
        {},
        "brow_raise",
        None,
        7,
    ],
)
def test_an_entry_that_cannot_be_honoured_is_skipped_with_a_reason_never_coerced(entry):
    got, problems = parse_bindings([entry], "jaw_open")
    assert got == {"jaw_open": "hold_to_talk"}, "the legacy binding must survive a bad entry"
    assert len(problems) == 1


def test_a_typo_does_not_bind_the_gesture_to_a_neighbouring_action():
    got, problems = parse_bindings([{"gesture": "smile", "intent": "selct"}], "jaw_open")
    assert "smile" not in got and problems


def test_a_duplicate_gesture_keeps_the_first_mapping():
    got, problems = parse_bindings(
        [{"gesture": "smile", "intent": "select"}, {"gesture": "smile", "intent": "cancel"}],
        "jaw_open",
    )
    assert got["smile"] == "select" and len(problems) == 1


@pytest.mark.parametrize("raw", ["confirm", {"gesture": "smile"}, 3, True])
def test_switches_that_are_not_a_list_are_ignored_with_a_reason(raw):
    got, problems = parse_bindings(raw, "jaw_open")
    assert got == {"jaw_open": "hold_to_talk"} and len(problems) == 1


def test_the_vocabulary_is_closed_and_consistent():
    assert set(HOLD_ACTIONS) | set(COMMIT_ACTIONS) | set(SAFE_ACTIONS) <= set(ACTIONS)
    assert "none" not in ACTIONS


# ---------------------------------------------------------------------------
# SwitchMapper
# ---------------------------------------------------------------------------


def test_an_unmapped_gesture_reaches_no_action():
    calls = _Calls()
    m = _mapper({"jaw_open": "hold_to_talk"}, calls)
    for gesture in ("brow_raise", "smile", "wink", ""):
        assert m.handle(_intent(gesture, PRESS)) is False
        assert m.handle(_intent(gesture, RELEASE)) is False
    assert calls.log == []


def test_an_unmapped_gesture_does_not_fall_back_to_the_default_action():
    calls = _Calls()
    m = _mapper({}, calls)
    m.handle(_intent("jaw_open", PRESS))
    m.handle(_intent("jaw_open", RELEASE))
    assert calls.log == []


def test_hold_to_talk_presses_and_releases_with_the_gesture():
    calls = _Calls()
    m = _mapper({"jaw_open": "hold_to_talk"}, calls)
    assert m.handle(_intent("jaw_open", PRESS)) is True
    assert m.handle(_intent("jaw_open", RELEASE)) is True
    assert calls.log == ["talk:press", "talk:release"]


def test_a_discrete_action_fires_once_on_press_and_never_on_release():
    calls = _Calls()
    m = _mapper({"brow_raise": "confirm"}, calls)
    m.handle(_intent("brow_raise", PRESS))
    m.handle(_intent("brow_raise", RELEASE))
    assert calls.log == ["confirm:press"]


def test_each_gesture_drives_only_its_own_action():
    calls = _Calls()
    m = _mapper({"jaw_open": "hold_to_talk", "brow_raise": "cancel", "smile": "select"}, calls)
    m.handle(_intent("brow_raise", PRESS))
    m.handle(_intent("brow_raise", RELEASE))
    assert calls.log == ["cancel:press"]


def test_an_action_nothing_implements_does_nothing_and_warns_once(caplog):
    m = SwitchMapper({"smile": "select"}, {})
    assert m.unwired() == ["select"]
    with caplog.at_level(logging.WARNING):
        assert m.handle(_intent("smile", PRESS)) is False
        assert m.handle(_intent("smile", PRESS)) is False
    assert caplog.text.count("nothing implements") == 1


def test_a_handler_that_raises_does_not_propagate_and_does_not_wedge_the_mapper():
    calls = _Calls()

    def boom():
        raise RuntimeError("daemon exploded")

    m = _mapper({"jaw_open": "hold_to_talk"}, calls, hold_to_talk=SwitchAction(boom, boom))
    assert m.handle(_intent("jaw_open", PRESS)) is False
    assert m.handle(_intent("jaw_open", RELEASE)) is False
    calls2 = _Calls()
    m2 = _mapper({"jaw_open": "hold_to_talk"}, calls2)
    assert m2.handle(_intent("jaw_open", PRESS)) is True


def test_a_release_with_no_recorded_press_still_closes_a_hold():
    """The shutdown drain and the legacy single-gesture tests rely on this."""
    calls = _Calls()
    m = _mapper({"jaw_open": "hold_to_talk"}, calls)
    assert m.handle(_intent("jaw_open", RELEASE)) is True
    assert calls.log == ["talk:release"]


def test_two_gestures_on_one_hold_start_it_once_and_end_it_when_both_let_go():
    calls = _Calls()
    m = _mapper({"jaw_open": "hold_to_talk", "smile": "hold_to_talk"}, calls)
    m.handle(_intent("jaw_open", PRESS))
    m.handle(_intent("smile", PRESS))
    m.handle(_intent("jaw_open", RELEASE))
    assert calls.log == ["talk:press"], "still held by the other gesture"
    m.handle(_intent("smile", RELEASE))
    assert calls.log == ["talk:press", "talk:release"]


def test_a_repeated_press_without_a_release_is_ignored():
    calls = _Calls()
    m = _mapper({"jaw_open": "hold_to_talk"}, calls)
    m.handle(_intent("jaw_open", PRESS))
    assert m.handle(_intent("jaw_open", PRESS)) is False
    assert calls.log == ["talk:press"]


def test_an_unknown_phase_does_nothing():
    calls = _Calls()
    m = _mapper({"jaw_open": "hold_to_talk"}, calls)
    assert m.handle(_intent("jaw_open", "wiggle")) is False
    assert calls.log == []


# -- the global pause/kill gate ------------------------------------------------


def test_a_switch_is_suppressed_until_the_gate_is_armed():
    """A fresh gate suppresses everything (ADR-v2-148): PAUSED until an explicit resume."""
    calls = _Calls()
    gate = HandsFreeSafety(("facegesture",), clock=_Clock())
    gate.sample("facegesture")
    m = _mapper({"brow_raise": "confirm"}, calls, gate=gate)
    assert m.handle(_intent("brow_raise", PRESS)) is False
    assert calls.log == []


def test_an_armed_gate_lets_a_switch_act():
    calls = _Calls()
    gate, _ = _armed_gate()
    m = _mapper({"brow_raise": "confirm"}, calls, gate=gate)
    assert m.handle(_intent("brow_raise", PRESS)) is True
    assert calls.log == ["confirm:press"]


def test_pause_suppresses_every_switch_action():
    calls = _Calls()
    gate, _ = _armed_gate()
    m = _mapper({"jaw_open": "hold_to_talk", "brow_raise": "confirm", "smile": "select"}, calls, gate=gate)
    gate.pause("user")
    for g in ("jaw_open", "brow_raise", "smile"):
        assert m.handle(_intent(g, PRESS)) is False
    assert calls.log == []
    assert m.freeze_pointer is False, "a suppressed commit gesture must not freeze the pointer"


def test_a_stale_face_signal_suppresses_the_switch():
    calls = _Calls()
    gate, clock = _armed_gate()
    m = _mapper({"brow_raise": "confirm"}, calls, gate=gate)
    clock.now = 10_000.0  # far past the staleness window with no new sample
    assert m.handle(_intent("brow_raise", PRESS)) is False
    assert calls.log == []


def test_a_fault_suppresses_the_switch_until_an_explicit_rearm():
    calls = _Calls()
    gate, _ = _armed_gate()
    m = _mapper({"brow_raise": "confirm"}, calls, gate=gate)
    gate.fault("facegesture", "model closed")
    gate.clear_fault("facegesture")
    assert m.handle(_intent("brow_raise", PRESS)) is False
    gate.sample("facegesture")
    assert gate.resume().ok
    assert m.handle(_intent("brow_raise", PRESS)) is True


def test_a_release_is_never_gated():
    """Refusing to close the microphone is the failure the gate exists to prevent."""
    calls = _Calls()
    gate, _ = _armed_gate()
    m = _mapper({"jaw_open": "hold_to_talk"}, calls, gate=gate)
    m.handle(_intent("jaw_open", PRESS))
    gate.pause("user")
    assert m.handle(_intent("jaw_open", RELEASE)) is True
    assert calls.log == ["talk:press", "talk:release"]


def test_pausing_closes_an_open_hold_at_once_without_waiting_for_the_face_to_relax():
    calls = _Calls()
    gate, _ = _armed_gate()
    m = _mapper({"jaw_open": "hold_to_talk"}, calls, gate=gate)
    m.handle(_intent("jaw_open", PRESS))
    m.frame(has_signal=True)
    assert calls.log == ["talk:press"], "still allowed: nothing happens on a healthy frame"
    gate.pause("user")
    m.frame(has_signal=True)
    assert calls.log == ["talk:press", "talk:release"]
    m.frame(has_signal=True)
    assert calls.log == ["talk:press", "talk:release"], "released once, not every frame"


def test_the_pause_action_is_the_one_thing_that_runs_under_a_closed_gate():
    calls = _Calls()
    gate, _ = _armed_gate()
    gate.pause("user")
    m = _mapper({"smile": "pause_pointer", "brow_raise": "confirm"}, calls, gate=gate)
    assert m.handle(_intent("smile", PRESS)) is True
    assert m.handle(_intent("brow_raise", PRESS)) is False
    assert calls.log == ["pause:press"]


def test_frames_with_a_face_feed_the_gates_freshness_and_frames_without_one_do_not():
    gate, clock = _armed_gate()
    m = _mapper({"brow_raise": "confirm"}, _Calls(), gate=gate)
    clock.now = 400.0
    m.frame(has_signal=True)
    clock.now = 800.0  # 400 ms since the last sample: still inside the 500 ms window
    assert gate.status().source("facegesture").stale is False
    clock.now = 1500.0
    m.frame(has_signal=False)  # a blind camera must age the source out, not refresh it
    assert gate.status().source("facegesture").stale is True


# -- pointer freeze --------------------------------------------------------------


def test_a_held_commit_gesture_requests_a_pointer_freeze_for_its_interval():
    seen: list[bool] = []
    m = _mapper({"brow_raise": "select"}, _Calls(), on_freeze=seen.append)
    assert m.freeze_pointer is False
    m.handle(_intent("brow_raise", PRESS))
    assert m.freeze_pointer is True
    m.handle(_intent("brow_raise", RELEASE))
    assert m.freeze_pointer is False
    assert seen == [True, False]


@pytest.mark.parametrize("action", ["hold_to_talk", "hold_to_command", "cancel", "pause_pointer"])
def test_only_commit_actions_freeze_the_pointer(action):
    m = _mapper({"smile": action}, _Calls())
    m.handle(_intent("smile", PRESS))
    assert m.freeze_pointer is False


def test_release_all_ends_a_freeze_and_every_hold():
    calls = _Calls()
    m = _mapper({"jaw_open": "hold_to_talk", "brow_raise": "confirm", "smile": "select"}, calls)
    for g in ("jaw_open", "smile"):
        m.handle(_intent(g, PRESS))
    assert m.freeze_pointer is True
    m.release_all()
    assert m.freeze_pointer is False
    assert calls.log[-1] == "talk:release"
    m.release_all()  # idempotent
    assert calls.log.count("talk:release") == 1


def test_a_freeze_callback_that_raises_does_not_break_the_mapper():
    def boom(_):
        raise RuntimeError("pointer gone")

    m = _mapper({"brow_raise": "select"}, _Calls(), on_freeze=boom)
    assert m.handle(_intent("brow_raise", PRESS)) is True


# -- the intent value ------------------------------------------------------------


def test_an_intent_carries_no_frame_score_or_mesh():
    assert {f.name for f in fields(SwitchIntent)} == {
        "gesture", "phase", "timestamp_s", "confidence", "source",
    }


def test_make_intent_maps_the_detectors_events_and_refuses_anything_else():
    assert make_intent("jaw_open", "start", 0.7, now_s=2.0) == SwitchIntent(
        "jaw_open", PRESS, 2.0, 0.7, "facegesture"
    )
    assert make_intent("jaw_open", "end", None, now_s=3.0).phase == RELEASE
    with pytest.raises(ValueError):
        make_intent("jaw_open", "held")


@pytest.mark.parametrize("raw,expected", [(float("nan"), None), (5.0, 1.0), (-1.0, 0.0), (0.4, 0.4)])
def test_make_intent_keeps_confidence_a_real_unit_number(raw, expected):
    assert make_intent("smile", "start", raw, now_s=0.0).confidence == expected


# ---------------------------------------------------------------------------
# layering: the detector side never reaches the desktop
# ---------------------------------------------------------------------------

_FORBIDDEN = (
    "yazses.core", "yazses.inject", "yazses.commands", "yazses.pointer",
    "yazses.headpointer", "yazses.windowctl", "yazses.mousegrid", "yazses.gesture",
)


def _imports(path: Path) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
    return out


def test_no_facegesture_module_imports_the_daemon_or_a_desktop_action():
    pkg = Path(_facegesture_pkg.__file__).parent
    modules = sorted(pkg.glob("*.py"))
    assert {p.name for p in modules} >= {"backend.py", "detector.py", "calibration.py", "switches.py"}
    for path in modules:
        bad = [m for m in _imports(path) if m.startswith(_FORBIDDEN)]
        assert not bad, f"{path.name} reaches into {bad}; a face switch emits intents only"


# ---------------------------------------------------------------------------
# the backend emits intents only
# ---------------------------------------------------------------------------


class _Cat:
    def __init__(self, name, score):
        self.category_name, self.score = name, score


class _Cv2:
    COLOR_BGR2RGB = 0

    def cvtColor(self, frame, code):
        return frame


class _Mp:
    ImageFormat = type("F", (), {"SRGB": 0})

    def Image(self, image_format, data):
        return data


def _run_loop(backend, frames):
    """Drive the real capture loop; ``frames`` is a list of ``{category: score}`` dicts."""
    queue = list(frames)
    current: list[dict] = [queue[0]]

    class _Landmarker:
        def detect(self, image):
            return type("R", (), {
                "face_blendshapes": [[_Cat(n, s) for n, s in current[0].items()]]
            })

    class _Cap:
        def read(self):
            current[0] = queue.pop(0)
            if not queue:
                backend.stop()
            return True, object()

    backend._loop(_Landmarker(), _Cap(), _Cv2(), _Mp())


_JAW = [{"jawOpen": v} for v in [0.0, 0.9, 0.9, 0.9, 0.9, 0.1, 0.1, 0.1]]


def test_the_backend_hands_intents_to_its_sink_and_calls_no_callback():
    got: list[SwitchIntent] = []
    started: list[int] = []
    backend = FaceGestureBackend(
        replace(FacegestureConfig(), fps=60),
        lambda n: started.append(n), lambda: started.append(-1),
        on_intent=got.append,
    )
    _run_loop(backend, _JAW)
    assert [(i.gesture, i.phase) for i in got] == [("jaw_open", PRESS), ("jaw_open", RELEASE)]
    assert started == [], "with a sink supplied the backend must not touch the hold callbacks"
    assert all(i.confidence == 0.5 and i.source == "facegesture" for i in got)


def test_the_default_sink_maps_the_single_gesture_to_the_hold_callbacks():
    """An existing `[facegesture]` install: same gesture, same two callbacks, same events."""
    events: list[str] = []
    backend = FaceGestureBackend(
        replace(FacegestureConfig(), fps=60),
        lambda n: events.append("start"), lambda: events.append("end"),
    )
    assert backend._mapper.bindings == {"jaw_open": "hold_to_talk"}
    _run_loop(backend, _JAW)
    assert events == ["start", "end"]


def test_a_second_gesture_drives_its_own_action_and_not_the_hold():
    calls = _Calls()
    cfg = replace(
        FacegestureConfig(), fps=60,
        switches=[{"gesture": "brow_raise", "intent": "confirm"}],
    )
    backend = FaceGestureBackend(
        cfg, lambda n: calls.log.append("talk:press"), lambda: calls.log.append("talk:release"),
        actions={"confirm": calls.pulse("confirm")},
    )
    frames = [{"jawOpen": 0.0, "browInnerUp": v} for v in [0, 0.9, 0.9, 0.9, 0.9, 0.0, 0.0, 0.0]]
    _run_loop(backend, frames)
    assert calls.log == ["confirm:press"]


def test_both_gestures_can_fire_in_one_session_independently():
    calls = _Calls()
    cfg = replace(
        FacegestureConfig(), fps=60,
        switches=[{"gesture": "brow_raise", "intent": "confirm"}],
    )
    backend = FaceGestureBackend(
        cfg, lambda n: calls.log.append("talk:press"), lambda: calls.log.append("talk:release"),
        actions={"confirm": calls.pulse("confirm")},
    )
    quiet = {"jawOpen": 0.0, "browInnerUp": 0.0}
    jaw = {"jawOpen": 0.9, "browInnerUp": 0.0}
    brow = {"jawOpen": 0.0, "browInnerUp": 0.9}
    _run_loop(backend, [quiet] + [jaw] * 4 + [quiet] * 3 + [brow] * 4 + [quiet] * 3)
    assert calls.log == ["talk:press", "talk:release", "confirm:press"]


def test_an_unmapped_gesture_reaches_no_daemon_action_end_to_end():
    """The P5.2 done-when, end to end: movements the user never mapped start nothing.

    Only `jaw_open` is mapped here, so the smile and brow movements are not even watched;
    the mapper-level tests above (and `test_explicitly_unmapping_the_primary_gesture...`
    below, which watches a gesture whose binding is removed) are what prove a *watched but
    unmapped* gesture is dropped rather than defaulted.
    """
    events: list[str] = []
    cfg = replace(FacegestureConfig(), fps=60)  # only jaw_open is mapped
    backend = FaceGestureBackend(cfg, lambda n: events.append("start"), lambda: events.append("end"))
    smile = [{"mouthSmileLeft": v, "mouthSmileRight": v, "jawOpen": 0.0, "browInnerUp": 0.9}
             for v in [0, 0.9, 0.9, 0.9, 0.9, 0.9, 0.0, 0.0]]
    _run_loop(backend, smile)
    assert events == []


def test_explicitly_unmapping_the_primary_gesture_silences_it():
    events: list[str] = []
    cfg = replace(FacegestureConfig(), fps=60, switches=[{"gesture": "jaw_open", "intent": "none"}])
    backend = FaceGestureBackend(cfg, lambda n: events.append("start"), lambda: events.append("end"))
    assert backend._mapper.bindings == {}
    _run_loop(backend, _JAW)
    assert events == []


def test_a_bad_switch_entry_is_reported_once_and_the_legacy_binding_survives(caplog):
    cfg = replace(FacegestureConfig(), switches=[{"gesture": "wink", "intent": "confirm"}])
    with caplog.at_level(logging.WARNING):
        backend = FaceGestureBackend(cfg)
    assert backend._mapper.bindings == {"jaw_open": "hold_to_talk"}
    assert "wink" in caplog.text


def test_a_mapped_action_with_no_handler_is_called_out_at_construction(caplog):
    cfg = replace(FacegestureConfig(), switches=[{"gesture": "smile", "intent": "select"}])
    with caplog.at_level(logging.WARNING):
        backend = FaceGestureBackend(cfg)
    assert backend._mapper.unwired() == ["select"]
    assert "select" in caplog.text


def test_shutdown_mid_gesture_releases_a_hold_on_every_gesture():
    calls = _Calls()
    cfg = replace(
        FacegestureConfig(), fps=60,
        switches=[{"gesture": "smile", "intent": "hold_to_command"}],
    )
    backend = FaceGestureBackend(
        cfg, lambda n: calls.log.append("talk:press"), lambda: calls.log.append("talk:release"),
        actions={"hold_to_command": calls.hold("command")},
    )
    for _ in range(3):
        backend._switches["jaw_open"].update(0.9)
        backend._switches["smile"].update(0.9)
    backend._mapper.handle(_intent("jaw_open", PRESS))
    backend._mapper.handle(_intent("smile", PRESS))
    backend._build_landmarker = lambda: SimpleNamespace(close=lambda: None)
    backend._open_camera = lambda: (SimpleNamespace(release=lambda: None), object())
    backend._loop = lambda *a: None
    backend.run()
    assert "talk:release" in calls.log and "command:release" in calls.log


def test_the_safety_gate_stops_the_running_switch_and_releases_an_open_hold():
    events: list[str] = []
    gate, clock = _armed_gate()
    backend = FaceGestureBackend(
        replace(FacegestureConfig(), fps=60),
        lambda n: events.append("start"), lambda: events.append("end"),
        safety=gate,
    )
    queue = [{"jawOpen": v} for v in [0.0, 0.9, 0.9, 0.9, 0.9, 0.9, 0.9, 0.9]]
    seen = {"n": 0}

    class _Landmarker:
        def detect(self, image):
            return type("R", (), {"face_blendshapes": [[_Cat("jawOpen", queue[seen["n"]]["jawOpen"])]]})

    class _Cap:
        def read(self):
            seen["n"] += 1
            if seen["n"] == 6:
                gate.pause("user")   # the user hits pause mid-hold
            if seen["n"] >= len(queue):
                backend.stop()
            seen["n"] = min(seen["n"], len(queue) - 1)
            return True, object()

    backend._loop(_Landmarker(), _Cap(), _Cv2(), _Mp())
    assert events == ["start", "end"], "pausing must close the mic without waiting for a relax"


# ---------------------------------------------------------------------------
# the daemon seam
# ---------------------------------------------------------------------------


def _daemon(**face):
    cfg = replace(Config(), facegesture=replace(FacegestureConfig(), enabled=True, **face))
    return Daemon(config=cfg, platform=get_platform())


def test_an_existing_install_builds_the_same_single_binding():
    d = _daemon()
    source = d._build_face_gesture_source(d._config)[0]
    assert source._mapper.bindings == {"jaw_open": "hold_to_talk"}
    assert source._on_hold_start == d._on_hold_start


def test_both_hold_actions_are_available_whatever_the_legacy_mode():
    d = _daemon(switches=[{"gesture": "smile", "intent": "hold_to_command"}])
    source = d._build_face_gesture_source(d._config)[0]
    assert source._mapper.unwired() == []
    assert source._mapper.bindings == {"jaw_open": "hold_to_talk", "smile": "hold_to_command"}

    d2 = _daemon(mode="command", switches=[{"gesture": "smile", "intent": "hold_to_talk"}])
    s2 = d2._build_face_gesture_source(d2._config)[0]
    assert s2._mapper.bindings == {"jaw_open": "hold_to_command", "smile": "hold_to_talk"}
    assert s2._mapper.unwired() == []


def test_actions_the_daemon_does_not_implement_yet_stay_unwired_not_invented():
    d = _daemon(switches=[{"gesture": "brow_raise", "intent": "confirm"}])
    source = d._build_face_gesture_source(d._config)[0]
    assert source._mapper.unwired() == ["confirm"]


def test_a_daemon_with_a_safety_gate_gives_the_face_switch_the_pause_action_and_the_gate():
    d = _daemon(switches=[{"gesture": "smile", "intent": "pause_pointer"}])
    gate = HandsFreeSafety(("facegesture",))
    d._handsfree_safety = gate
    source = d._build_face_gesture_source(d._config)[0]
    assert source._mapper.unwired() == []
    assert source._mapper._gate is gate


def test_a_daemon_with_no_safety_gate_leaves_pause_unwired():
    d = _daemon(switches=[{"gesture": "smile", "intent": "pause_pointer"}])
    assert not hasattr(d, "_handsfree_safety") or d._handsfree_safety is None
    source = d._build_face_gesture_source(d._config)[0]
    assert source._mapper.unwired() == ["pause_pointer"]
    assert source._mapper._gate is None


def test_switches_load_from_a_toml_style_table_list():
    from yazses.configcheck import build_section

    problems: list = []
    section = build_section(
        FacegestureConfig,
        {"switches": [{"gesture": "brow_raise", "intent": "confirm"}]},
        "facegesture", problems,
    )
    assert problems == []
    assert section.switches == [{"gesture": "brow_raise", "intent": "confirm"}]
    assert FacegestureConfig().switches == [], "off by default: no extra mapping"
