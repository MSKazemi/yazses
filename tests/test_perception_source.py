"""The one camera owner: one open for N consumers, and nothing at all when off.

`src/yazses/perception/source.py` (ADR-v2-145, EYE-CAM-001) exists because two
shipped features already open their own camera and their own FaceLandmarker, so a
machine with both enabled hands "device already busy" to whichever started second.
The architectural gate the ADR sets is a number — **one physical camera owner** —
so these tests count opens rather than reading the code and believing it.

Everything below runs with no camera, no model and no `gaze` extra installed: the
capture and the processor are injected fakes, and so is the thread. That is the
deal the injected seams buy, and it is why the loop is driven by hand in most of
these tests — a suite this size cannot afford a lifecycle whose tests are timing
races. One test does use the real thread, because "shutdown cannot leave the
capture thread alive" is a claim about a thread.

The privacy assertions are the ones worth being fussy about. A frame must not
outlive the observation it was derived from, so that is asserted with a weak
reference rather than by reading the code: the guard fails if anyone ever stores
the frame on the source, puts it on a sample, or lets it reach a log.
"""
from __future__ import annotations

import ast
import gc
import logging
import threading
import time
import weakref
from pathlib import Path

import pytest

import yazses.perception as perception
from yazses.perception import (
    FaceSignal,
    GazeSignal,
    HeadPoseSignal,
    PerceptionSample,
    SharedPerceptionSource,
    SourceState,
    build_perception_source,
)
from yazses.perception.signals import FacePerceptionSource

PACKAGE = Path(perception.__file__).resolve().parent


# --------------------------------------------------------------------------- #
# Fakes — a camera, a model and a thread, all made of counters
# --------------------------------------------------------------------------- #
class Frame:
    """Stands in for whatever the capture API hands back. Identity is the point."""


class FakeCapture:
    """A camera that counts what was done to it and holds no frame."""

    def __init__(self, *, open_error: Exception | None = None,
                 read_error: Exception | None = None, drop: bool = False,
                 max_reads: int | None = None) -> None:
        self.opens = 0
        self.closes = 0
        self.reads = 0
        self.open_error = open_error
        self.read_error = read_error
        #: Every read returns `None` — the ordinary dropped-frame path.
        self.drop = drop
        #: A ceiling for the tests that run the capture loop by hand. A loop that
        #: stopped honouring its shutdown would otherwise spin forever, and a test
        #: that hangs is worse than a test that fails: it takes the whole suite with
        #: it and says nothing about which contract broke.
        self.max_reads = max_reads

    def open(self) -> None:
        self.opens += 1
        if self.open_error is not None:
            raise self.open_error

    def read(self) -> object | None:
        self.reads += 1
        if self.max_reads is not None and self.reads > self.max_reads:
            raise AssertionError(f"the capture loop read {self.reads} frames without stopping")
        if self.read_error is not None:
            raise self.read_error
        return None if self.drop else Frame()

    def close(self) -> None:
        self.closes += 1


class FakeProcessor:
    """A model that returns a sample built from the timestamp it was given."""

    def __init__(self, *, name: str = "fake-landmarker") -> None:
        self._name = name
        self.calls = 0
        self.closes = 0
        #: Set to an exception to make the next derivation raise.
        self.error: Exception | None = None
        #: False means "no face this time".
        self.emit = True
        #: Which channels the sample carries, for the degradation tests.
        self.channels: tuple[str, ...] = ("gaze", "head_pose", "face")

    @property
    def name(self) -> str:
        return self._name

    def process(self, frame: object, timestamp_s: float) -> PerceptionSample | None:
        self.calls += 1
        if self.error is not None:
            raise self.error
        if not self.emit:
            return None
        return sample_at(timestamp_s, *self.channels)

    def close(self) -> None:
        self.closes += 1


class ManualWorker:
    """A driver that never runs the loop body — the test is the loop."""

    def __init__(self, target, name: str) -> None:
        self.target = target
        self.name = name
        self.joins = 0

    def join(self, timeout: float | None = None) -> None:
        self.joins += 1

    def is_alive(self) -> bool:
        return False


class ManualSpawn:
    def __init__(self) -> None:
        self.workers: list[ManualWorker] = []

    def __call__(self, target, name: str) -> ManualWorker:
        worker = ManualWorker(target, name)
        self.workers.append(worker)
        return worker


class Clock:
    """A monotonic reading the test moves on purpose."""

    def __init__(self, start: float = 1_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now


class Devices:
    """The injected pair plus how many times each was *built*.

    Built, not opened: "additional consumer -> no additional open **or model
    instance**" is two claims, and a source that opened one camera but created a
    second landmarker would still duplicate the inference the ADR is about.
    """

    def __init__(self, capture: FakeCapture | None = None,
                 processor: FakeProcessor | None = None) -> None:
        self.capture = capture if capture is not None else FakeCapture()
        self.processor = processor if processor is not None else FakeProcessor()
        self.captures_built = 0
        self.processors_built = 0

    def build_capture(self) -> FakeCapture:
        self.captures_built += 1
        return self.capture

    def build_processor(self) -> FakeProcessor:
        self.processors_built += 1
        return self.processor


def sample_at(timestamp_s: float, *channels: str) -> PerceptionSample:
    """A sample carrying exactly *channels*, all stamped with one clock reading."""
    return PerceptionSample(
        timestamp_s=timestamp_s,
        gaze=(
            GazeSignal(timestamp_s=timestamp_s, raw_x=0.1, raw_y=-0.2, confidence=0.9)
            if "gaze" in channels else None
        ),
        head_pose=(
            HeadPoseSignal(timestamp_s=timestamp_s, yaw=0.05, pitch=0.0, roll=0.0,
                           confidence=0.8)
            if "head_pose" in channels else None
        ),
        face=(
            FaceSignal(timestamp_s=timestamp_s, confidence=0.95,
                       blendshapes={"jawOpen": 0.4})
            if "face" in channels else None
        ),
    )


def make_source(devices: Devices | None = None, *, clock: Clock | None = None,
                spawn: ManualSpawn | None = None):
    """A source wired to fakes and to a driver that does not run."""
    devices = devices if devices is not None else Devices()
    spawn = spawn if spawn is not None else ManualSpawn()
    source = SharedPerceptionSource(
        devices.build_capture,
        devices.build_processor,
        interval_s=0.0,
        clock=clock if clock is not None else Clock(),
        spawn=spawn,
    )
    return source, devices, spawn


# --------------------------------------------------------------------------- #
# One camera owner
# --------------------------------------------------------------------------- #
def test_constructing_a_source_opens_nothing() -> None:
    """The lifecycle is subscriber-driven: existing is not asking."""
    source, devices, spawn = make_source()
    assert devices.captures_built == 0
    assert devices.capture.opens == 0
    assert spawn.workers == []
    assert source.status().state is SourceState.DORMANT
    assert source.status().opens == 0


def test_the_first_consumer_opens_the_camera_once() -> None:
    source, devices, spawn = make_source()
    source.consumer("gaze").start()
    assert devices.capture.opens == 1
    assert devices.captures_built == 1
    assert devices.processors_built == 1
    assert len(spawn.workers) == 1
    assert source.status().state is SourceState.RUNNING
    assert source.status().opens == 1
    assert source.status().backend == "fake-landmarker"


def test_three_consumers_share_one_camera_and_one_model() -> None:
    """The ADR's hard architectural gate, stated as the number it is."""
    source, devices, spawn = make_source()
    leases = [source.consumer(name) for name in ("gaze", "headpointer", "facegesture")]
    for lease in leases:
        lease.start()
    assert devices.capture.opens == 1
    assert devices.captures_built == 1
    assert devices.processors_built == 1
    assert len(spawn.workers) == 1
    assert source.status().consumers == ("facegesture", "gaze", "headpointer")


def test_a_consumer_releasing_leaves_the_others_running() -> None:
    source, devices, _ = make_source()
    gaze = source.consumer("gaze")
    head = source.consumer("headpointer")
    gaze.start()
    head.start()

    gaze.stop()
    assert devices.capture.closes == 0
    assert source.status().state is SourceState.RUNNING
    assert source.status().consumers == ("headpointer",)
    assert source.observe() is True, "the remaining consumer stopped getting samples"
    assert head.latest() is not None


def test_the_last_release_closes_the_camera_and_the_model() -> None:
    source, devices, spawn = make_source()
    gaze = source.consumer("gaze")
    head = source.consumer("headpointer")
    gaze.start()
    head.start()

    gaze.stop()
    head.stop()
    assert devices.capture.closes == 1
    assert devices.processor.closes == 1
    assert spawn.workers[0].joins == 1, "the capture loop was never joined"
    status = source.status()
    assert status.state is SourceState.DORMANT
    assert status.consumers == ()
    assert status.opens == 1


def test_a_fourth_consumer_after_everyone_left_opens_the_camera_again() -> None:
    """Dormant is not poisoned: a feature switched off and on again works."""
    source, devices, _ = make_source()
    lease = source.consumer("gaze")
    lease.start()
    lease.stop()
    source.consumer("headpointer").start()
    assert devices.capture.opens == 2
    assert source.status().opens == 2
    assert source.status().state is SourceState.RUNNING


# --------------------------------------------------------------------------- #
# Idempotence — the silent leak this prevents is a camera nobody can account for
# --------------------------------------------------------------------------- #
def test_starting_twice_takes_one_lease_so_one_stop_still_closes() -> None:
    source, devices, _ = make_source()
    lease = source.consumer("gaze")
    lease.start()
    lease.start()
    assert devices.capture.opens == 1
    lease.stop()
    assert devices.capture.closes == 1, "a double start pinned the camera open"
    assert source.status().state is SourceState.DORMANT


def test_stopping_twice_closes_once_and_raises_nothing() -> None:
    source, devices, _ = make_source()
    lease = source.consumer("gaze")
    lease.start()
    lease.stop()
    lease.stop()
    assert devices.capture.closes == 1


def test_stopping_a_lease_that_was_never_started_does_nothing() -> None:
    source, devices, _ = make_source()
    source.consumer("gaze").stop()
    assert devices.captures_built == 0
    assert devices.capture.closes == 0
    assert source.status().state is SourceState.DORMANT


def test_close_releases_every_lease_whatever_the_bookkeeping_says() -> None:
    """Process shutdown: a consumer that forgot to stop cannot pin the camera."""
    source, devices, spawn = make_source()
    leases = [source.consumer(name) for name in ("gaze", "facegesture")]
    for lease in leases:
        lease.start()

    source.close()
    assert devices.capture.closes == 1
    assert devices.processor.closes == 1
    assert spawn.workers[0].joins == 1
    assert [lease.active for lease in leases] == [False, False]
    assert source.status().state is SourceState.DORMANT
    assert source.status().consumers == ()


def test_close_is_idempotent_and_safe_on_a_source_that_never_ran() -> None:
    source, devices, _ = make_source()
    source.close()
    source.close()
    assert devices.captures_built == 0
    assert devices.capture.closes == 0


def test_a_lease_is_a_context_manager() -> None:
    source, devices, _ = make_source()
    with source.consumer("gaze") as lease:
        assert lease.active
        assert devices.capture.opens == 1
    assert not lease.active
    assert devices.capture.closes == 1


# --------------------------------------------------------------------------- #
# What a consumer sees
# --------------------------------------------------------------------------- #
def test_the_lease_is_the_source_protocol_the_signals_module_declares() -> None:
    """#393 declared `FacePerceptionSource`; this is the implementation of it.

    Asserted rather than assumed because the whole reason the Protocol lives beside
    the values is that a consumer (#395, #396) can be written against it with no
    camera installed — a lease that had drifted from it would break that silently.
    """
    lease = make_source()[0].consumer("gaze")
    assert isinstance(lease, FacePerceptionSource)


def test_a_released_consumer_reads_nothing_even_while_the_camera_is_open() -> None:
    """A feature the user switched off must not still be seeing faces."""
    source, _, _ = make_source()
    gaze = source.consumer("gaze")
    head = source.consumer("headpointer")
    gaze.start()
    head.start()
    assert source.observe() is True

    gaze.stop()
    assert gaze.latest() is None
    assert head.latest() is not None, "the remaining consumer lost its samples too"


def test_reading_does_not_restamp_and_no_face_does_not_republish() -> None:
    """A stale sample must keep ageing, or "no face" reads as a fresh face forever."""
    clock = Clock()
    source, devices, _ = make_source(clock=clock)
    source.consumer("gaze").start()
    assert source.observe() is True
    first = source.latest()
    assert first is not None
    assert source.status().last_sample_age_s == pytest.approx(0.0)

    devices.processor.emit = False  # the face left the frame
    clock.now += 0.5
    assert source.observe() is False
    assert source.latest() is first, "a new sample appeared out of no observation"
    assert source.status().last_sample_age_s == pytest.approx(0.5)


def test_the_sample_is_dropped_when_the_camera_closes() -> None:
    """Nothing may act on a face the camera saw before it was switched off."""
    source, _, _ = make_source()
    lease = source.consumer("gaze")
    lease.start()
    assert source.observe() is True
    assert source.latest() is not None

    lease.stop()
    assert source.latest() is None


def test_observing_while_dormant_touches_nothing() -> None:
    source, devices, _ = make_source()
    assert source.observe() is False
    assert devices.capture.reads == 0


# --------------------------------------------------------------------------- #
# Per-channel degradation
# --------------------------------------------------------------------------- #
def test_one_channel_missing_does_not_stop_the_others() -> None:
    """ADR-v2-145 invariant 6: no facial transform costs head pose, nothing else."""
    devices = Devices()
    devices.processor.channels = ("gaze", "face")
    source, _, _ = make_source(devices)
    source.consumer("gaze").start()

    assert source.observe() is True
    sample = source.latest()
    assert sample is not None
    assert sample.channels == ("gaze", "face")
    assert sample.head_pose is None
    assert source.status().state is SourceState.RUNNING
    assert source.status().channels == ("gaze", "face")


def test_a_sample_with_no_channels_at_all_is_still_not_a_failure() -> None:
    """Presence without a derived channel is a quality problem, not a broken camera."""
    devices = Devices()
    devices.processor.channels = ()
    source, _, _ = make_source(devices)
    source.consumer("gaze").start()

    assert source.observe() is True
    assert source.status().state is SourceState.RUNNING
    assert source.status().channels == ()


def test_a_dropped_frame_is_not_a_failure() -> None:
    source, devices, _ = make_source(Devices(capture=FakeCapture(drop=True)))
    source.consumer("gaze").start()

    assert source.observe() is False
    assert source.observe() is False
    assert source.status().state is SourceState.RUNNING
    assert devices.processor.calls == 0, "a missing frame was handed to the model"


# --------------------------------------------------------------------------- #
# Failure is contained — dictation is never in this path
# --------------------------------------------------------------------------- #
def test_a_camera_that_will_not_open_does_not_raise_at_the_consumer() -> None:
    devices = Devices(capture=FakeCapture(open_error=OSError("device or resource busy")))
    source, _, spawn = make_source(devices)
    lease = source.consumer("gaze")

    lease.start()  # must not raise

    status = source.status()
    assert status.state is SourceState.FAILED
    assert "device or resource busy" in status.failure_reason
    assert "OSError" in status.failure_reason
    assert lease.active, "the consumer still holds its lease; it just gets no samples"
    assert lease.latest() is None
    assert devices.capture.closes == 1, "the half-opened capture was not released"
    assert spawn.workers == [], "a capture loop was started over a camera that never opened"


def test_a_model_that_will_not_load_releases_the_camera_it_opened() -> None:
    devices = Devices()

    def exploding_processor() -> FakeProcessor:
        raise RuntimeError("the face landmarker model is missing")

    source = SharedPerceptionSource(
        devices.build_capture, exploding_processor, interval_s=0.0,
        clock=Clock(), spawn=ManualSpawn(),
    )
    source.consumer("gaze").start()

    assert source.status().state is SourceState.FAILED
    assert "landmarker model is missing" in source.status().failure_reason
    assert devices.capture.closes == 1


def test_a_camera_that_stops_delivering_frames_fails_without_raising() -> None:
    devices = Devices()
    source, _, _ = make_source(devices)
    source.consumer("gaze").start()
    devices.capture.read_error = OSError("select timeout")

    assert source.observe() is False

    status = source.status()
    assert status.state is SourceState.FAILED
    assert "select timeout" in status.failure_reason
    assert devices.capture.closes == 1, "a failed source kept the device"
    assert source.latest() is None


def test_a_processor_that_raises_fails_without_raising() -> None:
    devices = Devices()
    source, _, _ = make_source(devices)
    source.consumer("gaze").start()
    devices.processor.error = ValueError("unexpected landmark count")

    assert source.observe() is False
    assert source.status().state is SourceState.FAILED
    assert "unexpected landmark count" in source.status().failure_reason
    assert devices.processor.closes == 1


def test_a_failed_source_is_not_reopened_under_the_consumers_holding_it() -> None:
    """A retry loop against a camera that just refused is worse than no camera."""
    devices = Devices()
    source, _, _ = make_source(devices)
    gaze = source.consumer("gaze")
    gaze.start()
    devices.capture.read_error = OSError("gone")
    source.observe()

    source.consumer("headpointer").start()
    assert devices.capture.opens == 1
    assert source.status().state is SourceState.FAILED


def test_releasing_a_failed_source_lets_the_next_consumer_try_again() -> None:
    devices = Devices()
    source, _, _ = make_source(devices)
    lease = source.consumer("gaze")
    lease.start()
    devices.capture.read_error = OSError("gone")
    source.observe()
    assert source.status().state is SourceState.FAILED

    lease.stop()
    assert source.status().state is SourceState.DORMANT
    assert source.status().failure_reason == ""

    devices.capture.read_error = None
    source.consumer("gaze").start()
    assert devices.capture.opens == 2
    assert source.status().state is SourceState.RUNNING


def test_a_close_that_raises_does_not_stop_the_teardown() -> None:
    class BadCapture(FakeCapture):
        def close(self) -> None:
            super().close()
            raise OSError("release failed")

    devices = Devices(capture=BadCapture())
    source, _, _ = make_source(devices)
    lease = source.consumer("gaze")
    lease.start()

    lease.stop()  # must not raise
    assert devices.processor.closes == 1, "the model was not closed after the camera threw"
    assert source.status().state is SourceState.DORMANT


def test_a_driver_that_cannot_start_is_contained() -> None:
    devices = Devices()

    def refusing_spawn(target, name):
        raise RuntimeError("can't start new thread")

    source = SharedPerceptionSource(
        devices.build_capture, devices.build_processor, interval_s=0.0,
        clock=Clock(), spawn=refusing_spawn,
    )
    source.consumer("gaze").start()

    assert source.status().state is SourceState.FAILED
    assert "can't start new thread" in source.status().failure_reason
    assert devices.capture.closes == 1


# --------------------------------------------------------------------------- #
# The capture loop
# --------------------------------------------------------------------------- #
def test_the_loop_body_is_the_public_observation() -> None:
    """The worker runs `observe`, so every test of that method tests the loop too.

    Worth pinning: if the loop ever grew its own copy of the read-derive-publish
    path, every assertion in this file would still pass while the thing that runs
    in production went untested.
    """
    source, devices, spawn = make_source(Devices(capture=FakeCapture(max_reads=8)))
    lease = source.consumer("gaze")
    lease.start()
    passes: list[bool] = []
    observe = source.observe

    def counting() -> bool:
        passes.append(True)
        lease.stop()  # one pass is enough; this ends the loop
        if len(passes) > 2:
            raise AssertionError("the loop ignored the last consumer leaving")
        return observe()

    source.observe = counting  # type: ignore[method-assign]
    spawn.workers[0].target()
    assert passes == [True], "the capture loop does not go through `observe`"
    assert devices.capture.closes == 1


def test_the_loop_returns_as_soon_as_it_is_stopped() -> None:
    source, devices, spawn = make_source(Devices(capture=FakeCapture(max_reads=8)))
    lease = source.consumer("gaze")
    lease.start()
    lease.stop()

    spawn.workers[0].target()  # would hang if shutdown were not visible to the loop
    assert devices.capture.reads == 0


def test_the_loop_returns_on_a_failure_instead_of_spinning() -> None:
    devices = Devices(capture=FakeCapture(read_error=OSError("gone"), max_reads=8))
    source, _, spawn = make_source(devices)
    source.consumer("gaze").start()

    spawn.workers[0].target()  # would spin forever on a dead camera

    assert source.status().state is SourceState.FAILED
    assert devices.capture.reads == 1


def test_a_sample_observed_while_the_camera_closes_is_not_published() -> None:
    """The one real race, made deterministic: teardown lands mid-observation."""
    devices = Devices()
    source = SharedPerceptionSource(
        devices.build_capture, devices.build_processor, interval_s=0.0,
        clock=Clock(), spawn=ManualSpawn(),
    )
    lease = source.consumer("gaze")
    lease.start()

    real_process = devices.processor.process

    def closing_process(frame: object, timestamp_s: float):
        lease.stop()  # the consumer goes away while this frame is being derived
        return real_process(frame, timestamp_s)

    devices.processor.process = closing_process  # type: ignore[method-assign]
    assert source.observe() is False
    assert source.latest() is None, "a sample from a closed camera reached a consumer"


def test_the_default_driver_is_a_thread_that_stops_with_the_last_consumer() -> None:
    """`shutdown cannot leave capture/model thread alive` — the one threaded test."""
    devices = Devices()
    source = SharedPerceptionSource(
        devices.build_capture, devices.build_processor, interval_s=0.001,
    )
    lease = source.consumer("headpointer")
    lease.start()

    deadline = time.monotonic() + 5.0
    while source.latest() is None and time.monotonic() < deadline:
        time.sleep(0.005)
    assert source.latest() is not None, "the default thread driver produced no sample"
    assert "yazses-perception" in {thread.name for thread in threading.enumerate()}

    lease.stop()

    assert "yazses-perception" not in {thread.name for thread in threading.enumerate()}
    assert devices.capture.closes == 1
    assert devices.processor.closes == 1
    assert source.status().state is SourceState.DORMANT
    assert devices.capture.opens == 1


# --------------------------------------------------------------------------- #
# Privacy — frames stay inside the observation (ADR-011, ADR-v2-145 invariant 3)
# --------------------------------------------------------------------------- #
def test_a_frame_does_not_outlive_the_observation_it_was_derived_from() -> None:
    """Asserted with a weak reference, not by reading the code.

    This fails if the frame is ever stored on the source, attached to a sample, or
    kept by anything else the observation touches — which is the whole of the
    "frames stay in RAM inside the source" promise, expressed as a fact about
    lifetime rather than a claim about intent.
    """
    seen: list[weakref.ReferenceType[object]] = []

    class Watching(FakeProcessor):
        def process(self, frame: object, timestamp_s: float):
            seen.append(weakref.ref(frame))
            return super().process(frame, timestamp_s)

    source, _, _ = make_source(Devices(processor=Watching()))
    source.consumer("gaze").start()
    assert source.observe() is True

    gc.collect()
    assert seen, "the processor was never handed a frame — this proves nothing"
    assert seen[0]() is None, "the frame outlived the observation"


def test_no_frame_or_sample_detail_reaches_a_log(caplog: pytest.LogCaptureFixture) -> None:
    """A camera failure is reported as a state and a reason, never as data."""
    token = "FRAME-PIXELS-8f3a"

    class LoudFrame:
        def __repr__(self) -> str:
            return token

    class LoudCapture(FakeCapture):
        def read(self) -> object | None:
            self.reads += 1
            return LoudFrame()

    devices = Devices(capture=LoudCapture())
    source, _, _ = make_source(devices)
    with caplog.at_level(logging.DEBUG, logger="yazses.perception.source"):
        source.consumer("gaze").start()
        assert source.observe() is True
        devices.processor.error = OSError("device disconnected")
        assert source.observe() is False

    assert source.status().state is SourceState.FAILED
    assert token not in caplog.text
    assert token not in repr(source.status())


def test_the_status_carries_no_biometric_detail() -> None:
    """Observability is state, count, name and age — the spec's whole list."""
    source, _, _ = make_source()
    source.consumer("gaze").start()
    source.observe()
    status = source.status()

    assert set(vars(status)) == {
        "state", "backend", "consumers", "opens", "channels",
        "last_sample_age_s", "failure_reason",
    }
    text = repr(status)
    for leak in ("jawOpen", "raw_x", "yaw", "0.4", "blendshape"):
        assert leak not in text


# --------------------------------------------------------------------------- #
# Dormancy — the config half of "zero camera work"
# --------------------------------------------------------------------------- #
class Section:
    """A stub `[perception]` section; the factory duck-types it like the gaze one."""

    def __init__(self, **kw) -> None:
        self.enabled = kw.pop("enabled", False)
        self.camera_index = kw.pop("camera_index", 0)
        self.fps = kw.pop("fps", 15)
        assert not kw, kw


def _exploding_capture_factory(index: int):  # pragma: no cover - must not run
    raise AssertionError(f"a camera was built for index {index} with perception off")


def test_the_shipped_default_builds_no_source_at_all() -> None:
    """ADR-v2-145 invariant 2, at the only place that can decide it."""
    from yazses.config import Config

    assert Config().perception.enabled is False
    assert build_perception_source(
        Config().perception,
        capture_factory=_exploding_capture_factory,
        processor_factory=FakeProcessor,
    ) is None


def test_a_disabled_section_never_reaches_the_camera_factory() -> None:
    assert build_perception_source(
        Section(enabled=False),
        capture_factory=_exploding_capture_factory,
        processor_factory=FakeProcessor,
    ) is None


def test_an_enabled_section_with_no_backend_wired_stays_dormant() -> None:
    """The state this ships in: the owner exists in design, not yet in a device."""
    assert build_perception_source(Section(enabled=True)) is None
    assert build_perception_source(Section(enabled=True), processor_factory=FakeProcessor) is None
    assert build_perception_source(
        Section(enabled=True), capture_factory=lambda index: FakeCapture()
    ) is None


def test_an_enabled_section_builds_a_source_that_has_still_opened_nothing() -> None:
    built: list[int] = []

    def capture_factory(index: int) -> FakeCapture:
        built.append(index)
        return FakeCapture()

    source = build_perception_source(
        Section(enabled=True, camera_index=2),
        capture_factory=capture_factory,
        processor_factory=FakeProcessor,
    )
    assert source is not None
    assert built == [], "building the source opened a camera"
    assert source.status().state is SourceState.DORMANT

    source.consumer("gaze").start()
    assert built == [2], "the configured camera index did not reach the capture"
    source.close()


def test_the_daemon_owns_the_source_and_a_default_install_has_none() -> None:
    """"One owner per daemon" has to be true of an object with a daemon-long life.

    So the daemon holds it (ADR-v2-145) — and on every install today that is `None`,
    because the section ships off and no camera backend is wired to the owner yet.
    Asserted on a real daemon rather than on the builder alone: an attribute that was
    never assigned would make the shutdown path silently skip the camera release.
    """
    from yazses.config import Config
    from yazses.core.daemon import Daemon
    from yazses.platform import get_platform

    daemon = Daemon(config=Config(), platform=get_platform())
    assert daemon._perception is None
    assert daemon._build_perception_source(Config()) is None


@pytest.mark.parametrize(
    ("fps", "interval_s"),
    [(15, 1 / 15), (30, 1 / 30), (1, 1.0), (0, 1.0), (-5, 1.0), (600, 1 / 60)],
)
def test_the_frame_rate_is_read_and_held_to_a_usable_range(fps: int, interval_s: float) -> None:
    """`fps = 0` is type-valid and would divide by zero; a negative would spin a core."""
    source = build_perception_source(
        Section(enabled=True, fps=fps),
        capture_factory=lambda index: FakeCapture(),
        processor_factory=FakeProcessor,
    )
    assert source is not None
    assert source.interval_s == pytest.approx(interval_s)


# --------------------------------------------------------------------------- #
# The lifecycle brings no camera dependency with it
# --------------------------------------------------------------------------- #
def _imports(path: Path, *, module_level_only: bool) -> set[str]:
    """Module names imported by *path*, optionally only at module level.

    Module level is the distinction that matters for an optional extra: AGENTS.md
    rule 3 allows a heavy import *inside the function that needs it* and forbids it
    at the top, so a scan that cannot tell them apart would either miss the real
    violation or ban the pattern the whole repository uses.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    nodes = tree.body if module_level_only else list(ast.walk(tree))
    names: set[str] = set()
    for node in nodes:
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def _package_files() -> list[Path]:
    files = sorted(PACKAGE.rglob("*.py"))
    assert files, f"no source found under {PACKAGE} — this scan proves nothing"
    return files


def _offenders(names: set[str], forbidden: str) -> set[str]:
    """The imports in *names* that are *forbidden*, or something inside it.

    Matched on the dotted prefix rather than on the first component, because the
    first component of `yazses.config` is `yazses` — and a check that compared
    `name.split(".")[0]` against `"yazses.config"` could never match anything at
    all, which is how a parametrized guard ends up with one vacuous case.
    """
    return {name for name in names if name == forbidden or name.startswith(f"{forbidden}.")}


def test_the_scan_sees_the_imports_at_all() -> None:
    """Guard the guard: a wrong path or an over-narrow walk reports compliance."""
    source_module = PACKAGE / "source.py"
    assert "threading" in _imports(source_module, module_level_only=True)
    assert "yazses.perception.signals" in _imports(source_module, module_level_only=False)


@pytest.mark.parametrize("forbidden", ["cv2", "mediapipe", "numpy", "torch", "yazses.config"])
def test_no_camera_dependency_is_imported_at_module_level(forbidden: str) -> None:
    """A base install with no extras must import and run (AGENTS.md rule 3).

    Whole-package and module-level: the MediaPipe adapter (#395) will land in here
    and is *expected* to import mediapipe lazily inside the function that needs it.
    What must never happen is that import moving to the top, where a fresh install
    with no `gaze` extra meets it on startup.
    """
    offenders = {
        path.name
        for path in _package_files()
        if _offenders(_imports(path, module_level_only=True), forbidden)
    }
    assert not offenders, f"{sorted(offenders)} import {forbidden} at module level"


@pytest.mark.parametrize("forbidden", ["cv2", "mediapipe", "numpy", "torch", "yazses.config"])
def test_the_lifecycle_never_imports_a_camera_dependency_at_all(forbidden: str) -> None:
    """The seams are injected, so these two files have no reason to, at any depth.

    `signals.py` is held to a stricter version of this in
    `tests/test_perception_signals.py` — it may not import a thread or a config
    either. Here the thread is the point of the module, and the camera still is not.
    """
    for path in (PACKAGE / "source.py", PACKAGE / "factory.py"):
        offenders = _offenders(_imports(path, module_level_only=False), forbidden)
        assert not offenders, f"{path.name} imports {sorted(offenders)}"
