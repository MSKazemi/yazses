"""Gesture Chords wiring: what is leased, what is routed, and what happens when it cannot run.

The pure layers are in ``test_gesture_engine.py`` / ``test_gesture_sensors.py`` /
``test_gesture_headmotion.py``; this file is the shell (``gesture/runtime.py``) and the claims
that make the feature honest rather than merely present:

* **Dormant means dormant.** Off (the shipped state), enabled with *no chord bound* (the
  shipped mapping), or enabled with no shared camera: nothing is leased, no thread starts, and
  the reason is kept for ``yazses gesture status``.
* **One camera owner.** The runner takes a lease on the shared source and never opens a device
  -- counted with a real ``SharedPerceptionSource`` over a fake camera.
* **Chord actions reach only abstract, existing actions**, and a command phrase goes through
  the activation policy: a reversible one runs, anything else is refused (no prompt is wired).
* **The Head-Pointer is frozen for the gesture** through its existing public clutch -- proven
  against the real controller, not a stub.
* **The global hands-free gate suppresses chords end to end.**
"""
from __future__ import annotations

import ast
import math
from pathlib import Path

import yazses.gesture as gesture_pkg
from tests.pointer_fake import FakePointerSink, PointerActionKind
from yazses.commands.grammar import classify
from yazses.config import Config
from yazses.gesture.runtime import (
    CLUTCH_SOURCE,
    GestureRunner,
    GestureRuntime,
    build_gesture,
    command_runner,
    engine_params,
    sensor_settings,
)
from yazses.handsfree.safety import HandsFreeSafety
from yazses.headpointer.runtime import build_headpointer
from yazses.perception import (
    FaceSignal,
    HeadPoseSignal,
    PerceptionSample,
    SharedPerceptionSource,
)

PACKAGE = Path(gesture_pkg.__file__).resolve().parent


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def tick(self, dt: float = 1 / 15) -> None:
        self.now += dt


class Camera:
    def __init__(self) -> None:
        self.opens = 0
        self.closes = 0

    def open(self) -> None:
        self.opens += 1

    def read(self) -> object | None:
        return object()

    def close(self) -> None:
        self.closes += 1


class Model:
    """Turns each frame into the sample the test scripted."""

    name = "fake"

    def __init__(self) -> None:
        self.jaw = 0.0
        self.yaw = 0.0
        self.pitch = 0.0
        self.emit = True

    def process(self, frame: object, timestamp_s: float) -> PerceptionSample | None:
        if not self.emit:
            return None
        return PerceptionSample(
            timestamp_s,
            head_pose=HeadPoseSignal(timestamp_s, self.yaw, self.pitch, 0.0, 1.0),
            face=FaceSignal(timestamp_s, 1.0, {"jawOpen": self.jaw}),
        )

    def close(self) -> None:
        pass


class NoThread:
    def __init__(self, target, name: str) -> None:
        self.target = target

    def join(self, timeout: float | None = None) -> None:
        pass

    def is_alive(self) -> bool:
        return False


def section(chords=None, **overrides):
    cfg = Config().gesture
    cfg.enabled = True
    cfg.chords = dict(chords if chords is not None else {})
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return cfg


class Rig:
    """A real shared source over a fake camera, with Gesture Chords (and optionally the
    Head-Pointer) leasing it."""

    def __init__(self, chords, *, pointer=False, safety=None, run_command=None,
                 gesture_first=True, **overrides):
        self.gesture_first = gesture_first
        self.clock = Clock()
        self.camera = Camera()
        self.model = Model()
        self.source = SharedPerceptionSource(
            lambda: self.camera, lambda: self.model, clock=self.clock, spawn=NoThread
        )
        self.sink = FakePointerSink()
        self.headpointer = None
        if pointer:
            hp = Config().headpointer
            hp.enabled = True
            hp.x_gain, hp.y_gain = 800.0, 600.0
            self.headpointer = build_headpointer(
                hp, perception=self.source, pointer_factory=lambda: self.sink,
                clock=self.clock, thread=False, safety=safety, dwell_feedback_available=True,
            )
            assert self.headpointer.runner is not None, self.headpointer.reason
        self.runtime = build_gesture(
            section(chords, **overrides), facegesture=Config().facegesture,
            perception=self.source, headpointer=self.headpointer, safety=safety,
            run_command=run_command, clock=self.clock, thread=False,
        )
        assert self.runtime.runner is not None, self.runtime.reason
        self.runner = self.runtime.runner

    def start(self) -> None:
        if self.headpointer is not None:
            self.headpointer.start()
        self.runtime.start()

    def frame(self, **scripted) -> None:
        """The camera delivers one frame; both consumers poll it."""
        self.clock.tick()
        for key, value in scripted.items():
            setattr(self.model, key, value)
        self.source.observe()
        if self.gesture_first:
            self.runner.pump()
        if self.headpointer is not None:
            self.headpointer.runner.pump()
        if not self.gesture_first:
            self.runner.pump()

    @property
    def moves(self):
        return [a for a in self.sink.actions if a.kind is PointerActionKind.MOVE_RELATIVE]


# --------------------------------------------------------------------------- #
# Dormancy
# --------------------------------------------------------------------------- #
def test_the_shipped_default_is_off_and_builds_nothing():
    class Boom:
        def consumer(self, name):
            raise AssertionError("a default install must not touch the camera source")

    runtime = build_gesture(Config().gesture, facegesture=Config().facegesture, perception=Boom())
    assert runtime.runner is None and not runtime.active and runtime.reason == ""


def test_enabled_with_no_chord_bound_is_still_inert_and_says_why():
    class Boom:
        def consumer(self, name):
            raise AssertionError("no chord, no lease")

    runtime = build_gesture(section(), facegesture=Config().facegesture, perception=Boom())
    assert runtime.runner is None
    assert "no chords are bound" in runtime.reason


def test_a_mapping_whose_every_entry_is_refused_is_also_inert_and_lists_why():
    runtime = build_gesture(
        section({"jaw_open+wink": "recenter", "nod": "launch"}),
        facegesture=Config().facegesture, perception=object(),
    )
    assert runtime.runner is None and len(runtime.problems) == 2
    status = runtime.command("status")
    assert status["ok"] and status["active"] is False and len(status["problems"]) == 2


def test_enabled_without_a_shared_camera_says_why():
    runtime = build_gesture(
        section({"nod": "recenter"}), facegesture=Config().facegesture, perception=None
    )
    assert runtime.runner is None and "perception" in runtime.reason


def test_an_inert_runtime_refuses_commands_with_its_reason():
    runtime = GestureRuntime(reason="because")
    assert runtime.command("pause") == {"ok": False, "reason": "because"}
    runtime.start()
    runtime.stop()  # no runner: harmless


def test_building_the_runtime_leases_nothing_until_it_is_started():
    rig = Rig({"nod": "recenter"})
    assert rig.camera.opens == 0 and rig.source.status().consumers == ()
    rig.start()
    assert rig.camera.opens == 1 and rig.source.status().consumers == ("gesture",)
    rig.runtime.stop()
    assert rig.camera.closes == 1


def test_it_shares_the_one_camera_with_the_head_pointer():
    rig = Rig({"nod": "recenter"}, pointer=True)
    rig.start()
    assert rig.camera.opens == 1                        # two consumers, one open
    assert set(rig.source.status().consumers) == {"gesture", "headpointer"}
    rig.runtime.stop()
    assert rig.camera.closes == 0                       # the pointer still needs it
    rig.headpointer.stop()
    assert rig.camera.closes == 1


def test_stopping_twice_is_harmless():
    rig = Rig({"nod": "recenter"})
    rig.start()
    rig.runtime.stop()
    rig.runtime.stop()


def test_nothing_under_the_package_opens_a_camera_or_branches_on_the_platform():
    modules = sorted(PACKAGE.glob("*.py"))
    assert len(modules) >= 6          # not vacuous: chords, engine, headmotion, runtime, sensors
    for path in modules:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                assert name.split(".")[0] not in {"cv2", "mediapipe", "sounddevice"}, path.name
        text = path.read_text(encoding="utf-8")
        assert "VideoCapture" not in text and "sys.platform" not in text, path.name


# --------------------------------------------------------------------------- #
# The loop
# --------------------------------------------------------------------------- #
def test_a_chord_made_through_the_real_source_reaches_its_handler():
    called = []
    rig = Rig({"jaw_open": "command:undo"}, run_command=lambda phrase: called.append(phrase))
    rig.start()
    for _ in range(4):
        rig.frame(jaw=0.9)
    assert called == ["undo"]


def test_a_crash_in_the_loop_is_logged_once_and_the_runner_keeps_polling(caplog):
    rig = Rig({"nod": "recenter"})
    rig.start()
    boom = RuntimeError("sensor bug")
    original = rig.runner.sensors.update
    rig.runner.sensors.update = lambda *a, **k: (_ for _ in ()).throw(boom)  # type: ignore[method-assign]
    rig.frame()
    rig.frame()
    assert sum("loop failed" in r.message for r in caplog.records) == 1
    rig.runner.sensors.update = original  # type: ignore[method-assign]
    rig.frame()                                          # and recovers


def test_the_lease_failing_to_start_does_not_raise():
    class Bad:
        def start(self):
            raise OSError("no camera")

        def stop(self):
            pass

        def latest(self):
            return None

    rig = Rig({"nod": "recenter"})
    runner = GestureRunner(rig.runner.engine, rig.runner.sensors, Bad(), thread=False)
    runner.start()
    assert not runner.running


def test_stop_joins_a_real_polling_thread():
    rig = Rig({"nod": "recenter"})
    runner = GestureRunner(
        rig.runner.engine, rig.runner.sensors, rig.source.consumer("t"), thread=True,
        interval_s=0.01,
    )
    runner.start()
    assert runner.running and runner._thread is not None and runner._thread.is_alive()  # noqa: SLF001
    runner.stop()
    assert not runner.running and runner._thread is None  # noqa: SLF001


# --------------------------------------------------------------------------- #
# Actions
# --------------------------------------------------------------------------- #
def test_recenter_reaches_the_head_pointer_through_its_public_command():
    rig = Rig({"nod": "recenter"}, pointer=True)
    rig.start()
    rig.headpointer.command("recenter")  # baseline: the command exists and succeeds
    calls = []
    original = rig.headpointer.command
    rig.headpointer.command = lambda a, p=None: calls.append(a) or original(a, p)  # type: ignore[method-assign]
    rig.runner.engine.pulse("nod", rig.clock())
    assert "recenter" in calls


def test_without_a_head_pointer_recenter_is_unwired_and_inert():
    rig = Rig({"nod": "recenter"})
    assert rig.runner.engine.unwired() == ["recenter"]
    rig.runner.engine.pulse("nod", rig.clock())          # nothing to call; nothing raised


def test_pause_pointer_pauses_the_global_gate_when_there_is_one():
    gate = HandsFreeSafety(["gesture"])
    rig = Rig({"nod": "pause_pointer"}, safety=gate)
    rig.runner.engine.pulse("nod", rig.clock())
    assert gate.status().user_paused


def test_pause_pointer_pauses_the_head_pointer_when_there_is_no_gate():
    rig = Rig({"nod": "pause_pointer"}, pointer=True)
    rig.start()
    rig.runner.engine.pulse("nod", rig.clock())
    assert rig.headpointer.command("status")["paused"] is True


def test_pause_pointer_with_nothing_to_pause_is_unwired():
    rig = Rig({"nod": "pause_pointer"})
    assert rig.runner.engine.unwired() == ["pause_pointer"]


def test_no_action_bound_by_config_can_name_anything_but_the_abstract_set():
    runtime = build_gesture(
        section({"nod": "rm -rf", "tilt": "keystroke:ctrl+w", "jaw_open": "inject:hello"}),
        facegesture=Config().facegesture, perception=object(),
    )
    assert runtime.runner is None and len(runtime.problems) == 3


# --------------------------------------------------------------------------- #
# Spoken-command phrases go through the activation policy
# --------------------------------------------------------------------------- #
class Dispatched:
    def __init__(self) -> None:
        self.log: list[str] = []

    def __call__(self, intent) -> None:
        self.log.append(intent.action)


def _run(phrase, **kw):
    out = Dispatched()
    result = command_runner(lambda t: classify(t, "default"), out, **kw)(phrase)
    return out.log, result


def test_a_reversible_command_runs():
    log, result = _run("undo")
    assert log == ["undo"] and result.executed


def test_an_irreversible_command_is_held_for_confirmation_and_refused_with_no_prompt():
    log, result = _run("save")
    assert log == [] and not result.executed and result.confirmed is False


def test_an_irreversible_command_runs_only_when_a_prompt_says_yes():
    asked = []
    log, result = _run("save", confirm=lambda action, intent: asked.append(action) or True)
    assert asked == ["save"] and log == ["save"] and result.executed
    log, result = _run("save", confirm=lambda action, intent: False)
    assert log == [] and not result.executed


def test_a_phrase_that_is_not_a_command_is_never_typed():
    log, result = _run("hello world")
    assert log == [] and not result.executed


def test_a_chord_is_bound_to_the_phrase_not_to_its_literal_text():
    log = []
    runner = command_runner(lambda t: classify(t, "default"), lambda i: log.append(i.action))
    assert not runner("delete line").executed          # the grammar does not know it: dictation
    assert log == []


# --------------------------------------------------------------------------- #
# The pointer is held still for the gesture (Project Gameface's failure mode)
# --------------------------------------------------------------------------- #
def settle(rig, frames=4):
    for _ in range(frames):
        rig.frame()


def test_the_pointer_follows_the_head_when_no_gesture_is_engaged():
    rig = Rig({"jaw_open+nod": "recenter"}, pointer=True)
    rig.start()
    settle(rig)
    rig.frame(yaw=0.3)
    rig.frame(yaw=0.3)
    assert rig.moves                                    # the control: the pointer does move


def test_an_expression_that_disturbs_the_head_does_not_move_the_pointer():
    rig = Rig({"jaw_open+nod": "recenter"}, pointer=True, gesture_first=True)
    rig.start()
    settle(rig)                                         # neutral head, relaxed face
    rig.sink.clear()
    # The jaw opens and, as it does, the head tips: the failure Project Gameface documented.
    for yaw in (0.05, 0.12, 0.2, 0.3, 0.3, 0.3):
        rig.frame(jaw=0.9, yaw=yaw)
    assert rig.moves == []
    assert CLUTCH_SOURCE in rig.headpointer.runner.controller._clutches  # noqa: SLF001


DISTURBED = (0.05, 0.12, 0.2, 0.3, 0.3, 0.3)


def net(rig):
    return (sum(a.x for a in rig.moves), sum(a.y for a in rig.moves))


def test_a_freeze_that_lands_a_frame_late_takes_the_first_frame_step_back():
    """The two runners poll on their own threads, so the pointer can follow the first disturbed
    frame before the clutch lands. The clutch names that frame and the controller sends the
    opposite step: the pointer ends where it was. (The recording still shows the step and its
    undo -- a twitch of one frame, not a drift.)"""
    rig = Rig({"jaw_open+nod": "recenter"}, pointer=True, gesture_first=False)
    rig.start()
    settle(rig)
    rig.sink.clear()
    for yaw in DISTURBED:
        rig.frame(jaw=0.9, yaw=yaw)
    assert rig.moves, "the control: the pointer did follow that first frame"
    assert net(rig) == (0.0, 0.0)


def test_with_the_rewind_off_the_first_frame_still_leaks():
    """The mutation check for the test above, and the shipped behaviour of 2.42.0."""
    rig = Rig({"jaw_open+nod": "recenter"}, pointer=True, gesture_first=False, onset_rewind_ms=0)
    rig.start()
    settle(rig)
    rig.sink.clear()
    for yaw in DISTURBED:
        rig.frame(jaw=0.9, yaw=yaw)
    assert net(rig) != (0.0, 0.0)


def test_the_rewind_takes_back_the_onset_frame_and_nothing_earlier():
    rig = Rig({"jaw_open+nod": "recenter"}, pointer=True, gesture_first=False)
    rig.start()
    settle(rig)
    rig.sink.clear()
    for _ in range(3):
        rig.frame(yaw=0.3)                              # ordinary head movement, no expression
    before = net(rig)
    assert before != (0.0, 0.0)
    for _ in range(4):
        rig.frame(jaw=0.9, yaw=0.3)
    assert net(rig) == before


def test_when_the_gesture_runner_polls_first_there_is_nothing_to_take_back():
    rig = Rig({"jaw_open+nod": "recenter"}, pointer=True, gesture_first=True)
    rig.start()
    settle(rig)
    rig.sink.clear()
    for yaw in DISTURBED:
        rig.frame(jaw=0.9, yaw=yaw)
    assert rig.moves == []


# --------------------------------------------------------------------------- #
# Rule 9: the early clutch is judged on how rarely it fires
# --------------------------------------------------------------------------- #
def _count_clutches(rig):
    """Count the calls that *hold* the pointer, by spying on the controller's clutch."""
    controller = rig.headpointer.runner.controller
    original = controller.set_clutch
    held = []

    def spy(source, active, **kwargs):
        if active:
            held.append(kwargs)
        return original(source, active, **kwargs)

    controller.set_clutch = spy
    return held


def _ordinary_motion(rig, frames):
    """Head wandering and glancing about, a face that never reaches the release threshold."""
    for n in range(frames):
        t = n / 15.0
        rig.frame(
            yaw=0.25 * math.sin(2 * math.pi * t / 4.1) + 0.1 * math.sin(2 * math.pi * t / 1.3),
            pitch=0.15 * math.sin(2 * math.pi * t / 5.7),
            jaw=0.05 + 0.1 * abs(math.sin(2 * math.pi * t / 0.9)),
        )


def _talking(rig, frames):
    """A jaw that opens past the release threshold for three frames every 22 (about 1.5 s)."""
    for n in range(frames):
        spike = (n % 22) < 3
        rig.frame(jaw=0.6 if spike else 0.05, yaw=0.02 if spike else 0.0)


def _run_sequence(sequence, rewind_ms, frames=900):
    rig = Rig({"jaw_open+nod": "recenter"}, pointer=True, gesture_first=False,
              onset_rewind_ms=rewind_ms)
    rig.start()
    settle(rig)
    held = _count_clutches(rig)
    rig.sink.clear()
    sequence(rig, frames)
    return rig, held


def test_ordinary_head_movement_never_clutches_the_pointer():
    """900 frames (one minute at the rig's 15 fps) of a head wandering and glancing: no clutch
    is held and no motion is taken back, with the rewind on or off. Synthetic -- it says the
    early path has no trigger of its own, not what a person's day looks like. No threshold was
    tuned from it (measured 2026-10-15: 0 clutches per minute, 0 rewinds)."""
    on, held_on = _run_sequence(_ordinary_motion, 150)
    off, held_off = _run_sequence(_ordinary_motion, 0)
    assert held_on == [] and held_off == []
    assert on.sink.actions == off.sink.actions and on.moves


def test_the_rewind_adds_no_clutch_to_speech_like_jaw_movement():
    """The existing hazard, measured and not widened: a jaw opening past the release threshold
    engages the freeze, as it always did. The rewind rides the same trigger, so the number of
    clutches is identical with it on or off (measured 2026-10-15 on 41 synthetic jaw
    movements in one minute: 41 clutches either way. A real talker's rate is unmeasured, which is
    why `jaw_open` is a poor chord token for someone who talks while using the pointer)."""
    _, held_on = _run_sequence(_talking, 150)
    _, held_off = _run_sequence(_talking, 0)
    assert len(held_on) == len(held_off) == 41
    assert all(kwargs.get("since_s") is not None for kwargs in held_on)
    assert all(kwargs.get("since_s") is None for kwargs in held_off)


def test_without_the_freeze_the_same_disturbance_does_move_the_pointer():
    """The mutation check for the test above: with no clutch the disturbed pose is followed."""
    rig = Rig({"jaw_open+nod": "recenter"}, pointer=True, gesture_first=True)
    rig.start()
    settle(rig)
    rig.sink.clear()
    rig.runner.engine._on_freeze = None  # noqa: SLF001 - sever the clutch
    for yaw in (0.05, 0.12, 0.2, 0.3, 0.3, 0.3):
        rig.frame(jaw=0.9, yaw=yaw)
    assert len(rig.moves) >= 3


def test_the_pointer_is_free_again_after_the_gesture_and_its_tail():
    rig = Rig({"jaw_open+nod": "recenter"}, pointer=True)
    rig.start()
    settle(rig)
    for _ in range(5):
        rig.frame(jaw=0.9)
    for _ in range(12):                                 # relax: tail (0.3 s) elapses
        rig.frame(jaw=0.0, yaw=0.0)
    assert CLUTCH_SOURCE not in rig.headpointer.runner.controller._clutches  # noqa: SLF001
    rig.sink.clear()
    for _ in range(3):
        rig.frame(yaw=0.3)
    assert rig.moves                                    # moving again


def test_losing_the_camera_releases_the_clutch():
    rig = Rig({"jaw_open+nod": "recenter"}, pointer=True)
    rig.start()
    settle(rig)
    for _ in range(5):
        rig.frame(jaw=0.9)
    assert CLUTCH_SOURCE in rig.headpointer.runner.controller._clutches  # noqa: SLF001
    rig.model.emit = False                               # the face is gone
    rig.clock.tick(2.0)
    rig.runner.pump()
    assert CLUTCH_SOURCE not in rig.headpointer.runner.controller._clutches  # noqa: SLF001


def test_without_a_head_pointer_the_freeze_has_nowhere_to_go_and_nothing_breaks():
    rig = Rig({"jaw_open": "command:undo"}, run_command=lambda p: None)
    rig.start()
    for _ in range(5):
        rig.frame(jaw=0.9)


# --------------------------------------------------------------------------- #
# The global hands-free gate, end to end
# --------------------------------------------------------------------------- #
def armed(sources=("gesture",)):
    gate = HandsFreeSafety(list(sources))
    return gate


def test_chords_are_suppressed_until_the_source_is_explicitly_armed():
    gate = armed()
    called = []
    rig = Rig({"jaw_open": "command:undo"}, safety=gate, run_command=called.append)
    rig.start()
    for _ in range(5):
        rig.frame(jaw=0.9)
    assert called == []                                  # signal is fresh, but nobody re-armed
    assert rig.runtime.command("resume")["ok"]
    for _ in range(12):
        rig.frame(jaw=0.0)
    for _ in range(5):
        rig.frame(jaw=0.9)
    assert called == ["undo"]


def test_a_global_pause_suppresses_a_chord_that_was_working():
    gate = armed()
    called = []
    rig = Rig({"jaw_open": "command:undo"}, safety=gate, run_command=called.append)
    rig.start()
    rig.frame()
    assert rig.runtime.command("resume")["ok"]
    gate.pause("test")
    for _ in range(5):
        rig.frame(jaw=0.9)
    assert called == []


def test_resume_reports_why_a_source_will_not_arm():
    gate = armed()
    rig = Rig({"jaw_open": "command:undo"}, safety=gate, run_command=lambda p: None)
    result = rig.runtime.command("resume")              # no sample has ever arrived
    assert result["ok"] is False and result["reason"]


# --------------------------------------------------------------------------- #
# The command surface
# --------------------------------------------------------------------------- #
def test_status_carries_names_and_flags_never_a_measurement():
    rig = Rig({"jaw_open+nod": "recenter"}, pointer=True)
    rig.start()
    status = rig.runtime.command("status")
    assert status["ok"] and status["active"] and status["chords"] == 1
    assert set(status["watching"]) == {"jaw_open", "nod"}
    assert set(status) == {
        "ok", "active", "running", "chords", "watching", "paused", "pointer_frozen",
        "unwired", "problems",
    }


def test_pause_and_resume_toggle_the_engine():
    rig = Rig({"nod": "recenter"}, pointer=True)
    assert rig.runtime.command("pause") == {"ok": True}
    assert rig.runtime.command("status")["paused"] is True
    assert rig.runtime.command("resume")["ok"]
    assert rig.runtime.command("status")["paused"] is False


def test_an_unknown_command_is_refused():
    rig = Rig({"nod": "recenter"})
    assert rig.runtime.command("launch")["ok"] is False


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
def test_the_shipped_config_binds_nothing():
    cfg = Config().gesture
    assert cfg.enabled is False and cfg.chords == {}


def test_settings_are_read_from_the_config_in_the_units_the_detectors_use():
    cfg = Config().gesture
    cfg.head_amplitude_deg = 20.0
    cfg.head_swings = 6
    cfg.tilt_deg = 30.0
    cfg.freshness_ms = 250
    s = sensor_settings(cfg, Config().facegesture)
    assert math.isclose(s.head.amplitude_rad, math.radians(20.0))
    assert math.isclose(s.head.tilt_rad, math.radians(30.0))
    assert s.head.swings == 6 and math.isclose(s.freshness_s, 0.25)
    assert engine_params(cfg) == (0.4, 1.0, 0.3)


def test_the_face_tokens_use_the_face_switchs_calibrated_thresholds():
    face = Config().facegesture
    face.hold_threshold, face.release_threshold = 0.7, 0.2
    s = sensor_settings(Config().gesture, face)
    assert (s.face.hold_threshold, s.face.release_threshold) == (0.7, 0.2)


# --------------------------------------------------------------------------- #
# A failing command must not type its own name
# --------------------------------------------------------------------------- #
class _RecordingInjector:
    def __init__(self) -> None:
        self.typed: list[str] = []
        self.keys: list[list[str]] = []

    def inject(self, text: str) -> None:
        self.typed.append(text)

    def inject_key_sequence(self, keys: list[str]) -> None:
        self.keys.append(list(keys))


def test_the_chord_injector_will_not_type_the_phrase_but_passes_everything_else():
    from yazses.gesture.runtime import no_echo_injector

    inner = _RecordingInjector()
    wrapped = no_echo_injector(inner, "undo")
    wrapped.inject("undo")                 # the fallback in commands.dispatch on a failure
    wrapped.inject("12")                   # an argument a command legitimately types
    wrapped.inject_key_sequence(["ctrl+z"])
    assert inner.typed == ["12"] and inner.keys == [["ctrl+z"]]


def test_a_command_that_raises_does_not_end_up_typed_into_the_focused_window():
    from yazses.commands.dispatch import dispatch
    from yazses.gesture.runtime import no_echo_injector

    class Exploding(_RecordingInjector):
        def inject_key_sequence(self, keys):
            raise OSError("no display")

    inner = Exploding()
    intent = classify("undo", "default")
    dispatch(intent, no_echo_injector(inner, intent.raw_text))
    assert inner.typed == []               # without the wrapper this would be ["undo"]
    dispatch(intent, inner)
    assert inner.typed == ["undo"]         # the control: the plain path does type it


# --------------------------------------------------------------------------- #
# The "hold" token, end to end on the injected clock
# --------------------------------------------------------------------------- #
def test_hold_is_a_duration_of_the_clock_not_a_count_of_frames():
    called = []
    rig = Rig({"jaw_open+hold": "command:undo"}, run_command=called.append)
    rig.start()
    for _ in range(10):                  # 10 frames at 15 fps = 0.67 s: shorter than hold_ms
        rig.frame(jaw=0.9)
    assert called == []
    for _ in range(8):                   # past 0.8 s of the held token
        rig.frame(jaw=0.9)
    assert called == ["undo"]
    for _ in range(40):                  # however long it stays held, once
        rig.frame(jaw=0.9)
    assert called == ["undo"]


def test_a_jaw_that_lets_go_before_hold_ms_does_nothing():
    called = []
    rig = Rig({"jaw_open+hold": "command:undo"}, run_command=called.append)
    rig.start()
    for _ in range(8):
        rig.frame(jaw=0.9)
    for _ in range(30):
        rig.frame(jaw=0.0)
    assert called == []


def test_hold_ms_is_the_configured_duration():
    called = []
    rig = Rig({"jaw_open+hold": "command:undo"}, run_command=called.append, hold_ms=2000)
    rig.start()
    for _ in range(20):                  # 1.33 s: past the 0.8 s default, short of 2 s
        rig.frame(jaw=0.9)
    assert called == []
    for _ in range(14):
        rig.frame(jaw=0.9)
    assert called == ["undo"]
