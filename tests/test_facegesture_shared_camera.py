"""The face switch on the shared camera (ADR-v2-145): one device, one lease, same detectors.

Before this, `facegesture/backend.py` opened its own `cv2.VideoCapture` and FaceLandmarker even
with `[perception]` on, so it contended with Glance-Type gaze and the Head-Pointer ("device
already busy"). These pin the move from every side --

* the *decision* (`shared_source_for_facegesture`, `Daemon._build_face_gesture_source`): lease only
  when a source exists and the camera index matches, otherwise the own-capture path untouched;
* the *lifecycle*: counted on a real `SharedPerceptionSource` over a fake camera -- one open for
  two consumers, the last one out closes it;
* the *behaviour*: the same scores through the shared path and the own-capture path fire the same
  events, a repeated sample counts once, a stale or absent one can only release, and a missing
  blendshape channel costs the face switch and nothing else.

The own-capture path itself is pinned by `tests/test_facegesture_own_capture_path.py`. Every score
below is a synthetic numeric fixture; none is evidence about a real face.
"""
from __future__ import annotations

import logging
from dataclasses import replace

import pytest

from yazses.config import Config, FacegestureConfig, PerceptionConfig
from yazses.core.daemon import Daemon
from yazses.facegesture.backend import FaceGestureBackend
from yazses.facegesture.shared import (
    MAX_SAMPLE_AGE_S,
    NO_BLENDSHAPE_WARN_AFTER,
    shared_source_for_facegesture,
)
from yazses.perception import (
    FaceSignal,
    GazeSignal,
    PerceptionSample,
    SharedPerceptionSource,
    SourceState,
)
from yazses.platform import get_platform


class Clock:
    def __init__(self, now: float = 500.0) -> None:
        self.now = now

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
    """Turns each frame into a sample whose channels the test scripts."""

    name = "fake"

    def __init__(self) -> None:
        self.shapes: dict[str, float] | None = {}
        self.gaze = False

    def process(self, frame: object, timestamp_s: float) -> PerceptionSample | None:
        face = None if self.shapes is None else FaceSignal(timestamp_s, 0.9, self.shapes)
        gaze = GazeSignal(timestamp_s, 0.1, 0.2, 0.9) if self.gaze else None
        if face is None and gaze is None:
            return None
        return PerceptionSample(timestamp_s, gaze=gaze, face=face)

    def close(self) -> None:
        pass


class NoThread:
    def __init__(self, target, name: str) -> None:
        pass

    def join(self, timeout: float | None = None) -> None:
        pass

    def is_alive(self) -> bool:
        return False


class Spy:
    """A lease wrapper that records calls (a real lease has ``__slots__``) and can misbehave."""

    def __init__(self, inner) -> None:
        self.inner = inner
        self.log: list[str] = []
        self.after_start = None
        self.fail_start: Exception | None = None

    @property
    def name(self) -> str:
        return self.inner.name

    def start(self) -> None:
        self.log.append("start")
        if self.fail_start is not None:
            raise self.fail_start
        self.inner.start()
        if self.after_start is not None:
            self.after_start()

    def stop(self) -> None:
        self.log.append("stop")
        self.inner.stop()

    def latest(self):
        return self.inner.latest()


class Rig:
    """A real shared source over a fake camera, with the face switch leasing it."""

    def __init__(self, **face) -> None:
        self.clock = Clock()
        self.camera = Camera()
        self.model = Model()
        self.source = SharedPerceptionSource(
            lambda: self.camera, lambda: self.model, clock=self.clock, spawn=NoThread
        )
        self.events: list[str] = []
        self.cfg = replace(FacegestureConfig(enabled=True), fps=15, **face)
        self.lease = Spy(self.source.consumer("facegesture"))
        self.backend = FaceGestureBackend(
            self.cfg,
            lambda n: self.events.append("start"),
            lambda: self.events.append("end"),
            perception=self.lease,
            clock=self.clock,
            failure_reason=lambda: self.source.status().failure_reason,
        )

    def start(self) -> None:
        self.lease.start()

    def frame(self, jaw: float | None = 0.0) -> None:
        """The camera delivers one frame; the switch polls it.

        ``jaw=None`` is an observation that carries other channels (gaze) but no blendshape
        channel -- the per-channel degradation ADR-v2-145 invariant 6 describes. A frame in
        which the whole face is gone produces no sample at all; see ``stall``.
        """
        self.clock.tick()
        self.model.shapes = None if jaw is None else {"jawOpen": jaw}
        self.model.gaze = jaw is None
        self.source.observe()
        self.backend._shared_step()

    def stall(self, seconds: float) -> None:
        """The camera stops delivering; the switch keeps polling at twice the frame rate."""
        end = self.clock.now + seconds
        while self.clock.now < end:
            self.clock.tick(1 / 30)
            self.backend._shared_step()


# -- the decision ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("face_index", "shared_index", "source", "shares"),
    [
        (0, 0, object(), True),
        (2, 2, object(), True),
        (0, 1, object(), False),     # different cameras: two owners is correct, not a contention
        (1, 0, object(), False),
        (0, 0, None, False),         # [perception] off / no backend wired
    ],
)
def test_the_switch_shares_the_camera_only_when_sharing_is_correct(
    face_index, shared_index, source, shares
):
    choice = shared_source_for_facegesture(
        FacegestureConfig(camera_index=face_index), PerceptionConfig(camera_index=shared_index), source
    )
    assert (choice.source is not None) is shares
    assert choice.reason


def test_the_bounds_are_the_documented_starting_points():
    # Same freshness bound Glance-Type uses, so the two features agree on "too old".
    from yazses.gaze.shared import MAX_SAMPLE_AGE_S as GAZE_BOUND

    assert MAX_SAMPLE_AGE_S == GAZE_BOUND


# -- the daemon seam ------------------------------------------------------------------------


def _daemon(*, perception=None, face=None, shared=None):
    cfg = replace(
        Config(),
        facegesture=replace(FacegestureConfig(enabled=True), **(face or {})),
        perception=replace(PerceptionConfig(), **(shared or {})),
    )
    d = Daemon(config=cfg, platform=get_platform())
    d._perception = perception
    return d


def _source(camera=None):
    cam = camera or Camera()
    return SharedPerceptionSource(lambda: cam, Model, spawn=NoThread), cam


def test_a_default_install_has_no_shared_source_so_the_switch_keeps_its_own_camera():
    d = _daemon()
    backend = d._build_face_gesture_source(d._config)[0]
    assert backend._lease is None
    assert d._face_on_shared_source is False


def test_with_a_matching_shared_source_the_daemon_hands_the_backend_a_lease_and_opens_nothing():
    source, cam = _source()
    d = _daemon(perception=source)
    backend = d._build_face_gesture_source(d._config)[0]
    assert backend._lease is not None and backend._lease.name == "facegesture"
    assert d._face_on_shared_source is True
    assert cam.opens == 0, "building the backend must not open the camera"
    assert source.status().state is SourceState.DORMANT


def test_a_different_camera_index_keeps_the_own_capture_path_and_says_why(caplog):
    source, cam = _source()
    d = _daemon(perception=source, face={"camera_index": 1})
    with caplog.at_level(logging.INFO):
        backend = d._build_face_gesture_source(d._config)[0]
    assert backend._lease is None and d._face_on_shared_source is False
    assert "different cameras" in caplog.text
    assert cam.opens == 0


def test_a_backend_with_a_lease_never_builds_its_own_model_or_camera():
    source, _ = _source()
    d = _daemon(perception=source)
    backend = d._build_face_gesture_source(d._config)[0]

    def boom(*a, **k):
        raise AssertionError("the shared path must not own a camera or a model")

    backend._build_landmarker = boom
    backend._open_camera = boom
    backend.stop()      # run() leases, sees the stop at once and leaves; nothing else is built
    backend.run()


# -- the lifecycle, counted on a real source -------------------------------------------------


def test_the_face_switch_and_a_second_consumer_share_one_open():
    rig = Rig()
    other = rig.source.consumer("gaze")
    rig.start()
    other.start()
    assert rig.camera.opens == 1
    rig.lease.stop()
    assert rig.camera.closes == 0, "gaze still needs the device"
    other.stop()
    assert rig.camera.closes == 1, "the last one out closes the camera"


def test_run_takes_the_lease_once_and_releases_it_on_stop():
    rig = Rig()
    rig.backend.stop()
    rig.backend.run()
    assert rig.lease.log == ["start", "stop"]
    assert rig.camera.opens == 1 and rig.camera.closes == 1


def test_a_lease_that_cannot_start_ends_run_without_raising(caplog):
    rig = Rig()
    rig.lease.fail_start = RuntimeError("no camera")
    with caplog.at_level(logging.WARNING):
        rig.backend.run()
    assert "could not lease" in caplog.text
    assert rig.lease.log == ["start"]


def test_shutdown_mid_hold_releases_the_key_before_the_lease_goes():
    rig = Rig()
    order: list[str] = []
    rig.backend._on_hold_end = lambda: order.append("end")
    real_stop = rig.lease.stop
    rig.lease.stop = lambda: (order.append("lease.stop"), real_stop())[1]
    seen = []

    def after_start():
        for _ in range(5):
            rig.frame(0.9)
        seen.append(rig.backend._switch.held)
        rig.backend.stop()

    rig.lease.after_start = after_start
    rig.backend.run()
    assert seen == [True]
    assert order == ["end", "lease.stop"]


# -- behaviour: the same detectors, fed from the shared channel --------------------------------


def _own_path_events(scores):
    """The same scores through the own-capture loop, for the parity check."""
    from tests.test_facegesture_own_capture_path import _Cat, _Cv2, _FakeMediapipe

    frames = list(scores)
    cur = [frames[0]]
    events: list[str] = []
    backend = FaceGestureBackend(
        replace(FacegestureConfig(enabled=True), fps=60),
        lambda n: events.append("start"), lambda: events.append("end"),
    )

    class _Lm:
        def detect(self, image):
            shapes = [] if cur[0] is None else [[_Cat("jawOpen", cur[0])]]
            return type("R", (), {"face_blendshapes": shapes})

    class _Cap:
        def read(self):
            cur[0] = frames.pop(0)
            if not frames:
                backend.stop()
            return True, object()

    backend._loop(_Lm(), _Cap(), _Cv2(), _FakeMediapipe())
    return events


@pytest.mark.parametrize(
    "scores",
    [
        [0.0, 0.9, 0.9, 0.9, 0.9, 0.0, 0.0, 0.0],
        [0.9] * 4 + [None] * 3,
        [0.9] * 4 + [None] + [0.9] * 3 + [0.0] * 3,
        [0.2, 0.3, 0.26, 0.3, 0.2] * 4,
        [0.9, 0.9, 0.0, 0.9, 0.9, 0.0, 0.9, 0.9],
    ],
)
def test_the_shared_path_fires_exactly_what_the_own_capture_path_fires(scores):
    rig = Rig()
    rig.start()
    for s in scores:
        rig.frame(s)
    assert rig.events == _own_path_events(scores)


def test_one_observation_polled_many_times_counts_as_one_frame():
    rig = Rig()
    rig.start()
    rig.clock.tick()
    rig.model.shapes = {"jawOpen": 0.9}
    rig.source.observe()
    for _ in range(10):
        rig.backend._shared_step()      # min_hold_frames is 3; one sample must not be three
    assert rig.events == []
    rig.frame(0.9)
    rig.frame(0.9)
    assert rig.events == ["start"]


def test_a_camera_that_stalls_mid_hold_closes_the_microphone():
    rig = Rig()
    rig.start()
    for _ in range(4):
        rig.frame(0.9)
    assert rig.events == ["start"]
    rig.stall(MAX_SAMPLE_AGE_S + 0.5)
    assert rig.events == ["start", "end"], "a blind camera may only release, never hold"


def test_a_stale_sample_never_starts_a_hold():
    rig = Rig()
    rig.start()
    rig.frame(0.9)                      # one fresh frame at hold level ...
    rig.stall(MAX_SAMPLE_AGE_S + 2.0)   # ... then the camera goes quiet for good
    assert rig.events == []


def test_an_observation_without_a_blendshape_channel_releases_through_the_debounce():
    rig = Rig()
    rig.start()
    for _ in range(4):
        rig.frame(0.9)
    rig.frame(None)
    assert rig.events == ["start"], "one blurred frame must not cut the hold"
    rig.frame(None)
    assert rig.events == ["start", "end"]


def test_a_face_that_leaves_the_frame_entirely_releases_once_the_last_sample_is_stale():
    """The processor publishes nothing when no channel could be derived, so a vanished face
    is silence, and silence is judged by age. This is the one place the shared path is slower
    than the own-capture path (the freshness bound plus the debounce, not the debounce
    alone) -- slower to release, never to hold."""
    rig = Rig()
    rig.start()
    for _ in range(4):
        rig.frame(0.9)
    rig.model.shapes = None
    rig.model.gaze = False                  # nothing derivable: the source publishes no sample
    for _ in range(3):
        rig.clock.tick(1 / 15)
        rig.source.observe()
        rig.backend._shared_step()
    assert rig.events == ["start"], "still inside the freshness bound"
    rig.stall(MAX_SAMPLE_AGE_S + 0.3)
    assert rig.events == ["start", "end"]


def test_no_sample_before_the_first_frame_is_quiet_and_harmless():
    rig = Rig()
    rig.start()
    rig.stall(1.0)
    assert rig.events == []


# -- degradation: a missing blendshape channel costs only this switch -----------------------


def test_a_sample_with_gaze_but_no_blendshapes_never_fires_and_leaves_gaze_alone(caplog):
    rig = Rig()
    other = rig.source.consumer("gaze")
    rig.start()
    other.start()
    rig.model.gaze = True
    with caplog.at_level(logging.WARNING):
        for _ in range(NO_BLENDSHAPE_WARN_AFTER + 5):
            rig.clock.tick()
            rig.model.shapes = None            # no face channel in the sample
            rig.source.observe()
            rig.backend._shared_step()
    assert rig.events == []
    sample = other.latest()
    assert sample is not None and sample.gaze is not None, "the gaze channel is untouched"
    assert sample.face is None
    warned = [r for r in caplog.records if "no blendshape" in r.getMessage()]
    assert len(warned) == 1, "say it once, not once per frame"


def test_an_empty_blendshape_mapping_is_also_no_channel_and_warns_once(caplog):
    rig = Rig()
    rig.start()
    with caplog.at_level(logging.WARNING):
        for _ in range(NO_BLENDSHAPE_WARN_AFTER * 2):
            rig.clock.tick()
            rig.model.shapes = {}
            rig.source.observe()
            rig.backend._shared_step()
    assert rig.events == []
    assert sum("no blendshape" in r.getMessage() for r in caplog.records) == 1


def test_a_channel_that_was_working_does_not_trigger_the_never_had_one_warning(caplog):
    rig = Rig()
    rig.start()
    with caplog.at_level(logging.WARNING):
        rig.frame(0.1)
        for _ in range(NO_BLENDSHAPE_WARN_AFTER * 2):
            rig.frame(None)
    assert not [r for r in caplog.records if "no blendshape" in r.getMessage()]


def test_a_failed_source_is_explained_once_with_its_own_reason(caplog):
    rig = Rig()

    def boom():
        raise OSError("device busy")

    rig.camera.open = boom
    rig.start()
    assert rig.source.status().state is SourceState.FAILED
    with caplog.at_level(logging.WARNING):
        rig.stall(3.0)
    msgs = [r.getMessage() for r in caplog.records if "shared camera is not running" in r.getMessage()]
    assert len(msgs) == 1 and "OSError" in msgs[0]
    assert rig.events == []


# -- the mapping layer is unchanged by the camera it reads -------------------------------------


def test_extra_bindings_work_on_the_shared_path_and_emit_intents_only():
    intents = []
    rig = Rig(switches=[{"gesture": "smile", "intent": "hold_to_command"}])
    rig.backend._sink = intents.append
    rig.start()
    rig.clock.tick()
    rig.model.shapes = {"jawOpen": 0.0, "mouthSmileLeft": 0.9}
    for _ in range(4):
        rig.clock.tick()
        rig.source.observe()
        rig.backend._shared_step()
    assert [(i.gesture, i.phase) for i in intents] == [("smile", "press")]
    assert rig.events == [], "the legacy hold callbacks belong to the primary gesture only"

