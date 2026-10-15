"""The camera, in the states a real machine puts it in -- not the ones a fake answers.

EYE-PERM-001 (#414). The earlier contract tests prove the *decision* (`evaluate`) and the
*mapping* of each OS answer. What they cannot see is the shape of the failures that reach
the capture layer, because a fake `cv2.VideoCapture` that answers instantly makes every
one of them look the same:

* **permission refused**, **device busy**, **device unplugged** and **a macOS prompt still
  waiting for an answer** all arrive as one thing from OpenCV -- `isOpened()` is false --
  and the user was told "it may be in use by another application, or the OS may not have
  granted camera permission". A sentence that names both causes names neither.
* **a camera that dies after it opened** (cable pulled, another program took it) arrives
  as `(False, None)` from `read()` *for ever*. The source treats a failed read as an
  ordinary dropped frame, so it sat RUNNING and silent: no error, no log, no sample.
* **permission that changes while the process runs** (the user flips the switch in
  Settings, or answers a prompt) must be seen by the next question. An answer cached from
  the first call keeps reporting a refusal after the grant.

Every test drives a fake that models the *sequence*, with an injected clock so nothing
sleeps. No camera, no OS dialog, no network.
"""

from __future__ import annotations

import sys
import types

import pytest

from yazses.cameraperm import (
    CameraPermission,
    explain_open_failure,
    profile_for,
    resolve,
)
from yazses.config import Config
from yazses.perception.camera import STALL_TIMEOUT_S, OpenCVFrameCapture
from yazses.perception.source import SharedPerceptionSource, SourceState

SOURCE = profile_for("source")
MAC_APP = profile_for("macos-app")
HAVE_ALL = (lambda name: True)


# --------------------------------------------------------------------------- #
# A cv2 whose camera has a life: opens, streams, then misbehaves
# --------------------------------------------------------------------------- #
class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class _Camera:
    """One `cv2.VideoCapture`. `script` is consumed per read: a frame, False (no frame),
    or an exception class to raise -- and the last entry repeats, as a dead camera does."""

    def __init__(self, opens: bool, script: list, clock: _Clock, tick: float) -> None:
        self._opens = opens
        self._script = list(script)
        self._clock = clock
        self._tick = tick
        self.released = 0
        self.still_open = opens

    def isOpened(self) -> bool:  # noqa: N802 - cv2's name
        return self.still_open

    def read(self):
        self._clock.now += self._tick  # a blocking V4L2 read takes real time
        item = self._script[0] if len(self._script) == 1 else self._script.pop(0)
        if isinstance(item, type) and issubclass(item, BaseException):
            raise item("device error")
        return (item is not False, b"frame" if item is not False else None)

    def release(self) -> None:
        self.released += 1


@pytest.fixture
def cv2_world(monkeypatch):
    clock = _Clock()
    world = types.SimpleNamespace(clock=clock, cameras=[], opens=True, script=[True], tick=0.1)

    def video_capture(index):
        cam = _Camera(world.opens, world.script, clock, world.tick)
        world.cameras.append(cam)
        return cam

    monkeypatch.setitem(sys.modules, "cv2", types.SimpleNamespace(VideoCapture=video_capture))
    return world


def _capture(world, explain=lambda: "", **kw) -> OpenCVFrameCapture:
    return OpenCVFrameCapture(0, explain=explain, clock=world.clock, **kw)


# --------------------------------------------------------------------------- #
# 1. A camera that dies after it opened is reported, not silently starved
# --------------------------------------------------------------------------- #
def test_a_camera_that_stops_delivering_frames_raises_after_the_stall_window(cv2_world) -> None:
    cv2_world.script = [True, True, False]  # streams, then never another frame
    cap = _capture(cv2_world)
    cap.open()
    assert cap.read() is not None
    assert cap.read() is not None
    # Dropped frames inside the window are ordinary and stay ordinary.
    for _ in range(int(STALL_TIMEOUT_S / 0.1) - 5):
        assert cap.read() is None
    with pytest.raises(OSError, match=r"delivered no frame for 5s"):
        for _ in range(200):
            cap.read()


def test_one_good_frame_restarts_the_stall_window(cv2_world) -> None:
    """A flaky USB hub that drops for 4 s, delivers, drops 4 s more is not a dead camera --
    the window is 'since the last good frame', not 'since the first bad one'."""
    cv2_world.tick = 1.0
    cv2_world.script = ([False] * 4 + [True]) * 3 + [True]
    cap = _capture(cv2_world)
    cap.open()
    for _ in range(15):
        cap.read()  # never raises: no gap exceeds 4 s


def test_a_camera_that_never_delivers_a_first_frame_is_reported_too(cv2_world) -> None:
    """The Linux busy case: V4L2 lets a second process open the node, so `isOpened()` is
    true and every read fails. Nothing streamed, ever -- and the window runs from open."""
    cv2_world.script = [False]
    cap = _capture(cv2_world)
    cap.open()
    with pytest.raises(OSError, match="delivered no frame"):
        for _ in range(200):
            cap.read()


def test_an_unplugged_handle_is_reported_at_once_not_after_the_window(cv2_world) -> None:
    cv2_world.script = [True, False]
    cap = _capture(cv2_world)
    cap.open()
    assert cap.read() is not None
    cv2_world.cameras[0].still_open = False  # cv2 reports the handle closed
    with pytest.raises(OSError, match="disconnected"):
        cap.read()
    assert cv2_world.clock.now - 1000.0 < STALL_TIMEOUT_S


def test_a_read_that_raises_still_propagates(cv2_world) -> None:
    cv2_world.script = [True, RuntimeError]
    cap = _capture(cv2_world)
    cap.open()
    cap.read()
    with pytest.raises(RuntimeError):
        cap.read()


def test_a_close_and_reopen_gets_a_fresh_window(cv2_world) -> None:
    """The window must not survive a close: a camera reopened after a long pause would
    otherwise be declared stalled on its first dropped frame."""
    cv2_world.script = [False]
    cap = _capture(cv2_world)
    cap.open()
    cv2_world.clock.now += 3600
    cap.close()
    cap.open()
    assert cap.read() is None  # an ordinary dropped frame, not a stall


def test_a_dead_camera_fails_the_shared_source_with_a_reason_and_leaves_it_failed(
    cv2_world,
) -> None:
    """End to end through the real source: it must end FAILED with the camera's own
    explanation as the reason, and every lease must read nothing -- not RUNNING and silent."""
    cv2_world.script = [True, False]

    class _Processor:
        name = "fake"

        def process(self, frame, ts):
            return None  # frames arrive, no face: what matters here is the camera dying

        def close(self) -> None:
            return None

    class _Idle:
        def join(self, timeout=None) -> None:
            return None

        def is_alive(self) -> bool:
            return False

    source = SharedPerceptionSource(
        capture_factory=lambda: _capture(
            cv2_world, explain=lambda: "no camera device is visible to this machine"
        ),
        processor_factory=_Processor,
        spawn=lambda body, name: _Idle(),
        clock=cv2_world.clock,
    )
    lease = source.consumer("gaze")
    lease.start()
    try:
        assert source.status().state is SourceState.RUNNING
        for _ in range(100):
            source.observe()
            if source.status().state is SourceState.FAILED:
                break
        status = source.status()
        assert status.state is SourceState.FAILED
        assert "no camera device is visible" in status.failure_reason
        assert lease.latest() is None
    finally:
        source.close()
    assert cv2_world.cameras[0].released == 1, "the dead camera's handle was not released"


# --------------------------------------------------------------------------- #
# 2. A failed open says WHICH failure, because the OS probe can tell them apart
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("state", "must_contain", "must_not_contain"),
    [
        (CameraPermission.DENIED, "refused camera access", "in use"),
        (CameraPermission.UNAVAILABLE, "no camera device", "refused"),
        (CameraPermission.NOT_DETERMINED, "not granted yet", "in use"),
        (CameraPermission.GRANTED, "another application probably holds", "refused"),
        (CameraPermission.UNSUPPORTED_PLATFORM, "no camera-permission backend", "refused"),
    ],
)
def test_the_four_open_failures_read_differently(state, must_contain, must_not_contain) -> None:
    text = explain_open_failure(
        probe=lambda: state, remedy=lambda: "", profile=SOURCE, find_module=HAVE_ALL
    )
    assert must_contain in text
    assert must_not_contain not in text


def test_a_denied_reason_tells_the_user_to_restart_because_the_source_latches() -> None:
    """The shared source never retries a failed open under live leases, so 'grant it' alone
    would send the user to Settings and back to a feature that stays dead."""
    text = explain_open_failure(
        probe=lambda: CameraPermission.DENIED, remedy=lambda: "", profile=SOURCE,
        find_module=HAVE_ALL,
    )
    assert "restart YazSes" in text


def test_a_frozen_bundle_is_told_its_install_is_the_problem_without_asking_the_os() -> None:
    asked = []
    text = explain_open_failure(
        probe=lambda: asked.append(1) or CameraPermission.DENIED,
        remedy=lambda: "",
        profile=MAC_APP,
        find_module=HAVE_ALL,
    )
    assert "ships no camera runtime" in text
    assert asked == [], "asked the OS about a camera this package can never use"


def test_a_missing_runtime_is_named_not_blamed_on_permission() -> None:
    text = explain_open_failure(
        probe=lambda: CameraPermission.DENIED, remedy=lambda: "", profile=SOURCE,
        find_module=lambda name: name != "mediapipe",
    )
    assert "mediapipe is not installed" in text


@pytest.mark.parametrize("boom", [RuntimeError("tcc"), OSError("registry"), KeyError("x")])
def test_a_probe_that_raises_never_replaces_the_failure_it_explains(boom) -> None:
    def explode() -> CameraPermission:
        raise boom

    text = explain_open_failure(
        probe=explode, remedy=lambda: "", profile=SOURCE, find_module=HAVE_ALL
    )
    # Not granted-looking, and not an exception: an unreadable probe is "unknown".
    assert "not granted yet" in text


def test_every_reason_fits_the_sources_truncation_budget() -> None:
    """The source cuts a failure reason at 200 chars after the exception-type prefix. A
    reason whose useful half sits past the cut is the generic sentence again."""
    prefix = len("OSError: camera 12 could not be opened — ")
    for state in CameraPermission:
        text = explain_open_failure(
            probe=lambda s=state: s, remedy=lambda: "", profile=SOURCE, find_module=HAVE_ALL
        )
        assert text and prefix + len(text) <= 200, (state, len(text))
    for profile in (MAC_APP, profile_for("snap"), profile_for("windows-msix")):
        text = explain_open_failure(probe=lambda: CameraPermission.GRANTED, profile=profile,
                                    remedy=lambda: "", find_module=HAVE_ALL)
        assert prefix + len(text) <= 200, (profile.key, len(text))


# --------------------------------------------------------------------------- #
# 3. The capture asks AFTER it fails, so it can never stand between the user and a prompt
# --------------------------------------------------------------------------- #
def test_the_probe_runs_only_after_the_open_failed(cv2_world) -> None:
    order: list[str] = []
    cv2_world.opens = True
    cap = _capture(cv2_world, explain=lambda: order.append("explain") or "x")
    order.append("before-open")
    cap.open()
    order.append("after-open")
    assert order == ["before-open", "after-open"], "a successful open consulted the OS probe"


def test_a_pending_prompt_then_a_grant_opens_on_the_next_attempt(cv2_world) -> None:
    """macOS: the first open returns a closed handle while the dialog is up. The user
    clicks Allow. A *new* attempt must succeed -- nothing latched in the capture, and the
    probe is asked again rather than remembered."""
    answers = iter([CameraPermission.NOT_DETERMINED, CameraPermission.GRANTED])
    cv2_world.opens = False
    cap = _capture(
        cv2_world,
        explain=lambda: explain_open_failure(
            probe=lambda: next(answers), remedy=lambda: "", profile=SOURCE,
            find_module=HAVE_ALL,
        ),
    )
    with pytest.raises(OSError, match="not granted yet"):
        cap.open()
    assert cv2_world.cameras[0].released == 1, "the refused handle was not handed back"
    cv2_world.opens = True  # the user answered the dialog
    cap.open()
    assert cap.read() is not None


def test_a_missing_opencv_is_an_actionable_oserror_not_a_modulenotfound(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "cv2", None)  # `import cv2` raises ImportError
    cap = OpenCVFrameCapture(0, explain=lambda: "")
    with pytest.raises(OSError, match="opencv"):
        cap.open()


def test_an_explainer_that_raises_falls_back_to_the_generic_sentence(cv2_world) -> None:
    cv2_world.opens = False

    def explode() -> str:
        raise RuntimeError("probe blew up")

    with pytest.raises(OSError, match="may be in use by another application"):
        _capture(cv2_world, explain=explode).open()


# --------------------------------------------------------------------------- #
# 4. Permission that changes while the process runs is seen by the next question
# --------------------------------------------------------------------------- #
def test_resolve_does_not_remember_a_refusal_after_the_grant() -> None:
    """The stale-TCC shape. A `doctor` or panel refresh in a long-lived process asks again;
    if the first DENIED were cached, granting in Settings would never turn the row green."""
    cfg = Config()
    cfg.gaze.enabled = True
    answers = iter([CameraPermission.DENIED, CameraPermission.GRANTED])
    kwargs = dict(
        probe=lambda: next(answers), remedy=lambda: "", profile=SOURCE,
        find_module=HAVE_ALL, model_present=lambda: True,
    )
    assert resolve(cfg, **kwargs).allowed is False
    assert resolve(cfg, **kwargs).allowed is True


def test_resolve_does_not_remember_a_grant_after_the_revocation() -> None:
    """The dangerous direction: a cached GRANTED keeps a revoked camera 'allowed'."""
    cfg = Config()
    cfg.gaze.enabled = True
    answers = iter([CameraPermission.GRANTED, CameraPermission.DENIED])
    kwargs = dict(
        probe=lambda: next(answers), remedy=lambda: "", profile=SOURCE,
        find_module=HAVE_ALL, model_present=lambda: True,
    )
    assert resolve(cfg, **kwargs).allowed is True
    gate = resolve(cfg, **kwargs)
    assert gate.allowed is False and gate.permission is CameraPermission.DENIED


def test_a_disabled_install_never_reaches_the_probe_however_many_times_it_is_asked() -> None:
    """Criterion 1 with a probe that would fail the test if it were ever called."""
    def forbidden() -> CameraPermission:
        raise AssertionError("the OS was asked about a camera nobody enabled")

    cfg = Config()
    for _ in range(3):
        gate = resolve(cfg, probe=forbidden, remedy=lambda: "", profile=SOURCE,
                       find_module=HAVE_ALL)
        assert gate.allowed is False
        assert gate.permission is None
