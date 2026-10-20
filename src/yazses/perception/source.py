"""The single camera owner: leases in, derived samples out (ADR-v2-145, EYE-CAM-001).

Two shipped features already open their own ``cv2.VideoCapture`` and their own
FaceLandmarker — Glance-Type gaze and the Face-Gesture Switch — and nothing
arbitrates between them. Enable both and the second one meets "device already
busy"; which one that is depends on whichever initialised first. The Head-Pointer
would have been a third. This module is the arbiter: one object owns the camera
and the model, every feature holds a **lease** on it, and the derived numbers of
``src/yazses/perception/signals.py`` are the only thing that crosses back out.

Four properties are the whole point, and each is a defect this programme has
already paid for somewhere:

**One open for N consumers.** The camera is opened by the transition from zero
leases to one, and by nothing else. A second, third or tenth consumer shares that
observation — :attr:`PerceptionStatus.opens` counts the opens so a test, and
``doctor``, can hold that claim to a number rather than to a promise.

**The last one out closes the door.** Releasing back to zero leases closes the
camera and the model, and drops the last sample with them: a consumer must not be
able to act on a face the camera saw before it was switched off. Both ``start``
and ``stop`` are idempotent per lease, because a feature that starts twice and
stops once would otherwise pin the camera on forever — the leak is silent, and the
symptom is a webcam light nobody can account for.

**Nothing happens until someone asks.** Constructing a source opens nothing,
probes nothing and imports nothing: the capture and the processor are built by
injected factories on the first lease. That is what makes "no camera feature
enabled means zero camera work" (ADR-v2-145 invariant 2) a property of the code
rather than a review habit, and it is why every test below runs with no camera and
no ``gaze`` extra installed.

**A failure here is not the daemon's failure.** A camera that will not open, a
read that raises, a processor that throws — each stops the sensing, records why,
and returns. Nothing propagates out of :meth:`PerceptionLease.start` or the worker
loop, because ordinary dictation is never in this path and a webcam is not allowed
to take it down (ADR-v2-145, and the same rule ``src/yazses/gaze/factory.py``
already follows by returning ``None``).

## Frames

A frame exists as a local variable inside :meth:`SharedPerceptionSource.observe`
and nowhere else. It is never stored on the source, never published, never logged
and never interpolated into a message — the boundary values carry no field that
could hold one, and this side is where that stops being true if anyone is careless
(ADR-011). The one hole left is a *processor* that puts frame content into its own
exception message, which is why the seam's contract below forbids it.

## What is deliberately not here

No callback or subscription API: consumers pull with :meth:`latest`, so "a
consumer exception must not crash the source loop" is structural rather than
guarded — the source never calls a consumer at all. And of the six states the spec
sketches, four are materialised. ``STARTING`` is, because opening a camera is *not*
instant (a permission dialog, a USB camera waking, a first-run model fetch) and the
bookkeeping lock is not held across it, so a reader really can observe it.
``STOPPING`` is not: it is only the moment the devices are being set aside, a state
no reader can see. ``DEGRADED`` would need to know which channels *this* install
expects; per-channel degradation is visible where it is actually decided — on the
sample, as ``channels``.

## Ordering the fakes cannot show

The lifecycle is exercised with blocking fakes in
``tests/test_perception_source_concurrency.py``, because these are the orderings a
real camera produces and an instant fake hides: a status request during a slow open;
the last consumer leaving mid-open (the opened device is closed, never installed); a
stop-then-start while the first open still hangs (the second waits, so two handles on
one webcam never exist); a capture loop that outlives its session (its failure and its
reads are discarded); and the loop being joined *before* the device it reads is
released.
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable

from yazses.perception.signals import PerceptionSample

__all__ = [
    "FAILURE_CAMERA",
    "FAILURE_DEPENDENCY",
    "FAILURE_KINDS",
    "FAILURE_MODEL",
    "FAILURE_PROCESSING",
    "FrameCapture",
    "FrameProcessor",
    "PerceptionLease",
    "PerceptionStatus",
    "SharedPerceptionSource",
    "SourceState",
    "Worker",
    "describe_open_failure",
]

log = logging.getLogger(__name__)

#: Longest a failure reason may be. A camera error is a sentence, not a payload,
#: and an unbounded one is a place for something unintended to travel.
_MAX_REASON = 200

#: Where a contained failure came from -- one value per *place the fix lives*, the same
#: reasoning ``cameraperm.CameraBlocker`` gives (EYE-OBS-001, #416). A camera that is busy,
#: a dependency that is not installed and a face model that could not be fetched all end
#: the session the same way, and before this they all read "the camera could not be
#: opened" -- which sent somebody behind a firewall to look for the application holding
#: their webcam.
#:
#: The camera itself: it would not open, or a read from it raised.
FAILURE_CAMERA = "camera"
#: An optional dependency (``cv2``, ``mediapipe``) could not be imported.
FAILURE_DEPENDENCY = "dependency"
#: The camera opened, and the face model could not be fetched or loaded.
FAILURE_MODEL = "model"
#: Both opened, and deriving signals from a frame, or starting the loop, failed.
FAILURE_PROCESSING = "processing"
#: Every kind, in the order a session reaches them. ``""`` means "no failure".
FAILURE_KINDS: tuple[str, ...] = (
    FAILURE_CAMERA,
    FAILURE_DEPENDENCY,
    FAILURE_MODEL,
    FAILURE_PROCESSING,
)


@runtime_checkable
class FrameCapture(Protocol):
    """The camera, as the one owner sees it — one implementation per capture API.

    Deliberately the narrowest thing a webcam can be: open it, read a frame, close
    it. The frame is typed ``object`` because nothing here may know what it is; the
    source hands it straight to the processor and drops it. Opening is separate
    from construction so that a capture can be built cheaply and the *device* is
    touched only by :meth:`open`, which is the call that has to be countable.
    """

    def open(self) -> None:
        """Acquire the device. Raise if it cannot be had — the source contains it."""
        ...

    def read(self) -> object | None:
        """One frame, or ``None`` when this attempt produced none.

        ``None`` is the ordinary dropped-frame path and is not a failure: a camera
        that occasionally misses is normal, and treating it as fatal would make the
        source die on a laptop that suspends for a moment. Raise only when the
        device itself has gone.
        """
        ...

    def close(self) -> None:
        """Release the device. Called at most once per :meth:`open`."""
        ...


@runtime_checkable
class FrameProcessor(Protocol):
    """Frame in, derived signals out — the model half of the source.

    One instance per camera open, so an implementation may hold a model handle. It
    must not keep the frame it was handed, and it must not put frame content into
    an exception message: the source reports that message, and it is the one route
    by which pixels could reach a log.
    """

    @property
    def name(self) -> str:
        """Which backend this is (``"mediapipe"``), for status and diagnostics."""
        ...

    def process(self, frame: object, timestamp_s: float) -> PerceptionSample | None:
        """Derive a sample from *frame*, or ``None`` when nothing was derived.

        ``timestamp_s`` is the source's monotonic reading for this observation and
        belongs on every signal in the sample, so the channels of one frame share
        one clock. ``None`` means "no face this time" and must not be a recycled
        previous answer — the source does not restamp, so a replayed sample would
        read as fresh forever.
        """
        ...

    def close(self) -> None:
        """Release the model. Called at most once per instance."""
        ...


@runtime_checkable
class Worker(Protocol):
    """The already-started driver of the capture loop — a ``threading.Thread`` fits.

    Injected so the lifecycle can be tested without a thread: a fake records the
    loop body and the test pumps it by hand, which is what keeps these tests
    deterministic in a suite this size.
    """

    def join(self, timeout: float | None = None) -> None:
        """Wait for the loop to finish, at most *timeout* seconds."""
        ...

    def is_alive(self) -> bool:
        """Whether the loop is still running."""
        ...


#: Start the capture loop and return a handle on it. The callable is invoked with
#: the loop body and a thread name, and must return a worker that is *already
#: running* — so a fake that never runs the body is a legal, silent driver.
Spawn = Callable[[Callable[[], None], str], Worker]


class SourceState(str, Enum):
    """What the source is doing, in the four states a reader can actually observe."""

    #: Nothing is open. The shipped state, and the state after the last release.
    DORMANT = "dormant"
    #: The first consumer has asked and the camera is being opened -- a USB camera
    #: waking, a permission dialog, a first-run model fetch. Consumers hold leases and
    #: get no samples yet; this is what keeps ``status()`` answering instead of waiting.
    STARTING = "starting"
    #: Camera and model are open and the loop is observing.
    RUNNING = "running"
    #: Sensing stopped on a contained failure; :attr:`PerceptionStatus.failure_reason`
    #: says why. Consumers still hold leases; nothing retries under them.
    FAILED = "failed"


@dataclass(frozen=True)
class PerceptionStatus:
    """The source described in derived facts, for ``doctor`` and daemon status.

    Everything here is state, count, name or age — never a landmark, a score or a
    frame (ADR-v2-145 observability rules, and the spec's "no biometric detail").
    """

    #: What the source is doing.
    state: SourceState
    #: The processor's name while something is open, else ``""``.
    backend: str
    #: Names of the consumers currently holding a lease, sorted.
    consumers: tuple[str, ...]
    #: How many times the physical camera has been opened in this source's life.
    #: The ADR's hard architectural gate is that this stays at 1 for N consumers.
    opens: int
    #: Which channels the newest sample carries, e.g. ``("gaze",)``.
    channels: tuple[str, ...]
    #: Seconds since the newest observation, or ``None`` when there is none.
    last_sample_age_s: float | None
    #: Why sensing stopped, or ``""``.
    failure_reason: str
    #: Which ``FAILURE_*`` kind :attr:`failure_reason` is, or ``""`` with no failure.
    #: Defaulted, so a status built by an older caller still constructs.
    failure_kind: str = ""


class PerceptionLease:
    """One consumer's handle on the shared camera — its ``FacePerceptionSource``.

    A lease exists so that "the last consumer closes the camera" can be *counted*.
    Identity does the counting: the source holds a set of the leases that are up,
    so a consumer calling :meth:`start` twice takes one lease and calling
    :meth:`stop` twice releases one, without either being a special case.

    :meth:`latest` reads nothing once the lease is down, even while another
    consumer keeps the camera open. A feature the user switched off should not
    still be seeing faces, and making that the lease's answer means no consumer has
    to remember to stop asking.
    """

    __slots__ = ("_held", "_name", "_source")

    def __init__(self, source: SharedPerceptionSource, name: str) -> None:
        self._source = source
        self._name = str(name)
        #: Owned by the lease, mutated only by the source under its lock, so that
        #: taking the lease and counting it are one atomic step.
        self._held = False

    def __repr__(self) -> str:
        return f"PerceptionLease({self._name!r}, held={self._held})"

    @property
    def name(self) -> str:
        """Who this lease belongs to — appears in status, never in a signal."""
        return self._name

    @property
    def active(self) -> bool:
        """Whether this consumer currently holds the source open."""
        return self._held

    def start(self) -> None:
        """Take the lease, opening the camera if this is the first one.

        Never raises: a camera that cannot be opened leaves the source
        :data:`SourceState.FAILED` with a reason, and the consumer simply gets no
        samples.
        """
        self._source._acquire(self)

    def stop(self) -> None:
        """Release the lease; the last one out closes the camera."""
        self._source._release(self)

    def latest(self) -> PerceptionSample | None:
        """The newest observation, or ``None`` when there is none or the lease is down."""
        return self._source.latest() if self._held else None

    def __enter__(self) -> PerceptionLease:
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()


class SharedPerceptionSource:
    """The one camera owner. Build it once per daemon; hand out leases.

    Both heavy halves are injected, which is what keeps this file free of OpenCV,
    MediaPipe and any thread the tests cannot see: ``capture_factory`` builds an
    unopened camera and ``processor_factory`` the model that derives signals from
    its frames, once per open.

    ``spawn`` drives the capture loop and defaults to a daemon thread. A caller
    that would rather pump the source itself — a burst-oriented consumer, or a test
    — passes a spawn that does not run the body and calls :meth:`observe`.

    The owner is deliberately **not** itself a ``FacePerceptionSource``: it has no
    ``start``/``stop``, because an anonymous lease on the shared object is exactly
    the bookkeeping that cannot answer "was that the last consumer?". A consumer
    asks for :meth:`consumer` and gets a :class:`PerceptionLease`, which is the
    Protocol ``src/yazses/perception/signals.py`` declares.
    """

    def __init__(
        self,
        capture_factory: Callable[[], FrameCapture],
        processor_factory: Callable[[], FrameProcessor],
        *,
        interval_s: float = 1.0 / 15.0,
        clock: Callable[[], float] = time.monotonic,
        spawn: Spawn | None = None,
        join_timeout_s: float = 2.0,
    ) -> None:
        self._capture_factory = capture_factory
        self._processor_factory = processor_factory
        self._interval_s = max(0.0, float(interval_s))
        self._clock = clock
        self._spawn: Spawn = spawn if spawn is not None else _spawn_thread
        self._join_timeout_s = max(0.0, float(join_timeout_s))
        # Guards the lease set, the state and the installed devices. It is held for field
        # updates only -- never across a camera read (see `observe`) or a camera open --
        # so a slow frame or a pending permission dialog cannot block a consumer that is
        # only asking what is going on.
        self._lock = threading.RLock()
        # Serialises the slow transitions: opening devices, and closing the ones a
        # finished session left behind. Reentrant because a failure inside an open drains
        # too. See the note above `_acquire`.
        self._lifecycle = threading.RLock()
        self._loop = threading.local()
        self._retired: list[tuple[Worker | None, FrameCapture | None, FrameProcessor | None]] = []
        self._leases: set[PerceptionLease] = set()
        self._capture: FrameCapture | None = None
        self._processor: FrameProcessor | None = None
        self._worker: Worker | None = None
        self._stopping = threading.Event()
        # Bumped on every open and every teardown, so an observation that was in
        # flight when the camera closed can recognise that its sample is stale
        # instead of publishing it into a source that is dormant.
        self._epoch = 0
        self._opens = 0
        self._state = SourceState.DORMANT
        self._failure = ""
        self._failure_kind = ""
        self._backend = ""
        self._sample: PerceptionSample | None = None

    # -- consumers ---------------------------------------------------------- #

    def consumer(self, name: str) -> PerceptionLease:
        """A lease for *name*. Taking it is what opens the camera, not this call."""
        return PerceptionLease(self, name)

    def latest(self) -> PerceptionSample | None:
        """The newest observation, or ``None``.

        No lock: the value is immutable and reading one attribute is atomic, while
        taking the lock here would put every consumer behind whatever the camera is
        doing — which is the one thing the spec's "read must not block" rules out.
        """
        return self._sample

    def status(self) -> PerceptionStatus:
        """Derived facts about the source, for ``doctor`` and daemon status."""
        with self._lock:
            sample = self._sample
            return PerceptionStatus(
                state=self._state,
                backend=self._backend,
                consumers=tuple(sorted(lease.name for lease in self._leases)),
                opens=self._opens,
                channels=() if sample is None else sample.channels,
                last_sample_age_s=None if sample is None else sample.age_s(self._clock()),
                failure_reason=self._failure,
                failure_kind=self._failure_kind,
            )

    @property
    def interval_s(self) -> float:
        """Seconds the loop waits between observations (the configured frame rate)."""
        return self._interval_s

    # -- one observation ---------------------------------------------------- #

    def observe(self) -> bool:
        """Take one observation; ``True`` when a new sample was published.

        This is the whole body of the capture loop, exposed because a caller may
        prefer to drive the source itself. The camera read and the derivation
        happen *outside* the lock: holding it there would mean a consumer asking
        for status, or a shutdown, waits on a webcam.
        """
        # The capture loop publishes the session it was started for in a thread-local, so
        # that this stays the one entry point the loop and a hand-driven caller share. A
        # loop that outlived its session -- a slow thread start, a read still in flight at
        # release -- must not adopt the next session's devices, or the "one reader" the
        # source promises becomes two. A caller that drives the source itself has no
        # session of its own and observes whichever is open.
        only_epoch: int | None = getattr(self._loop, "epoch", None)
        with self._lock:
            capture = self._capture
            processor = self._processor
            epoch = self._epoch
            if capture is None or processor is None or self._state is not SourceState.RUNNING:
                return False
            if only_epoch is not None and epoch != only_epoch:
                return False

        try:
            frame = capture.read()
        except Exception as exc:
            self._fail(
                f"reading from the camera failed ({_reason(exc)})", epoch, FAILURE_CAMERA
            )
            return False
        if frame is None:
            # A dropped frame is not a failure, and nothing is restamped for it.
            return False
        try:
            sample = processor.process(frame, self._clock())
        except Exception as exc:
            self._fail(
                f"deriving signals from the camera failed ({_reason(exc)})",
                epoch,
                FAILURE_PROCESSING,
            )
            return False
        finally:
            # The frame's only reference leaves scope here, always (ADR-011).
            del frame

        if sample is None:
            return False
        with self._lock:
            if epoch != self._epoch:
                # The camera closed under this observation. Its sample describes a
                # device that is no longer open, so it is dropped rather than
                # published into a dormant source.
                return False
            current = self._sample
            if current is not None and sample.timestamp_s < current.timestamp_s:
                # Time does not run backwards for a consumer: an observation that
                # finished late (a second driver, a slow derivation) must not replace a
                # newer one, or "latest" would age *down* and a stale face would read
                # as fresher than it is.
                return False
            self._sample = sample
        return True

    # -- shutdown ----------------------------------------------------------- #

    def close(self) -> None:
        """Release every lease and close the camera, whatever the bookkeeping says.

        The process-shutdown path: a consumer that forgot to stop must not be able
        to leave a camera open or a thread alive. Idempotent, and the source is
        reusable afterwards -- it returns to :data:`SourceState.DORMANT` rather than
        becoming poisoned, so a feature switched off and on again works.

        Never waits on a camera that is still *opening*: an open that is blocked on a
        permission dialog is cancelled, and the device it eventually returns is closed
        by the opener, not installed.
        """
        with self._lock:
            for lease in tuple(self._leases):
                lease._held = False
            self._leases.clear()
            self._retire_locked()
        self._drain()

    # -- internals ---------------------------------------------------------- #
    #
    # Two locks, deliberately. ``_lock`` guards the bookkeeping (leases, state, the
    # installed devices, the epoch) and is held only for field updates, never across
    # anything that can block on hardware or the network -- ``status()`` is called by
    # the daemon's status request and by ``doctor``, and must answer while a camera is
    # mid-open. ``_lifecycle`` serialises the slow part: building and opening devices,
    # and joining and closing the ones a finished session left behind. Draining the
    # left-behind devices *before* any new open is what keeps a quick stop-then-start
    # from ever having two handles on one webcam.

    def _acquire(self, lease: PerceptionLease) -> None:
        """Take *lease*, opening the camera on the transition from zero to one."""
        with self._lock:
            if lease._held:
                return
            lease._held = True
            self._leases.add(lease)
            if len(self._leases) > 1 or self._state is not SourceState.DORMANT:
                # Already open, opening, or failed: sharing one observation is the
                # entire point, and a retry loop against a camera that just refused is
                # worse than no camera, so failure is never cleared by a new consumer.
                return
            self._epoch += 1
            token = self._epoch
            self._state = SourceState.STARTING
        self._open(token)

    def _release(self, lease: PerceptionLease) -> None:
        """Release *lease*, closing the camera when it was the last one."""
        with self._lock:
            lease._held = False
            if lease not in self._leases:
                return
            self._leases.discard(lease)
            if self._leases:
                return
            self._retire_locked()
        # Outside the lock: the worker may be inside `observe`, which needs it to
        # publish, and joining while holding it would deadlock the pair.
        self._drain()

    def _open(self, token: int) -> None:
        """Build and open the camera and the model. The one place that does.

        *token* is the epoch this open was started for. If it is no longer current when
        a step finishes, the last consumer left (or the process is closing) while the
        device was opening: whatever was built is closed and nothing is installed.
        """
        with self._lifecycle:
            self._drain_locked()
            if not self._current(token):
                return
            capture: FrameCapture | None = None
            processor: FrameProcessor | None = None
            backend = ""
            failure = ""
            kind = ""
            # Two attempts, not one: the camera and the model fail for different reasons
            # with different fixes, and one `except` around both reported a face model
            # that could not be downloaded as a camera that could not be opened.
            try:
                capture = self._capture_factory()
                capture.open()
            except Exception as exc:
                kind, failure = describe_open_failure("camera", exc)
            if not failure and self._current(token):
                try:
                    processor = self._processor_factory()
                    backend = processor.name
                except Exception as exc:
                    kind, failure = describe_open_failure("model", exc)

            stopping = threading.Event()
            installed = False
            with self._lock:
                if token != self._epoch:
                    failure = ""  # nobody is left to be told
                elif not failure and capture is not None and processor is not None:
                    self._capture = capture
                    self._processor = processor
                    self._backend = backend
                    self._opens += 1
                    self._sample = None
                    self._failure = ""
                    self._failure_kind = ""
                    self._state = SourceState.RUNNING
                    # A fresh event per open: reusing one that has already been set
                    # would make the new loop exit immediately, and it would look like
                    # a dead camera.
                    self._stopping = stopping
                    installed = True
                else:
                    self._state = SourceState.FAILED
                    self._failure = failure
                    self._failure_kind = kind if failure else ""
            if not installed:
                # Failed, or cancelled while opening: close what was built, install nothing.
                _close_quietly(capture)
                _close_quietly(processor)
                if failure:
                    log.warning(
                        "Shared camera perception could not start: %s. The feature that "
                        "asked stays dormant; dictation is unaffected.",
                        failure,
                    )
                return

            try:
                # Bound to this open's epoch and event at spawn time, not looked up when
                # the thread gets going: a loop that starts after its session ended must
                # not pick up the next session's.
                worker = self._spawn(lambda: self._pump(token, stopping), "yazses-perception")
            except Exception as exc:
                self._fail(
                    f"the camera loop could not be started ({_reason(exc)})",
                    token,
                    FAILURE_PROCESSING,
                )
                return
            with self._lock:
                if token == self._epoch:
                    self._worker = worker
                    return
            # Cancelled between the install and the spawn: nobody owns this worker.
            stopping.set()
            self._join(worker)

    def _current(self, token: int) -> bool:
        with self._lock:
            return token == self._epoch

    def _retire_locked(self) -> None:
        """End the session: cancel anything in flight and set the devices aside to close.

        Cheap and non-blocking -- it only moves references. Joining the loop and closing
        the devices happens in :meth:`_drain`, outside the lock.
        """
        self._stopping.set()
        # Any observation or open in flight belongs to the epoch that just ended, and the
        # sample already published belongs to a camera that is now shut: a consumer
        # must not be able to act on a face seen before the device closed.
        self._epoch += 1
        self._sample = None
        retired = (self._worker, self._capture, self._processor)
        self._worker = None
        self._capture = None
        self._processor = None
        if any(item is not None for item in retired):
            self._retired.append(retired)
        self._state = SourceState.DORMANT
        # Dormant means nothing is wrong and nothing is running. Keeping the last
        # reason here would let `doctor` report a failure that is over as a live one.
        self._failure = ""
        self._failure_kind = ""
        self._backend = ""

    def _drain(self) -> None:
        """Join and close what finished sessions left behind, without waiting on an open.

        If another thread is mid-open the devices stay queued: that thread drains them
        before it opens anything, and a shutdown must not wait on a permission dialog.
        """
        with self._lock:
            if not self._retired:
                return
        if not self._lifecycle.acquire(timeout=self._join_timeout_s):
            log.warning(
                "A camera is still being opened; the devices of the previous session "
                "will be closed as soon as that returns."
            )
            return
        try:
            self._drain_locked()
        finally:
            self._lifecycle.release()

    def _drain_locked(self) -> None:
        """The body of :meth:`_drain`; the caller holds ``_lifecycle``."""
        while True:
            with self._lock:
                if not self._retired:
                    return
                worker, capture, processor = self._retired.pop(0)
            # The loop first, then the devices it reads: releasing a capture under a
            # thread that is mid-read is undefined in the camera libraries.
            self._join(worker)
            _close_quietly(capture)
            _close_quietly(processor)

    def _fail(self, reason: str, epoch: int, kind: str = FAILURE_PROCESSING) -> None:
        """Contain a failure: stop sensing, remember why, leave the daemon alone.

        *epoch* is the session that observed it. A failure from a session that has
        already ended -- a read that raised because its own release closed the device
        under it -- says nothing about the session that replaced it, and is dropped.

        Never joins the worker -- it is usually the worker itself calling this, and
        a thread cannot wait for itself. The loop sees the state change and ends;
        the join belongs to whoever releases the last lease.
        """
        with self._lock:
            if epoch != self._epoch or self._state is not SourceState.RUNNING:
                return
            self._state = SourceState.FAILED
            self._failure = reason
            self._failure_kind = kind
            self._stopping.set()
            self._epoch += 1
            self._sample = None
            self._retired.append((None, self._capture, self._processor))
            self._capture = None
            self._processor = None
        log.warning(
            "Shared camera perception stopped: %s. Camera features that were using "
            "it get no further samples; dictation is unaffected.",
            reason,
        )
        self._drain()

    def _join(self, worker: Worker | None) -> None:
        if worker is None:
            return
        worker.join(self._join_timeout_s)
        if worker.is_alive():
            log.warning(
                "The shared camera loop did not stop within %.1fs. It holds no lease "
                "and the device is closed, but the thread is still winding down.",
                self._join_timeout_s,
            )

    def _pump(self, epoch: int, stopping: threading.Event) -> None:
        """The capture loop: observe, pace, repeat, until stopped or failed."""
        self._loop.epoch = epoch
        while not stopping.is_set():
            self.observe()
            with self._lock:
                if self._state is not SourceState.RUNNING or self._epoch != epoch:
                    return
            stopping.wait(self._interval_s)


def _spawn_thread(target: Callable[[], None], name: str) -> Worker:
    """Run the capture loop on a daemon thread — the default driver.

    Daemon because a camera loop must never be the reason the process refuses to
    exit; the lifecycle above closes it properly on every ordinary path, and this
    is the backstop for the ones that are not ordinary.
    """
    thread = threading.Thread(target=target, name=name, daemon=True)
    thread.start()
    return thread


def _close_quietly(thing: object) -> None:
    """Close what we opened, without letting a second failure hide the first."""
    close = getattr(thing, "close", None)
    if close is None:
        return
    try:
        close()
    except Exception as exc:
        log.debug("Closing %s raised %s", type(thing).__name__, type(exc).__name__)


def describe_open_failure(stage: str, exc: BaseException) -> tuple[str, str]:
    """``(kind, reason)`` for an exception raised while opening a session. Pure.

    *stage* is ``"camera"`` (building or opening the capture) or ``"model"`` (building the
    processor, which is where the face model is fetched and loaded). An ``ImportError`` is
    a missing dependency whichever stage raised it, and the reason names the module rather
    than the stage -- "mediapipe is not installed" is the sentence with a fix in it. The
    camera wording is unchanged from before the split, because `status`, `doctor` and the
    controls window already print it and tests hold them to agreeing.
    """
    if isinstance(exc, ImportError):
        module = (getattr(exc, "name", "") or "").split(".")[0]
        what = f"{module} is not installed" if module else "a camera dependency is not installed"
        return FAILURE_DEPENDENCY, f"{what} ({_reason(exc)})"
    if stage == "model":
        return (
            FAILURE_MODEL,
            f"the camera opened, but the face model could not be fetched or loaded "
            f"({_reason(exc)})",
        )
    return FAILURE_CAMERA, f"the camera could not be opened ({_reason(exc)})"


def _reason(exc: BaseException) -> str:
    """An exception as a short, bounded sentence for a status line or a log.

    The type name leads because it is the part that is always safe and often the
    most useful ("device busy" reads as ``OSError``). The message is truncated: a
    camera error is a sentence, and an unbounded one is a channel.
    """
    message = str(exc).strip().replace("\n", " ")
    if not message:
        return type(exc).__name__
    return f"{type(exc).__name__}: {message[:_MAX_REASON]}"
