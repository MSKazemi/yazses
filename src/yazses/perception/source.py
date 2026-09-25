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
sketches, three are materialised: a ``STARTING``/``STOPPING`` that only exists
while a lock is held is a state no reader can ever observe, and ``DEGRADED`` would
need to know which channels *this* install expects, which is knowledge that
arrives with the MediaPipe adapter (#395). Per-channel degradation is visible
today where it is actually decided — on the sample, as ``channels``.
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
    "FrameCapture",
    "FrameProcessor",
    "PerceptionLease",
    "PerceptionStatus",
    "SharedPerceptionSource",
    "SourceState",
    "Worker",
]

log = logging.getLogger(__name__)

#: Longest a failure reason may be. A camera error is a sentence, not a payload,
#: and an unbounded one is a place for something unintended to travel.
_MAX_REASON = 200


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
    """What the source is doing, in the three states a reader can actually observe."""

    #: Nothing is open. The shipped state, and the state after the last release.
    DORMANT = "dormant"
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
        # Guards the lease set, the state and the open/close transitions. It is
        # deliberately NOT held across a camera read (see `observe`), so a slow
        # frame cannot block a consumer that is only asking what is going on.
        self._lock = threading.RLock()
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
        with self._lock:
            capture = self._capture
            processor = self._processor
            epoch = self._epoch
            if capture is None or processor is None or self._state is not SourceState.RUNNING:
                return False

        try:
            frame = capture.read()
        except Exception as exc:
            self._fail(f"reading from the camera failed ({_reason(exc)})")
            return False
        if frame is None:
            # A dropped frame is not a failure, and nothing is restamped for it.
            return False
        try:
            sample = processor.process(frame, self._clock())
        except Exception as exc:
            self._fail(f"deriving signals from the camera failed ({_reason(exc)})")
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
            self._sample = sample
        return True

    # -- shutdown ----------------------------------------------------------- #

    def close(self) -> None:
        """Release every lease and close the camera, whatever the bookkeeping says.

        The process-shutdown path: a consumer that forgot to stop must not be able
        to leave a camera open or a thread alive. Idempotent, and the source is
        reusable afterwards — it returns to :data:`SourceState.DORMANT` rather than
        becoming poisoned, so a feature switched off and on again works.
        """
        with self._lock:
            for lease in tuple(self._leases):
                lease._held = False
            self._leases.clear()
            worker = self._begin_stop_locked()
        self._join(worker)

    # -- internals ---------------------------------------------------------- #

    def _acquire(self, lease: PerceptionLease) -> None:
        """Take *lease*, opening the camera on the transition from zero to one."""
        with self._lock:
            if lease._held:
                return
            lease._held = True
            self._leases.add(lease)
            if len(self._leases) > 1:
                # Already open (or already failed): sharing one observation is the
                # entire point, so there is nothing to do.
                return
            if self._state is SourceState.FAILED:
                # Unreachable while releasing to zero resets the state, and kept
                # anyway: a retry loop against a camera that just refused is worse
                # than no camera, so failure is never cleared by a new consumer.
                return
            self._open_locked()

    def _release(self, lease: PerceptionLease) -> None:
        """Release *lease*, closing the camera when it was the last one."""
        with self._lock:
            lease._held = False
            if lease not in self._leases:
                return
            self._leases.discard(lease)
            if self._leases:
                return
            worker = self._begin_stop_locked()
        # Outside the lock: the worker may be inside `observe`, which needs it to
        # publish, and joining while holding it would deadlock the pair.
        self._join(worker)

    def _open_locked(self) -> None:
        """Build and open the camera and the model. The one place that does."""
        capture: FrameCapture | None = None
        processor: FrameProcessor | None = None
        try:
            capture = self._capture_factory()
            capture.open()
            processor = self._processor_factory()
            backend = processor.name
        except Exception as exc:
            _close_quietly(capture)
            _close_quietly(processor)
            self._state = SourceState.FAILED
            self._failure = f"the camera could not be opened ({_reason(exc)})"
            log.warning(
                "Shared camera perception is enabled but %s. The feature that asked "
                "stays dormant; dictation is unaffected.",
                self._failure,
            )
            return

        self._capture = capture
        self._processor = processor
        self._backend = backend
        self._opens += 1
        self._epoch += 1
        self._sample = None
        self._failure = ""
        self._state = SourceState.RUNNING
        # A fresh event per open: reusing one that has already been set would make
        # the new loop exit immediately, and it would look like a dead camera.
        self._stopping = threading.Event()
        try:
            self._worker = self._spawn(self._pump, "yazses-perception")
        except Exception as exc:
            self._worker = None
            self._fail(f"the camera loop could not be started ({_reason(exc)})")

    def _begin_stop_locked(self) -> Worker | None:
        """Stop sensing and close the devices; return the worker left to join."""
        worker, self._worker = self._worker, None
        self._stopping.set()
        self._teardown_devices_locked()
        self._state = SourceState.DORMANT
        # Dormant means nothing is wrong and nothing is running. Keeping the last
        # reason here would let `doctor` report a failure that is over as a live one.
        self._failure = ""
        self._backend = ""
        return worker

    def _teardown_devices_locked(self) -> None:
        capture, processor = self._capture, self._processor
        self._capture = None
        self._processor = None
        # Any observation in flight belongs to the epoch that just ended, and the
        # sample already published belongs to a camera that is now shut: a consumer
        # must not be able to act on a face seen before the device closed.
        self._epoch += 1
        self._sample = None
        _close_quietly(capture)
        _close_quietly(processor)

    def _fail(self, reason: str) -> None:
        """Contain a failure: stop sensing, remember why, leave the daemon alone.

        Never joins the worker — it is usually the worker itself calling this, and
        a thread cannot wait for itself. The loop sees the state change and ends;
        the join belongs to whoever releases the last lease.
        """
        with self._lock:
            if self._state is not SourceState.RUNNING:
                return
            self._state = SourceState.FAILED
            self._failure = reason
            self._stopping.set()
            self._teardown_devices_locked()
        log.warning(
            "Shared camera perception stopped: %s. Camera features that were using "
            "it get no further samples; dictation is unaffected.",
            reason,
        )

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

    def _pump(self) -> None:
        """The capture loop: observe, pace, repeat, until stopped or failed."""
        # Bound to this open's event on purpose: a later re-open installs a new one,
        # and a loop watching that would never notice its own shutdown.
        stopping = self._stopping
        while not stopping.is_set():
            self.observe()
            if self._state is not SourceState.RUNNING:
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
