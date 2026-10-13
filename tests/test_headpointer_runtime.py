"""Head-Pointer wiring: who builds it, what it leases, and what it does when it cannot run.

The state machine is in ``tests/test_headpointer_controller.py``; this file is about the shell
around it (``headpointer/runtime.py``) and the claims that make the feature *honest* rather
than merely present:

* **Dormant means dormant.** Off (the shipped state), or enabled with no shared camera, or with
  no pointer backend: no pointer sink is built, no camera is leased, no thread is started, and
  the reason is kept so ``yazses headpointer status`` can say why the pointer is not moving.
* **One camera owner.** The runner takes a lease on the shared source and never opens a
  device itself -- counted with a real ``SharedPerceptionSource`` over a fake camera, not read
  off the code. Nothing under ``headpointer/`` may import OpenCV or MediaPipe or call
  ``cv2.VideoCapture`` or branch on ``sys.platform``.
* **A crash in the loop is not the daemon's crash.**

Everything runs on numbers: the camera, the model and the pointer are fakes, the loop is driven
by ``pump()`` rather than a thread (one test excepted, because "stop joins the thread" is a
claim about a thread), and time is a list index.
"""
from __future__ import annotations

import ast
import threading
from pathlib import Path

import pytest

import yazses.headpointer as headpointer_pkg
from tests.pointer_fake import FakePointerSink, PointerActionKind
from yazses.config import Config
from yazses.headpointer.controller import HeadPointerSettings, State
from yazses.headpointer.runtime import (
    HeadPointerRunner,
    HeadPointerRuntime,
    build_headpointer,
    settings_from_config,
)
from yazses.perception import HeadPoseSignal, PerceptionSample, SharedPerceptionSource
from yazses.pointer.base import PointerCapabilities, PointerUnsupportedError

PACKAGE = Path(headpointer_pkg.__file__).resolve().parent


# --------------------------------------------------------------------------- #
# Fakes: a camera and a model made of counters, a clock made of a float
# --------------------------------------------------------------------------- #
class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def tick(self, dt: float = 1 / 30) -> None:
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
    """Turns each frame into a head-pose sample whose yaw the test scripts."""

    name = "fake"

    def __init__(self) -> None:
        self.yaw = 0.0
        self.emit = True

    def process(self, frame: object, timestamp_s: float) -> PerceptionSample | None:
        if not self.emit:
            return None
        pose = HeadPoseSignal(timestamp_s, self.yaw, 0.0, 0.0, 1.0)
        return PerceptionSample(timestamp_s, head_pose=pose)

    def close(self) -> None:
        pass


class NoThread:
    """A spawn that never runs the loop: the test calls ``observe()`` itself."""

    def __init__(self, target, name: str) -> None:
        self.target = target

    def join(self, timeout: float | None = None) -> None:
        pass

    def is_alive(self) -> bool:
        return False


class Rig:
    """A real shared source over a fake camera, with the Head-Pointer leasing it."""

    def __init__(self, section=None, *, sink: FakePointerSink | None = None) -> None:
        self.clock = Clock()
        self.camera = Camera()
        self.model = Model()
        self.source = SharedPerceptionSource(
            lambda: self.camera, lambda: self.model, clock=self.clock, spawn=NoThread
        )
        self.sink = sink or FakePointerSink()
        cfg = Config().headpointer
        cfg.enabled = True
        if section:
            for key, value in section.items():
                setattr(cfg, key, value)
        self.runtime = build_headpointer(
            cfg, perception=self.source, pointer_factory=lambda: self.sink, clock=self.clock,
            thread=False, dwell_feedback_available=True,
        )
        assert self.runtime.runner is not None, self.runtime.reason
        self.runner = self.runtime.runner

    def frame(self, yaw: float | None = None) -> None:
        """The camera delivers one frame; the runner polls it."""
        self.clock.tick()
        if yaw is not None:
            self.model.yaw = yaw
        self.source.observe()
        self.runner.pump()

    @property
    def moves(self):
        return [a for a in self.sink.actions if a.kind is PointerActionKind.MOVE_RELATIVE]


# --------------------------------------------------------------------------- #
# Dormancy: the shipped state does no camera and no pointer work at all
# --------------------------------------------------------------------------- #
def test_the_shipped_default_is_off_and_builds_nothing():
    built: list[int] = []
    runtime = build_headpointer(
        Config().headpointer,
        perception=object(),
        pointer_factory=lambda: built.append(1),  # type: ignore[arg-type,return-value]
    )
    assert runtime.runner is None and not runtime.active
    assert built == []  # no pointer session was asked for


def test_enabled_without_a_shared_camera_says_why_and_opens_nothing():
    built: list[int] = []
    cfg = Config().headpointer
    cfg.enabled = True
    runtime = build_headpointer(
        cfg, perception=None, pointer_factory=lambda: built.append(1)  # type: ignore[arg-type,return-value]
    )
    assert runtime.runner is None
    assert "perception" in runtime.reason
    assert built == []


def test_enabled_on_a_platform_with_no_pointer_backend_says_so():
    cfg = Config().headpointer
    cfg.enabled = True
    runtime = build_headpointer(cfg, perception=object(), pointer_factory=None)
    assert runtime.runner is None and "no pointer backend" in runtime.reason


def test_an_unsupported_session_is_a_reason_not_a_crash_and_not_a_silent_sink():
    cfg = Config().headpointer
    cfg.enabled = True

    def refuse():
        raise PointerUnsupportedError("native Wayland session")

    runtime = build_headpointer(cfg, perception=object(), pointer_factory=refuse)
    assert runtime.runner is None
    assert "Wayland" in runtime.reason


def test_a_backend_that_cannot_move_the_pointer_is_refused_and_closed():
    cfg = Config().headpointer
    cfg.enabled = True
    sink = FakePointerSink(PointerCapabilities(backend="clicks-only"))
    runtime = build_headpointer(cfg, perception=object(), pointer_factory=lambda: sink)
    assert runtime.runner is None and "relatively" in runtime.reason
    assert sink.closed


def test_building_the_runtime_leases_nothing_until_it_is_started():
    rig = Rig()
    assert rig.camera.opens == 0  # constructing is not opening
    assert rig.source.status().consumers == ()


def test_a_dormant_runtime_answers_commands_with_its_reason():
    runtime = HeadPointerRuntime(reason="no shared camera source")
    assert runtime.command("status") == {
        "ok": True, "active": False, "reason": "no shared camera source",
    }
    refused = runtime.command("recenter")
    assert refused["ok"] is False and refused["reason"] == "no shared camera source"
    runtime.start()
    runtime.stop()  # harmless: there is nothing to start or stop


# --------------------------------------------------------------------------- #
# One camera owner
# --------------------------------------------------------------------------- #
def test_the_head_pointer_leases_the_shared_source_and_opens_the_camera_once():
    rig = Rig()
    rig.runtime.start()
    rig.runtime.start()  # idempotent
    assert rig.camera.opens == 1
    assert rig.source.status().consumers == ("headpointer",)
    rig.runtime.stop()
    assert rig.camera.closes == 1  # the last lease out closes the door
    assert rig.sink.closed


def test_a_second_consumer_shares_the_one_open_with_the_head_pointer():
    rig = Rig()
    other = rig.source.consumer("facegesture")
    rig.runtime.start()
    other.start()
    assert rig.camera.opens == 1
    rig.runtime.stop()
    assert rig.camera.closes == 0  # the other consumer still holds it
    other.stop()
    assert rig.camera.closes == 1


def test_nothing_under_headpointer_imports_a_camera_stack_or_branches_on_the_platform():
    banned_imports = {"cv2", "mediapipe", "sounddevice"}
    modules = sorted(PACKAGE.glob("*.py"))
    assert {p.name for p in modules} >= {"controller.py", "pointer.py", "runtime.py"}
    for path in modules:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = {node.module.split(".")[0]}
            else:
                names = set()
            assert not names & banned_imports, f"{path.name} imports {names & banned_imports}"
        text = path.read_text(encoding="utf-8")
        assert "VideoCapture" not in text.replace("`", ""), f"{path.name} opens a camera itself"
        assert "sys.platform" not in text, f"{path.name} branches on the platform"


# --------------------------------------------------------------------------- #
# The loop, end to end
# --------------------------------------------------------------------------- #
def test_head_pose_from_the_shared_source_moves_the_pointer_through_the_sink():
    rig = Rig()
    rig.runtime.start()
    rig.frame(0.0)  # becomes the neutral pose
    assert rig.moves == []
    rig.frame(0.05)
    # +yaw is a turn to the user's left; the default x gain is negative, so the pointer goes left.
    assert len(rig.moves) == 1 and rig.moves[0].x < 0
    rig.runtime.stop()


def test_polling_faster_than_the_camera_does_not_move_the_pointer_twice():
    rig = Rig()
    rig.runtime.start()
    rig.frame(0.0)
    rig.frame(0.05)
    for _ in range(10):
        rig.clock.tick(0.001)
        rig.runner.pump()  # no new frame arrived
    assert len(rig.moves) == 1


def test_a_camera_that_goes_blind_freezes_the_pointer():
    rig = Rig()
    rig.runtime.start()
    rig.frame(0.0)
    rig.frame(0.05)
    rig.model.emit = False  # the face is gone: the source publishes nothing new
    for _ in range(60):
        rig.frame()
    assert len(rig.moves) == 1
    assert rig.runtime.command("status")["state"] == "lost"


def test_stopping_drops_the_sample_so_nothing_acts_on_a_face_seen_before_shutdown():
    rig = Rig()
    rig.runtime.start()
    rig.frame(0.0)
    rig.frame(0.05)
    rig.runtime.stop()
    assert rig.runner.controller.update(None, rig.clock.now).state is State.CLOSED
    assert len(rig.moves) == 1


def test_an_exception_in_the_loop_faults_the_feature_and_is_contained(caplog):
    rig = Rig()
    rig.runtime.start()
    rig.frame(0.0)

    class Broken:
        def latest(self):
            raise RuntimeError("source exploded")

        def start(self) -> None:
            pass

        def stop(self) -> None:
            pass

    rig.runner._lease = Broken()  # type: ignore[assignment]
    rig.runner.pump()
    rig.runner.pump()
    status = rig.runtime.command("status")
    assert status["state"] == "faulted" and "RuntimeError" in str(status["fault"])
    assert sum("Head-Pointer loop failed" in r.message for r in caplog.records) == 1


def test_a_lease_that_cannot_be_taken_faults_instead_of_raising():
    class Refusing:
        def start(self) -> None:
            raise RuntimeError("busy")

        def stop(self) -> None:
            pass

        def latest(self):
            return None

    sink = FakePointerSink()
    from yazses.headpointer.controller import HeadPointerController

    runner = HeadPointerRunner(HeadPointerController(sink), Refusing(), thread=False)
    runner.start()
    assert runner.running is False
    assert runner.controller.status().state is State.FAULTED


def test_the_real_thread_polls_and_stop_joins_it():
    cam, model = Camera(), Model()
    source = SharedPerceptionSource(lambda: cam, lambda: model, interval_s=0.001)
    sink = FakePointerSink()
    cfg = Config().headpointer
    cfg.enabled = True
    runtime = build_headpointer(cfg, perception=source, pointer_factory=lambda: sink, fps=120)
    runtime.start()
    try:
        assert cam.opens == 1
        model.yaw = 0.0
        deadline = threading.Event()
        for _ in range(400):
            if runtime.command("status")["state"] == "tracking":
                break
            deadline.wait(0.005)
        assert runtime.command("status")["state"] == "tracking"
    finally:
        runtime.stop()
        source.close()
    assert not [t for t in threading.enumerate() if t.name in {"headpointer", "perception-source"}]
    assert sink.closed


# --------------------------------------------------------------------------- #
# The command surface (what the CLI, a tray item or a voice command reaches)
# --------------------------------------------------------------------------- #
def test_recenter_pause_resume_clutch_and_dwell_are_reachable_as_commands():
    rig = Rig({"dwell_enabled": True})
    rig.runtime.start()
    rig.frame(0.0)
    cmd = rig.runtime.command
    assert cmd("status")["dwell_enabled"] is True

    assert cmd("pause")["ok"] and cmd("status")["paused"] is True
    rig.frame(0.3)
    assert rig.moves == []  # paused: a vigorous head does nothing
    assert cmd("resume")["ok"] and cmd("status")["paused"] is False

    assert cmd("clutch", {"source": "key", "active": True})["ok"]
    assert cmd("status")["clutched"] is True
    assert cmd("clutch", {"source": "key", "active": False})["ok"]
    assert cmd("status")["clutched"] is False

    assert cmd("dwell", {"enabled": False})["ok"] and cmd("status")["dwell_enabled"] is False

    assert cmd("recenter")["ok"]
    rig.frame(0.3)  # capture frame
    assert cmd("status")["calibrated"] is True
    assert rig.moves == []


def test_an_unknown_command_is_refused_not_ignored():
    rig = Rig()
    result = rig.runtime.command("explode")
    assert result["ok"] is False and "explode" in str(result["reason"])


def test_the_status_command_carries_no_pose_or_position():
    rig = Rig()
    rig.runtime.start()
    rig.frame(0.0)
    rig.frame(0.31337)
    status = rig.runtime.command("status")
    assert not any(k in status for k in ("yaw", "pitch", "roll", "x", "y", "position", "neutral"))
    assert "0.31337" not in repr(status)


# --------------------------------------------------------------------------- #
# [headpointer] -> settings
# --------------------------------------------------------------------------- #
def test_the_defaults_are_the_pure_cores_own_and_dwell_is_off():
    settings = settings_from_config(Config().headpointer)
    import dataclasses

    from yazses.headpointer.pointer import DwellClicker, PointerCalib

    # The pure core's own numbers, except the sign of x: a left turn is positive yaw on a real
    # webcam, so the shipped config negates it (see the geometry test below).
    core = PointerCalib()
    assert settings.calib == dataclasses.replace(core, x_gain=-core.x_gain)
    assert settings.dwell_enabled is False
    clicker = DwellClicker()
    assert settings.dwell_radius_px == clicker.radius
    assert settings.dwell_hold_frames == 20


def test_config_values_reach_the_settings_and_junk_falls_back():
    cfg = Config().headpointer
    cfg.x_gain, cfg.deadzone, cfg.freshness_ms = -300.0, 0.05, 250
    cfg.dwell_enabled, cfg.dwell_hold_frames = True, 7
    settings = settings_from_config(cfg)
    assert (settings.calib.x_gain, settings.calib.deadzone) == (-300.0, 0.05)
    assert settings.freshness_s == 0.25 and settings.dwell_enabled and settings.dwell_hold_frames == 7

    cfg.y_gain = "banana"  # type: ignore[assignment]
    cfg.freshness_ms = float("nan")  # type: ignore[assignment]
    fallback = settings_from_config(cfg)
    assert fallback.calib.y_gain == HeadPointerSettings().calib.y_gain
    assert fallback.freshness_s == HeadPointerSettings().freshness_s


def test_a_backend_without_a_left_button_turns_dwell_off_rather_than_failing():
    cfg = Config().headpointer
    cfg.enabled, cfg.dwell_enabled = True, True
    caps = PointerCapabilities(backend="move-only", relative_motion=True)
    source = SharedPerceptionSource(lambda: Camera(), lambda: Model())
    runtime = build_headpointer(
        cfg, perception=source, pointer_factory=lambda: FakePointerSink(caps),
        dwell_feedback_available=True,
    )
    assert runtime.runner is not None
    assert runtime.runner.controller.status().dwell_enabled is False
    assert "no left button" in runtime.notice
    assert runtime.command("dwell", {"enabled": True})["ok"] is False


def test_dwell_click_is_held_off_when_nothing_could_show_its_progress():
    """A click must never arrive unannounced: no overlay, no dwell -- even if configured."""
    cfg = Config().headpointer
    cfg.enabled, cfg.dwell_enabled = True, True
    source = SharedPerceptionSource(lambda: Camera(), lambda: Model())
    runtime = build_headpointer(cfg, perception=source, pointer_factory=FakePointerSink)
    assert runtime.runner is not None  # motion still works
    status = runtime.command("status")
    assert status["dwell_enabled"] is False
    assert "overlay" in str(status["notice"])


def test_the_hold_off_cannot_be_undone_from_the_command_line():
    cfg = Config().headpointer
    cfg.enabled = True  # dwell not even requested
    source = SharedPerceptionSource(lambda: Camera(), lambda: Model())
    runtime = build_headpointer(cfg, perception=source, pointer_factory=FakePointerSink)
    refused = runtime.command("dwell", {"enabled": True})
    assert refused["ok"] is False and "overlay" in str(refused["reason"])
    assert runtime.command("status")["dwell_enabled"] is False
    assert runtime.command("dwell", {"enabled": False})["ok"] is True  # off is always allowed


def test_a_dwell_feedback_sink_counts_as_a_way_to_show_progress():
    cfg = Config().headpointer
    cfg.enabled, cfg.dwell_enabled = True, True

    class Ring:
        def show(self, progress: float) -> None: ...
        def hide(self) -> None: ...

    source = SharedPerceptionSource(lambda: Camera(), lambda: Model())
    runtime = build_headpointer(
        cfg, perception=source, pointer_factory=FakePointerSink, feedback=Ring()
    )
    assert runtime.command("status")["dwell_enabled"] is True


@pytest.mark.parametrize("key", ["x_gain", "y_gain", "deadzone", "freshness_ms", "min_confidence",
                                 "dwell_enabled", "dwell_radius_px", "dwell_hold_frames"])
def test_every_config_key_is_read_by_the_settings_builder(key):
    """A key nothing reads is a toggle that lies (the registry's own honesty rule)."""
    source = (PACKAGE / "runtime.py").read_text(encoding="utf-8")
    assert f'"{key}"' in source


def test_the_default_config_moves_the_pointer_the_way_the_head_turns():
    """Observed on a real webcam (2026-10-13), through this runtime, with a recording sink.

    A turn to the user's left reads as *positive* yaw and a chin-up as *negative* pitch. With the
    gains the config used to ship (+800 on x) a left turn moved the pointer right: the horizontal
    axis was inverted while the vertical one was correct. The sign is geometry, so it is pinned
    here; the magnitudes are not (they are unmeasured and were far too fast).
    """
    from yazses.config import HeadpointerConfig
    from yazses.headpointer.pointer import pose_to_cursor
    from yazses.headpointer.runtime import settings_from_config

    calib = settings_from_config(HeadpointerConfig()).calib
    dx_left, _ = pose_to_cursor(+0.3, 0.0, calib)   # head to the user's left
    dx_right, _ = pose_to_cursor(-0.3, 0.0, calib)  # head to the user's right
    _, dy_up = pose_to_cursor(0.0, -0.3, calib)     # chin up
    _, dy_down = pose_to_cursor(0.0, +0.3, calib)   # chin down
    assert dx_left < 0 < dx_right   # pointer follows the head: left turn -> pointer left
    assert dy_up < 0 < dy_down      # y grows downward: chin up -> pointer up
