"""EYE-HEAD-001 (#404) end to end: a head turn reaches the platform pointer *through the daemon*.

The pieces are proven one at a time elsewhere -- the state machine in
``test_headpointer_controller.py``, the camera lease in ``test_headpointer_runtime.py``, each
daemon builder called on its own in ``test_headpointer_daemon_wiring.py``. What none of them
proves is the composition the issue asks for: that the daemon's **real** ``_build_pipeline()``,
from nothing but ``[headpointer] enabled = true``, builds the shared camera source, hands it and
the platform's ``pointer_factory`` to the Head-Pointer, and that ``_start_headpointer()`` then
turns ``HeadPoseSignal -> pose_to_cursor -> PointerSink.move_relative`` into a working loop.

That gap matters because the registry's "wired" flag is decided by an *import* closure
(``tests/test_feature_wiring_honesty.py``), and the daemon imports ``yazses.headpointer`` in four
statements, two of them outside the builder: ``_build_handsfree_safety`` imports the
controller's ``SOURCE_NAME`` and the face-switch commit path imports ``ClickResult``. Replace the
``self._headpointer = self._build_headpointer(cfg)`` line in ``_build_pipeline`` with ``None``
and the closure still says "reachable" -- the feature would be advertised as wired and never
move anything -- while ten of the tests below fail (checked by hand when this file was written).
So "wired" is pinned here to a behaviour: the flag is true *and* enabling the feature is what
makes the daemon move a pointer.

Only three seams are replaced, and each is named where it is: the camera and the face model (a
counter and a scripted yaw, behind a real ``SharedPerceptionSource``), the platform pointer (a
``FakePointerSink`` returned by the platform's own ``pointer_factory`` slot) and time (the runner
is built by the real ``build_headpointer`` with every argument the daemon passes, plus a list-index
clock and no thread, so the loop is stepped by hand instead of raced). Nothing opens a camera, a
display or a socket.

The last test holds the other half of "no camera logic duplicated inside headpointer": the
existing guard bans OpenCV and MediaPipe by name, which a module could satisfy while importing
the project's own camera, source or landmark-derivation code. Here the package may consume the
perception *data contract* (``perception/signals.py``) and nothing that owns or reads a camera.
"""
from __future__ import annotations

import ast
import dataclasses
import types
from collections.abc import Iterator
from pathlib import Path

import pytest

import yazses.headpointer as headpointer_pkg
from tests.pointer_fake import FakePointerSink, PointerActionKind
from yazses.config import Config
from yazses.core.daemon import Daemon
from yazses.ipc.protocol import Request
from yazses.perception import HeadPoseSignal, PerceptionSample, SharedPerceptionSource, SourceState
from yazses.platform import get_platform
from yazses.system.features import feature_status, unwired_slugs

PACKAGE = Path(headpointer_pkg.__file__).resolve().parent
FRAME_S = 1 / 30


# --------------------------------------------------------------------------- #
# Fakes: a camera, a face model and a clock -- the only things that are not real
# --------------------------------------------------------------------------- #
class _Clock:
    def __init__(self) -> None:
        self.now = 5000.0

    def __call__(self) -> float:
        return self.now


class _Camera:
    def __init__(self) -> None:
        self.opens = 0
        self.closes = 0
        self.broken = False

    def open(self) -> None:
        self.opens += 1

    def read(self) -> object | None:
        if self.broken:
            raise OSError("the webcam was unplugged")
        return object()

    def close(self) -> None:
        self.closes += 1


class _FaceModel:
    """Turns every frame into a head pose whose yaw the test scripts; ``face=False`` hides it."""

    name = "fake-face"

    def __init__(self) -> None:
        self.yaw = 0.0
        self.face = True

    def process(self, frame: object, timestamp_s: float) -> PerceptionSample | None:
        if not self.face:
            return None
        return PerceptionSample(
            timestamp_s, head_pose=HeadPoseSignal(timestamp_s, self.yaw, 0.0, 0.0, 1.0)
        )

    def close(self) -> None:
        pass


class _NoThread:
    """The source's capture loop never runs by itself: the test calls ``observe()``."""

    def join(self, timeout: float | None = None) -> None:
        pass

    def is_alive(self) -> bool:
        return False


@dataclasses.dataclass
class Rig:
    """A daemon after the real ``_build_pipeline()``, and handles on what it was given."""

    daemon: Daemon
    clock: _Clock
    camera: _Camera
    model: _FaceModel
    sink: FakePointerSink
    #: Every ``pointer_factory()`` call the daemon made.
    sinks_built: list[FakePointerSink]
    #: Every ``build_headpointer`` call, with the keyword arguments the daemon passed.
    builder_calls: list[dict[str, object]]
    source: SharedPerceptionSource | None = None

    def frame(self, yaw: float | None = None) -> None:
        """The camera delivers one frame and the Head-Pointer loop polls it once."""
        self.clock.now += FRAME_S
        if yaw is not None:
            self.model.yaw = yaw
        assert self.source is not None
        self.source.observe()
        runtime = self.daemon._headpointer
        assert runtime is not None and runtime.runner is not None
        runtime.runner.pump()

    def hold(self, yaw: float, seconds: float) -> None:
        for _ in range(round(seconds / FRAME_S)):
            self.frame(yaw)

    def command(self, action: str, **params: object) -> dict[str, object]:
        return self.daemon._handle_headpointer(
            Request("headpointer", {"action": action, **params})
        )

    @property
    def moves(self) -> list[object]:
        return [a for a in self.sink.actions if a.kind is PointerActionKind.MOVE_RELATIVE]

    @property
    def clicks(self) -> int:
        return sum(a.kind is PointerActionKind.BUTTON_PRESS for a in self.sink.actions)


@pytest.fixture
def build(monkeypatch: pytest.MonkeyPatch) -> Iterator:
    """Build a daemon through the real ``_build_pipeline()``, with the three seams replaced.

    ``dwell_feedback`` overrides the one argument the daemon derives from the desktop (whether
    the overlay that draws the dwell ring will be on screen), because a headless test runner
    has no overlay and dwell-click is -- rightly -- held off without one. The dwell tests need
    dwell to be *live*, or "it never clicked" would be true for the wrong reason.
    """
    import yazses.core.daemon as daemon_mod
    import yazses.headpointer.runtime as runtime_mod
    import yazses.inject.auto as inject_auto
    import yazses.perception as perception_pkg

    # Not this file's subject, and each would reach for a model, the env or an OS listener.
    monkeypatch.setattr(daemon_mod, "build_engine", lambda stt: types.SimpleNamespace(name="stub"))
    monkeypatch.setattr(inject_auto, "apply_injection_config", lambda injection: None)

    made: list[Daemon] = []

    def make(cfg: Config, *, dwell_feedback: bool | None = None) -> Rig:
        clock, camera, model = _Clock(), _Camera(), _FaceModel()
        sinks: list[FakePointerSink] = []
        calls: list[dict[str, object]] = []
        rig_box: list[Rig] = []

        def fake_source(section, *, capture_factory, processor_factory):
            # The daemon decides *whether* there is a source (it implies one for the
            # Head-Pointer); only the camera and the model behind it are fakes.
            if not getattr(section, "enabled", False):
                return None
            source = SharedPerceptionSource(
                lambda: camera, lambda: model, clock=clock,
                spawn=lambda body, name: _NoThread(),
            )
            rig_box[0].source = source
            return source

        real_builder = runtime_mod.build_headpointer

        def spy_builder(section, **kwargs):
            calls.append(dict(kwargs))
            if dwell_feedback is not None:
                kwargs["dwell_feedback_available"] = dwell_feedback
            return real_builder(section, clock=clock, thread=False, **kwargs)

        def pointer_factory() -> FakePointerSink:
            sink = FakePointerSink()
            sinks.append(sink)
            return sink

        monkeypatch.setattr(perception_pkg, "build_perception_source", fake_source)
        monkeypatch.setattr(runtime_mod, "build_headpointer", spy_builder)
        platform = dataclasses.replace(
            get_platform(),
            injector_factory=lambda: types.SimpleNamespace(name="stub"),
            hotkey_factory=lambda *args: types.SimpleNamespace(run=lambda: None, stop=lambda: None),
            pointer_factory=pointer_factory,
        )
        monkeypatch.setattr(platform.lifecycle, "clear_pid", lambda: None)
        daemon = Daemon(config=cfg, platform=platform)
        monkeypatch.setattr(daemon, "_announce_model_download", lambda cfg: None)
        rig = Rig(daemon, clock, camera, model, FakePointerSink(), sinks, calls)
        rig_box.append(rig)
        made.append(daemon)
        daemon._build_pipeline()
        if sinks:
            rig.sink = sinks[0]
        return rig

    yield make
    for daemon in made:
        daemon._shutdown()


def _enabled(**headpointer: object) -> Config:
    cfg = Config()
    cfg.headpointer.enabled = True
    for key, value in headpointer.items():
        setattr(cfg.headpointer, key, value)
    return cfg


# --------------------------------------------------------------------------- #
# "Wired" is a behaviour, not an import
# --------------------------------------------------------------------------- #
def test_the_wired_flag_is_true_and_the_shipped_daemon_still_builds_nothing(build) -> None:
    feature = next(f for f in feature_status(Config()) if f.slug == "headpointer")
    assert feature.wired and "headpointer" not in unwired_slugs()

    rig = build(Config())  # the shipped config: [headpointer] is off

    runtime = rig.daemon._headpointer
    assert runtime is not None and runtime.runner is None and runtime.reason == ""
    assert rig.sinks_built == [] and rig.builder_calls == []  # no pointer session was asked for
    assert rig.source is None  # and no camera owner either
    assert rig.command("status") == {"ok": True, "active": False, "reason": ""}


def test_enabling_the_feature_is_what_makes_the_daemon_build_a_runner(build) -> None:
    rig = build(_enabled())

    runtime = rig.daemon._headpointer
    assert runtime is not None and runtime.runner is not None, runtime and runtime.reason
    # The daemon's own objects, not ones a test handed it: the shared source it built and
    # the global gate it built (None while [handsfree_safety] is off).
    (call,) = rig.builder_calls
    assert call["perception"] is rig.daemon._perception is rig.source
    assert call["safety"] is rig.daemon._handsfree_safety is None
    assert call["pointer_factory"] is rig.daemon._platform.pointer_factory
    assert len(rig.sinks_built) == 1  # opened once, at build, so a bad backend is known now
    # Building leases nothing: the camera is untouched until the daemon starts the pointer.
    assert rig.camera.opens == 0
    assert rig.source is not None and rig.source.status().state is SourceState.DORMANT


# --------------------------------------------------------------------------- #
# The loop the issue asks for, through the daemon
# --------------------------------------------------------------------------- #
def test_a_head_turn_reaches_the_platform_pointer_through_the_daemon(build) -> None:
    rig = build(_enabled())
    rig.daemon._start_headpointer()
    assert rig.camera.opens == 1
    assert rig.source is not None and rig.source.status().consumers == ("headpointer",)

    rig.frame(0.0)  # the first valid pose becomes the neutral pose: observed, never acted on
    assert rig.moves == []
    rig.hold(0.05, 0.2)  # turn to the user's left and hold it

    assert rig.moves, "a held head turn never reached the platform pointer"
    # The shipped x gain is negative (a real webcam mirrors the user), so +yaw goes left.
    assert all(move.x < 0 and move.y == 0 for move in rig.moves)
    assert rig.clicks == 0  # dwell ships off: motion alone never clicks
    status = rig.command("status")
    assert status["ok"] and status["active"] and status["state"] == "tracking"
    assert status["backend"] == rig.sink.capabilities().backend


def test_returning_to_neutral_stops_the_pointer(build) -> None:
    rig = build(_enabled())
    rig.daemon._start_headpointer()
    rig.frame(0.0)
    rig.hold(0.05, 0.2)
    moved = len(rig.moves)
    rig.hold(0.0, 1.0)  # back to the neutral pose: inside the deadzone
    assert len(rig.moves) == moved


@pytest.mark.parametrize("loss", ["face", "camera"])
def test_losing_the_signal_through_the_daemon_produces_zero_motion(build, loss) -> None:
    """The face leaving the frame, or the webcam failing outright, freezes the pointer."""
    rig = build(_enabled())
    rig.daemon._start_headpointer()
    rig.frame(0.0)
    rig.hold(0.05, 0.2)
    moved = len(rig.moves)
    assert moved, "the precondition: the pointer was following the head"

    if loss == "face":
        rig.model.face = False
    else:
        rig.camera.broken = True
    rig.hold(0.08, 2.0)  # the head keeps turning, but nothing fresh arrives

    assert len(rig.moves) == moved
    assert rig.command("status")["state"] == "lost"
    if loss == "camera":
        assert rig.source is not None and rig.source.status().state is SourceState.FAILED
    # Dictation does not depend on the webcam: the pipeline the daemon built is untouched.
    assert rig.daemon._engine is not None and rig.daemon._injector is not None


def test_a_paused_pointer_does_not_move_when_asked_through_the_daemon(build) -> None:
    rig = build(_enabled())
    rig.daemon._start_headpointer()
    rig.frame(0.0)
    assert rig.command("pause")["ok"] is True
    rig.hold(0.05, 1.0)
    assert rig.moves == []
    assert rig.command("status")["paused"] is True


# --------------------------------------------------------------------------- #
# No click on startup or when the face comes back -- with dwell-click live
# --------------------------------------------------------------------------- #
def aim(rig: Rig) -> None:
    """Turn far enough, for long enough, to leave the 15 px dwell radius, then stop.

    0.15 rad held 0.3 s is ~40 px with the shipped gains; a smaller turn (0.05 rad for 0.2 s
    is ~12 px) never leaves the radius, and a dwell that never re-arms cannot click.
    """
    rig.hold(0.15, 0.3)
    assert sum(abs(move.x) for move in rig.moves) > 15


def test_no_click_on_startup_or_reacquisition_while_dwell_is_live(build) -> None:
    rig = build(_enabled(dwell_enabled=True), dwell_feedback=True)
    status = rig.command("status")
    assert status["dwell_enabled"] is True, status  # dwell really is on in this daemon
    rig.daemon._start_headpointer()

    rig.hold(0.0, 3.0)  # start up and sit perfectly still for four dwell times
    assert rig.clicks == 0, "startup clicked"

    rig.model.face = False
    rig.hold(0.0, 1.0)  # the face leaves...
    rig.model.face = True
    rig.hold(0.0, 3.0)  # ...and comes back to the same still pose
    assert rig.clicks == 0, "re-acquiring the face clicked"

    # The positive control: the same daemon does click once the user *aims* and rests, so
    # the zero above is the gate working and not a dwell that could never fire.
    aim(rig)
    rig.hold(0.0, 3.0)
    assert rig.clicks == 1


def test_a_daemon_without_the_overlay_holds_dwell_click_off(build) -> None:
    """The daemon's own answer to "could the user see a dwell coming?" reaches the runtime."""
    rig = build(_enabled(dwell_enabled=True), dwell_feedback=False)
    rig.daemon._start_headpointer()
    status = rig.command("status")
    assert status["dwell_enabled"] is False and "overlay" in str(status["notice"])
    rig.hold(0.0, 0.1)
    aim(rig)
    rig.hold(0.0, 3.0)
    assert rig.clicks == 0
    assert rig.command("dwell", enabled=True)["ok"] is False  # and it cannot be forced on


# --------------------------------------------------------------------------- #
# Teardown, behaviourally
# --------------------------------------------------------------------------- #
def test_daemon_shutdown_closes_the_pointer_and_then_the_camera(build) -> None:
    rig = build(_enabled())
    rig.daemon._start_headpointer()
    rig.frame(0.0)
    rig.hold(0.05, 0.2)

    rig.daemon._shutdown()

    assert rig.sink.closed
    assert rig.camera.closes == 1
    assert rig.source is not None and rig.source.status().state is SourceState.DORMANT
    moved = len(rig.moves)
    runtime = rig.daemon._headpointer
    assert runtime is not None and runtime.runner is not None
    runtime.runner.pump()  # a straggling poll after shutdown acts on nothing
    assert len(rig.moves) == moved


# --------------------------------------------------------------------------- #
# No camera logic inside headpointer: it consumes signals, it never makes them
# --------------------------------------------------------------------------- #
#: Packages that own a camera path of their own (the shared source and its backends, the
#: gaze targeter, the face switch, the permission probe). The Head-Pointer leases the
#: shared source it is *given*; naming any of these would be a second camera path.
_CAMERA_OWNERS = ("yazses.gaze", "yazses.facegesture", "yazses.cameraperm")
#: The only part of ``yazses.perception`` the Head-Pointer may name: the data contract.
_PERCEPTION_CONTRACT = "yazses.perception.signals"


def _imported_names(path: Path) -> tuple[set[str], set[str]]:
    """Absolute module names *path* imports (relative ones resolved), and dynamic-import calls."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    dynamic: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = ["yazses", "headpointer"][: max(0, 3 - node.level)]
                module = ".".join([*base, *(node.module.split(".") if node.module else [])])
            else:
                module = node.module or ""
            if module == "yazses.perception":
                # `from yazses.perception import X` is recorded as `yazses.perception.X`, so
                # importing the contract submodule this way passes and a camera export fails.
                names.update(f"{module}.{alias.name}" for alias in node.names)
            else:
                names.add(module)
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "__import__":
                dynamic.add("__import__")
            elif isinstance(func, ast.Attribute) and func.attr == "import_module":
                dynamic.add("import_module")
    return names, dynamic


def test_headpointer_reads_the_perception_contract_and_no_camera_code() -> None:
    modules = sorted(PACKAGE.glob("*.py"))
    assert {p.name for p in modules} >= {"controller.py", "pointer.py", "runtime.py"}
    contract_seen = False
    for path in modules:
        names, dynamic = _imported_names(path)
        assert not dynamic, f"{path.name} imports dynamically ({dynamic}); name the module"
        perception = {
            n for n in names if n == "yazses.perception" or n.startswith("yazses.perception.")
        }
        contract_seen |= _PERCEPTION_CONTRACT in perception
        stray = perception - {_PERCEPTION_CONTRACT}
        assert not stray, f"{path.name} imports perception internals {stray}, not the contract"
        owners = {
            n for n in names for owner in _CAMERA_OWNERS if n == owner or n.startswith(owner + ".")
        }
        assert not owners, f"{path.name} imports a camera-owning package {owners}"
    # A parser that saw nothing would pass every assertion above; this one must see the
    # contract the runtime and controller really import.
    assert contract_seen, "no module imported the perception contract -- is the parser blind?"


def test_the_import_guard_catches_what_it_is_for(tmp_path: Path) -> None:
    """Red first: each shape the guard exists to refuse is seen by the parser it uses."""
    cases = {
        "from yazses.perception.camera import OpenCVFrameCapture": "yazses.perception.camera",
        "from yazses.perception import SharedPerceptionSource": (
            "yazses.perception.SharedPerceptionSource"
        ),
        "import yazses.perception": "yazses.perception",
        "import yazses.perception.derive": "yazses.perception.derive",
        "from ..perception import source": "yazses.perception.source",
        "from yazses.gaze.targeter import GazeTargeter": "yazses.gaze.targeter",
    }
    for line, expected in cases.items():
        probe = tmp_path / "probe.py"
        probe.write_text(line + "\n", encoding="utf-8")
        names, _ = _imported_names(probe)
        assert expected in names, (line, names)
    probe.write_text("import importlib\nimportlib.import_module('cv2')\n", encoding="utf-8")
    assert _imported_names(probe)[1] == {"import_module"}
