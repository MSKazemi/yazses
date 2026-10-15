"""The camera owner under real ordering: slow opens, late workers, racing consumers.

`tests/test_perception_source.py` proves the lifecycle with fakes that answer at once
and a loop the test drives by hand. That is the right base, and it is also exactly what
a real webcam is not: `cv2.VideoCapture` can sit for seconds (a USB camera waking, a
macOS permission dialog nobody has answered yet), the model can be fetched on the first
open, and a capture thread is mid-read when its consumer goes away. Each test below
models one of those orderings with a *blocking* fake, so the thing the base file's
instant fakes hid is the thing under test:

* a camera that is still opening must not freeze ``status()`` (the daemon's status
  request and ``doctor`` both call it), a second consumer, or process shutdown -- the
  same shape as the Wayland portal that held ``Start`` open for an unanswered dialog;
* a consumer that leaves while the camera is opening must not leak the device that
  eventually opens;
* a restart must never have two devices open at once, even while the first open is
  still hung;
* a capture loop that outlives its session -- because a read was in flight, or because
  its thread was slow to start -- must neither fail nor read the *next* session's
  camera;
* the loop is joined **before** the device it reads is released.

Every wait here is bounded: a regression must turn into a failed assertion, never into
a hung suite. No camera, no model, no ``gaze`` extra.
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

import pytest

from yazses.perception import (
    FaceSignal,
    GazeSignal,
    HeadPoseSignal,
    PerceptionSample,
    SharedPerceptionSource,
    SourceState,
)

#: Upper bound for any single wait on another thread. Generous: it is only ever spent
#: when a test is already failing.
WAIT_S = 5.0
#: How long a call that must NOT block is given before it is called blocked.
PROMPT_S = 2.0


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #
class Frame:
    """Whatever a capture API returns. Identity is the point."""


def sample_at(timestamp_s: float) -> PerceptionSample:
    return PerceptionSample(
        timestamp_s=timestamp_s,
        gaze=GazeSignal(timestamp_s=timestamp_s, raw_x=0.1, raw_y=-0.2, confidence=0.9),
        head_pose=HeadPoseSignal(timestamp_s=timestamp_s, yaw=0.0, pitch=0.0, roll=0.0,
                                 confidence=0.8),
        face=FaceSignal(timestamp_s=timestamp_s, confidence=0.9, blendshapes={"jawOpen": 0.1}),
    )


class Ledger:
    """What happened to the devices, in order, across every capture the source built."""

    def __init__(self) -> None:
        self._guard = threading.Lock()
        self.events: list[str] = []
        self.live = 0
        self.max_live = 0
        self.captures: list[Capture] = []
        self.processors: list[Processor] = []

    def note(self, event: str) -> None:
        with self._guard:
            self.events.append(event)

    def opened(self) -> None:
        with self._guard:
            self.live += 1
            self.max_live = max(self.max_live, self.live)

    def closed(self) -> None:
        with self._guard:
            self.live -= 1


class Capture:
    """A camera whose open and read can be held, and which counts what is open."""

    def __init__(self, ledger: Ledger, *, hold_open: threading.Event | None = None,
                 hold_read: threading.Event | None = None,
                 read_error: Exception | None = None, open_delay_s: float = 0.0) -> None:
        self.ledger = ledger
        self.hold_open = hold_open
        self.hold_read = hold_read
        self.read_error = read_error
        self.open_delay_s = open_delay_s
        self.in_open = threading.Event()
        self.in_read = threading.Event()
        self.opens = 0
        self.reads = 0
        self.closes = 0
        self.is_open = False

    def open(self) -> None:
        self.opens += 1
        self.in_open.set()
        if self.hold_open is not None:
            self.hold_open.wait(WAIT_S)
        if self.open_delay_s:
            time.sleep(self.open_delay_s)
        self.is_open = True
        self.ledger.opened()
        self.ledger.note("open")

    def read(self) -> object | None:
        self.reads += 1
        self.in_read.set()
        if self.hold_read is not None:
            self.hold_read.wait(WAIT_S)
        if self.read_error is not None:
            raise self.read_error
        return Frame()

    def close(self) -> None:
        self.closes += 1
        if self.is_open:
            self.is_open = False
            self.ledger.closed()
        self.ledger.note("close-capture")


class Processor:
    def __init__(self, ledger: Ledger, *, stamp: Callable[[float], float] | None = None,
                 error: Exception | None = None) -> None:
        self.ledger = ledger
        self.stamp = stamp
        self.error = error
        self.closes = 0

    @property
    def name(self) -> str:
        return "fake"

    def process(self, frame: object, timestamp_s: float) -> PerceptionSample | None:
        if self.error is not None:
            raise self.error
        return sample_at(self.stamp(timestamp_s) if self.stamp else timestamp_s)

    def close(self) -> None:
        self.closes += 1
        self.ledger.note("close-processor")


class Worker:
    """A driver that never runs the body; ``join`` is recorded in the ledger."""

    def __init__(self, target: Callable[[], None], name: str, ledger: Ledger,
                 *, alive: bool = False) -> None:
        self.target = target
        self.name = name
        self.ledger = ledger
        self.alive = alive
        self.join_timeouts: list[float | None] = []

    def join(self, timeout: float | None = None) -> None:
        self.join_timeouts.append(timeout)
        self.ledger.note("join")

    def is_alive(self) -> bool:
        return self.alive


class Spawn:
    def __init__(self, ledger: Ledger, *, alive: bool = False) -> None:
        self.ledger = ledger
        self.alive = alive
        self.workers: list[Worker] = []

    def __call__(self, target: Callable[[], None], name: str) -> Worker:
        worker = Worker(target, name, self.ledger, alive=self.alive)
        self.workers.append(worker)
        return worker


class Rig:
    """A source wired to a ledger, with a hook for building each capture."""

    def __init__(self, *, capture_for: Callable[[Ledger, int], Capture] | None = None,
                 processor_for: Callable[[Ledger, int], Processor] | None = None,
                 alive: bool = False, join_timeout_s: float = 0.5) -> None:
        self.ledger = Ledger()
        self.spawn = Spawn(self.ledger, alive=alive)
        self.clock_value = 1_000.0
        self._capture_for = capture_for or (lambda ledger, n: Capture(ledger))
        self._processor_for = processor_for or (lambda ledger, n: Processor(ledger))
        self.captures_built = 0
        self.processors_built = 0
        self.source = SharedPerceptionSource(
            self._build_capture, self._build_processor,
            interval_s=0.0, clock=lambda: self.clock_value, spawn=self.spawn,
            join_timeout_s=join_timeout_s,
        )

    def _build_capture(self) -> Capture:
        self.captures_built += 1
        capture = self._capture_for(self.ledger, self.captures_built)
        self.ledger.captures.append(capture)
        return capture

    def _build_processor(self) -> Processor:
        self.processors_built += 1
        processor = self._processor_for(self.ledger, self.processors_built)
        self.ledger.processors.append(processor)
        return processor


def wait_until_opening(rig: Rig) -> None:
    """Block until the first capture exists and is inside ``open()``."""
    deadline = time.monotonic() + WAIT_S
    while not rig.ledger.captures and time.monotonic() < deadline:
        time.sleep(0.005)
    assert rig.ledger.captures, "no capture was ever built"
    assert rig.ledger.captures[0].in_open.wait(WAIT_S)


def in_thread(fn: Callable[[], object]) -> threading.Thread:
    thread = threading.Thread(target=fn, daemon=True)
    thread.start()
    return thread


def returns_promptly(fn: Callable[[], object]) -> tuple[bool, list[object]]:
    """Run *fn* on a thread; whether it finished within ``PROMPT_S``, and its result."""
    box: list[object] = []
    thread = in_thread(lambda: box.append(fn()))
    thread.join(PROMPT_S)
    return (not thread.is_alive()), box


# --------------------------------------------------------------------------- #
# A camera that is still opening
# --------------------------------------------------------------------------- #
def test_status_answers_while_the_camera_is_still_opening() -> None:
    """`status()` is what the daemon's status request and `doctor` call.

    A macOS permission dialog, a USB camera waking up or a first-run model fetch all
    keep the open going for seconds. The one lock must not be held across it, or every
    status request queues behind a dialog the user may not have seen.
    """
    proceed = threading.Event()
    rig = Rig(capture_for=lambda ledger, n: Capture(ledger, hold_open=proceed))
    lease = rig.source.consumer("gaze")
    starter = in_thread(lease.start)
    try:
        wait_until_opening(rig)

        prompt, box = returns_promptly(rig.source.status)

        assert prompt, "status() blocked behind a camera that was still opening"
        status = box[0]
        assert status.state is SourceState.STARTING  # type: ignore[attr-defined]
        assert status.consumers == ("gaze",)  # type: ignore[attr-defined]
        assert status.opens == 0  # type: ignore[attr-defined]
    finally:
        proceed.set()
        starter.join(WAIT_S)
    assert rig.source.status().state is SourceState.RUNNING
    assert rig.source.status().opens == 1


def test_a_second_consumer_is_not_held_up_by_a_camera_that_is_still_opening() -> None:
    proceed = threading.Event()
    rig = Rig(capture_for=lambda ledger, n: Capture(ledger, hold_open=proceed))
    first = rig.source.consumer("gaze")
    second = rig.source.consumer("headpointer")
    starter = in_thread(first.start)
    try:
        wait_until_opening(rig)

        prompt, _ = returns_promptly(second.start)
        assert prompt, "a second consumer waited for someone else's camera open"
        prompt, _ = returns_promptly(second.stop)
        assert prompt, "a non-final release waited for the camera open"
    finally:
        proceed.set()
        starter.join(WAIT_S)
    assert rig.source.status().state is SourceState.RUNNING
    assert rig.captures_built == 1


@pytest.mark.parametrize("how", [
    pytest.param("stop", id="last-lease-stops"),
    pytest.param("close", id="process-shutdown"),
])
def test_leaving_while_the_camera_opens_neither_waits_nor_leaks_the_device(how: str) -> None:
    """The consumer that asked has gone by the time the open finally returns.

    The shutdown path must not wait on a dialog nobody answers; and the device that
    eventually opens is closed, never installed into a dormant source.
    """
    proceed = threading.Event()
    rig = Rig(capture_for=lambda ledger, n: Capture(ledger, hold_open=proceed))
    lease = rig.source.consumer("gaze")
    starter = in_thread(lease.start)
    try:
        wait_until_opening(rig)

        leave = lease.stop if how == "stop" else rig.source.close
        prompt, _ = returns_promptly(leave)
        assert prompt, f"{how}() waited for a camera that was still opening"
        assert rig.source.status().state is SourceState.DORMANT
    finally:
        proceed.set()
        starter.join(WAIT_S)

    capture = rig.ledger.captures[0]
    assert capture.closes == 1, "the device that opened after its consumer left was leaked"
    assert rig.ledger.live == 0
    assert rig.processors_built == 0, "a model was loaded for a camera nobody wanted"
    assert rig.spawn.workers == [], "a capture loop was started for no consumer"
    status = rig.source.status()
    assert status.state is SourceState.DORMANT
    assert status.opens == 0
    assert rig.source.latest() is None


def test_a_restart_never_has_two_devices_open_even_while_the_first_open_hangs() -> None:
    """Stop, then start again, while the first open has not returned.

    Two ``cv2.VideoCapture`` on one device is the "device busy" this source exists to
    prevent. The second open must wait for the first to finish and be discarded.
    """
    first_gate = threading.Event()

    def capture_for(ledger: Ledger, n: int) -> Capture:
        return Capture(ledger, hold_open=first_gate if n == 1 else None)

    rig = Rig(capture_for=capture_for)
    lease = rig.source.consumer("gaze")
    starter = in_thread(lease.start)
    restarter = None
    try:
        wait_until_opening(rig)

        lease.stop()
        restarter = in_thread(lease.start)
        time.sleep(0.15)
        assert rig.captures_built == 1, "a second camera was built while the first still opened"
    finally:
        first_gate.set()
        starter.join(WAIT_S)
        if restarter is not None:
            restarter.join(WAIT_S)

    assert rig.ledger.max_live == 1, "two devices were open at once"
    assert rig.captures_built == 2
    assert rig.ledger.captures[0].closes == 1
    status = rig.source.status()
    assert status.state is SourceState.RUNNING
    assert status.opens == 1
    lease.stop()
    assert rig.ledger.live == 0


def test_consumers_racing_to_start_and_stop_open_and_close_the_camera_once() -> None:
    """Eight consumers, one barrier, a camera that takes a moment to open."""
    rig = Rig(capture_for=lambda ledger, n: Capture(ledger, open_delay_s=0.05))
    leases = [rig.source.consumer(f"c{i}") for i in range(8)]

    barrier = threading.Barrier(len(leases))

    def go(lease) -> Callable[[], None]:
        def run() -> None:
            barrier.wait(WAIT_S)
            lease.start()
        return run

    threads = [in_thread(go(lease)) for lease in leases]
    for thread in threads:
        thread.join(WAIT_S)
    assert all(not thread.is_alive() for thread in threads)
    assert rig.captures_built == 1
    assert rig.processors_built == 1
    assert rig.ledger.max_live == 1
    assert len(rig.source.status().consumers) == 8

    barrier = threading.Barrier(len(leases))

    def leave(lease) -> Callable[[], None]:
        def run() -> None:
            barrier.wait(WAIT_S)
            lease.stop()
        return run

    threads = [in_thread(leave(lease)) for lease in leases]
    for thread in threads:
        thread.join(WAIT_S)
    assert all(not thread.is_alive() for thread in threads)
    assert rig.ledger.captures[0].closes == 1
    assert rig.ledger.processors[0].closes == 1
    assert rig.source.status().state is SourceState.DORMANT


# --------------------------------------------------------------------------- #
# A capture loop that outlives its session
# --------------------------------------------------------------------------- #
def test_a_read_in_flight_at_release_cannot_fail_the_next_session() -> None:
    """The camera the old loop was reading dies under it; the new session is innocent.

    Release lands while a read is in flight; the consumer switches the feature straight
    back on. When the old read finally raises (the device it was reading was closed), its
    failure belongs to the session that ended -- it must not stop the new one.
    """
    gate = threading.Event()

    def capture_for(ledger: Ledger, n: int) -> Capture:
        if n == 1:
            return Capture(ledger, hold_read=gate, read_error=OSError("device closed under read"))
        return Capture(ledger)

    rig = Rig(capture_for=capture_for)
    lease = rig.source.consumer("gaze")
    lease.start()
    old_loop = in_thread(rig.spawn.workers[0].target)
    try:
        assert rig.ledger.captures[0].in_read.wait(WAIT_S)
        lease.stop()
        lease.start()
        assert rig.source.status().state is SourceState.RUNNING
    finally:
        gate.set()
        old_loop.join(WAIT_S)

    status = rig.source.status()
    assert status.state is SourceState.RUNNING, f"the old session's failure killed the new: {status}"
    assert status.failure_reason == ""
    assert rig.ledger.captures[1].is_open


def test_a_derivation_in_flight_at_release_cannot_fail_the_next_session() -> None:
    """Same ordering, through the model half: the old processor raises after release."""
    gate = threading.Event()

    class SlowThenBroken(Processor):
        def process(self, frame: object, timestamp_s: float) -> PerceptionSample | None:
            gate.wait(WAIT_S)
            raise RuntimeError("the model was closed under this frame")

    def processor_for(ledger: Ledger, n: int) -> Processor:
        return SlowThenBroken(ledger) if n == 1 else Processor(ledger)

    rig = Rig(processor_for=processor_for)
    lease = rig.source.consumer("gaze")
    lease.start()
    old_loop = in_thread(rig.spawn.workers[0].target)
    try:
        deadline = time.monotonic() + WAIT_S
        while rig.ledger.captures[0].reads == 0 and time.monotonic() < deadline:
            time.sleep(0.005)
        lease.stop()
        lease.start()
    finally:
        gate.set()
        old_loop.join(WAIT_S)

    assert rig.source.status().state is SourceState.RUNNING
    assert rig.source.latest() is None, "a sample from the previous session was published"


def test_a_loop_that_starts_late_never_reads_the_next_sessions_camera() -> None:
    """The thread was slow to start: the session ended and another began before it ran.

    A loop that looks up "the current" stop signal when it finally runs would adopt the
    NEW session's, and become a second reader on the new camera -- the duplicate
    inference loop the shared source exists to prevent.
    """
    rig = Rig()
    lease = rig.source.consumer("gaze")
    lease.start()
    lease.stop()
    lease.start()
    assert len(rig.spawn.workers) == 2

    stale = in_thread(rig.spawn.workers[0].target)
    stale.join(PROMPT_S)

    assert not stale.is_alive(), "the previous session's loop kept running"
    assert rig.ledger.captures[1].reads == 0, "a stale loop read the new session's camera"
    assert rig.source.status().state is SourceState.RUNNING


def test_a_loop_between_its_stop_check_and_its_read_cannot_adopt_the_next_camera() -> None:
    """The narrow window the stop signal cannot close: the check passed, then release.

    A loop that has just seen "not stopped" and is about to take the lock cannot be
    stopped by the event any more. What protects the next session is that the loop
    observes *its own* epoch (white-box: the loop's epoch lives on a thread-local).
    """
    rig = Rig()
    lease = rig.source.consumer("gaze")
    lease.start()
    old_epoch = rig.source._epoch
    lease.stop()
    lease.start()

    seen: list[bool] = []

    def old_loop_step() -> None:
        rig.source._loop.epoch = old_epoch
        seen.append(rig.source.observe())

    in_thread(old_loop_step).join(WAIT_S)

    assert seen == [False]
    assert rig.ledger.captures[1].reads == 0, "a loop from the ended session read the new camera"
    # A hand-driven caller has no session of its own and observes whichever is open.
    assert rig.source.observe() is True


def test_the_loop_is_joined_before_the_device_it_reads_is_released() -> None:
    """Closing a ``cv2.VideoCapture`` under a thread that is reading it is undefined.

    So the order is: stop signal, join the loop, then close the capture and the model.
    """
    rig = Rig()
    lease = rig.source.consumer("gaze")
    lease.start()

    lease.stop()

    order = [e for e in rig.ledger.events if e in {"join", "close-capture", "close-processor"}]
    assert order[0] == "join", f"a device was released before its loop was joined: {order}"
    assert sorted(order[1:]) == ["close-capture", "close-processor"]


def test_a_loop_that_will_not_stop_does_not_hold_up_shutdown(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The join is bounded; the devices are released and the user is told."""
    rig = Rig(alive=True, join_timeout_s=0.25)
    lease = rig.source.consumer("gaze")
    lease.start()

    with caplog.at_level(logging.WARNING, logger="yazses.perception.source"):
        prompt, _ = returns_promptly(rig.source.close)

    assert prompt
    assert rig.spawn.workers[0].join_timeouts == [0.25]
    assert rig.ledger.captures[0].closes == 1
    assert rig.ledger.processors[0].closes == 1
    assert rig.source.status().state is SourceState.DORMANT
    assert any("did not stop" in record.getMessage() for record in caplog.records)


# --------------------------------------------------------------------------- #
# Samples and time
# --------------------------------------------------------------------------- #
def test_a_sample_older_than_the_published_one_is_not_published() -> None:
    """A slower, older observation finishing last must not move the newest one back."""
    stamps = iter([100.0, 90.0, 110.0])
    rig = Rig(processor_for=lambda ledger, n: Processor(ledger, stamp=lambda t: next(stamps)))
    rig.source.consumer("gaze").start()

    assert rig.source.observe() is True
    assert rig.source.latest().timestamp_s == 100.0  # type: ignore[union-attr]

    assert rig.source.observe() is False, "an older observation was published"
    assert rig.source.latest().timestamp_s == 100.0  # type: ignore[union-attr]

    assert rig.source.observe() is True
    assert rig.source.latest().timestamp_s == 110.0  # type: ignore[union-attr]


# --------------------------------------------------------------------------- #
# Consumers that raise, and models that go missing
# --------------------------------------------------------------------------- #
def test_a_consumer_that_raises_inside_its_lease_still_releases_the_camera() -> None:
    rig = Rig()
    lease = rig.source.consumer("gaze")

    with pytest.raises(RuntimeError, match="consumer bug"):
        with lease:
            assert rig.source.status().state is SourceState.RUNNING
            raise RuntimeError("consumer bug")

    assert not lease.active
    assert rig.source.status().state is SourceState.DORMANT
    assert rig.ledger.live == 0


def test_a_model_that_goes_missing_is_a_contained_failure_and_the_next_try_recovers() -> None:
    """The cached model file is deleted between two opens (a cache cleaner, an upgrade)."""
    state = {"model_present": False}

    def processor_for(ledger: Ledger, n: int) -> Processor:
        if not state["model_present"]:
            raise FileNotFoundError("face_landmarker.task")
        return Processor(ledger)

    rig = Rig(processor_for=processor_for)
    lease = rig.source.consumer("gaze")

    lease.start()  # must not raise
    status = rig.source.status()
    assert status.state is SourceState.FAILED
    assert "FileNotFoundError" in status.failure_reason
    assert rig.ledger.captures[0].closes == 1, "the camera stayed open without a model"
    assert rig.ledger.live == 0

    lease.stop()
    state["model_present"] = True
    lease.start()

    assert rig.source.status().state is SourceState.RUNNING
    assert rig.source.status().opens == 1
    assert rig.ledger.live == 1
    lease.stop()
    assert rig.ledger.live == 0


def test_a_model_that_fails_mid_run_releases_the_camera_and_reads_no_more() -> None:
    rig = Rig(processor_for=lambda ledger, n: Processor(ledger, error=FileNotFoundError("gone")))
    lease = rig.source.consumer("gaze")
    lease.start()

    assert rig.source.observe() is False

    status = rig.source.status()
    assert status.state is SourceState.FAILED
    assert rig.ledger.live == 0, "the webcam stayed on after the model failed"
    reads = rig.ledger.captures[0].reads
    assert rig.source.observe() is False
    assert rig.ledger.captures[0].reads == reads
    assert lease.latest() is None
    lease.stop()
    assert rig.source.status().state is SourceState.DORMANT
