"""The Head-Pointer runtime state machine: pose in, pointer intent out (ADR-v2-052, #404/#405).

This is the piece that makes ``pose_to_cursor`` and ``DwellClicker`` reachable. It owns no
camera, no thread, no platform call and no clock of its own: a head-pose sample and the current
monotonic time go in through :meth:`HeadPointerController.update`, and ``PointerSink`` calls come
out. Everything it needs from the outside (the sink, the global safety gate, dwell feedback) is
injected, so a whole session -- including the failures -- is a list of numbers in a unit test.

The pipeline is the one in ``design/specs/eye-head-pointer-runtime.md``::

    sample -> freshness/quality -> global gate -> pause/clutch -> neutral transform
           -> pose_to_cursor -> speed caps -> x dt -> sub-unit accumulator -> PointerSink.move_relative
    pointer position -> DwellClicker -> progress feedback -> PointerSink.click

**The failure this module exists to prevent is a pointer that moves or clicks when the user did
not ask it to.** Every rule below is a version of that, and each has a test that fails when the
rule is removed:

* *Signal loss freezes the pointer; it never repeats the last delta.* A missing, stale or
  low-confidence sample produces zero motion. A sample is acted on **once**: the runner polls
  faster than the camera delivers, and re-reading the same observation must not move the pointer
  a second time.
* *Nothing clicks on the way in.* After startup, recentering, a pause, a clutch, a fault, a
  global-gate suppression or a signal loss, the very next sample is consumed as a settling
  frame (no motion), and the dwell detector stays **disarmed** until the pointer has actually
  travelled beyond the dwell radius. Without that last rule a user who merely sits still after
  enabling the feature would be clicked at: the dwell detector times stillness, and a
  freshly started pointer is perfectly still.
* *One click, then the user must move.* The same rule is why a click is followed by a disarmed
  detector rather than an instantly re-armed one: resting the head would otherwise click every
  ``dwell_hold_s`` for as long as the user stayed put.
* *The global hands-free state wins.* When a ``HandsFreeSafety`` gate is supplied, a denied
  decision zeroes motion and clicks, and its one-shot ``clear_pending`` latch drops the
  half-built dwell and the sub-unit remainder (ADR-v2-148, R-05/R-06/R-24).
* *An unanswered permission dialog is not a fault.* A sink with a consent step (the Wayland
  RemoteDesktop portal) reports where it stands (``pointer/consent.py``). While the user has
  not answered, the controller does not try to move: it rests in ``pending_consent`` -- no
  fault, nothing told to the global gate -- and starts by itself, through a settling frame,
  the moment the desktop grants the pointer. A refusal is ``denied`` and a compositor with no
  pointer to give is ``unavailable``; both are words, not a silence and not a generic fault.
* *A failed sink stops the feature, not the daemon.* A ``PointerSink`` that raises faults the
  controller and reports it to the gate; nothing is retried, and the failed step's motion is
  spent rather than replayed (ADR-v2-146 rule 4). Only an explicit :meth:`resume` clears it.

**Sub-unit motion is accumulated here, because the backends disagree.** macOS and Windows carry
a fractional remainder inside their sinks; X11 rounds each call and carries nothing, so a slow
head movement under half a device unit per frame would move one platform's pointer and not
another's. The controller therefore accumulates in a :class:`~yazses.pointer.subpixel.
SubPixelAccumulator` and hands the sink **whole** units, which every backend treats identically.

**Dwell position is a virtual one.** ``PointerSink`` is write-only -- there is no "where is the
pointer" -- so the dwell detector watches the running sum of the whole units this controller
has itself sent. That is the pointer's displacement, not its screen coordinate: a pointer pinned
at a screen edge keeps accumulating, which makes dwell *less* likely to fire there, never more.

**The motion model is rate control in real time, independent of the camera's frame rate.** The
head's offset from neutral sets a *velocity* (``PointerCalib`` gains are pointer units per
**second** per radian), that velocity is capped per axis and overall (units per second), and a
sample moves the pointer by ``velocity x dt``, where ``dt`` is the real time since the previous
accepted sample, clamped to ``max_dt_s``. So the same head motion moves the pointer the same
distance on a 15, 30 or 60 fps camera, a long gap (a stalled thread, a camera hiccup) becomes
at most one bounded step rather than a leap, and no pose however extreme can exceed the cap.
A zero, negative or non-finite ``dt`` is no motion. The sub-unit remainder is carried across
samples exactly as before.

**No defaults are declared from synthetic data.** The gains, speed caps, dead zone, dwell
radius and hold length are provisional first-principles values; the freshness window and
confidence floor are placeholders to be replaced by measurement (``GOVERNANCE.md``). The
*sign* of the horizontal gain is geometry, observed on a real camera (2026-10-13): a negative
gain flips an axis.

**A clutch can take back the step that raced it.** A facial expression that disturbs the head is
seen by a *different* runner than the one that moves the pointer, so the pointer can follow the
first disturbed frame before the clutch lands. ``set_clutch(..., since_s=t)`` therefore also sends
one opposite ``move_relative`` for whole units *this controller* sent for samples at or after
``t`` (and no further back than ``REWIND_LIMIT_S``). ``PointerSink`` is write-only, so this is
arithmetic on its own record, not a read of the screen: a pointer pinned at a screen edge during
that step is moved back by the unclamped amount. It does nothing when the controller is paused,
faulted, closed or has not moved, and it never clicks.

**Dwell is in real time too.** The hold is ``dwell_hold_s`` seconds: the sum of the real gaps
between accepted samples that stayed inside the dwell radius (``DwellClicker`` takes each
sample's timestamp), so a 15 and a 30 fps camera click after the same wait. A gap longer than
``max_dt_s`` (a stall that never went stale) is unobserved stillness and restarts the dwell
rather than counting towards it. ``dwell_hold_frames`` is the legacy spelling: when set it is
read as that many frames at a nominal 30 fps (:func:`effective_dwell_s`). The 700 ms default
is provisional -- roughly the old 20-frame default at 30 fps, not a measurement.

**A click is never the first the user hears of a dwell.** Progress is published on the first
sample at which it is above zero (``DwellFeedback.show`` and ``status().dwell_progress``), and a
dwell that completes before any progress was published waits at the brink for one more sample
(``DwellClicker.update(..., may_fire=False)``), so a hold shorter than the gap between two
frames cannot click unannounced. Whether the user *sees* it then depends on the reader of that
progress -- the overlay polls ``status`` and speeds up while a dwell can be building
(``overlay/poller.py``).
"""
from __future__ import annotations

import logging
import math
import threading
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from yazses.handsfree.safety import HandsFreeSafety
from yazses.headpointer.pointer import (
    DEFAULT_MAX_DT_S,
    DwellClicker,
    PointerCalib,
    elapsed_s,
    limit_velocity,
    pose_to_cursor,
)
from yazses.perception.signals import HeadPoseSignal
from yazses.pointer.base import PointerButton, PointerSink
from yazses.pointer.consent import ConsentReport, PointerConsent, consent_of
from yazses.pointer.subpixel import SubPixelAccumulator

__all__ = [
    "DEFAULT_DWELL_S",
    "DEFAULT_FRESHNESS_S",
    "DEFAULT_MAX_DT_S",
    "DEFAULT_MIN_CONFIDENCE",
    "REWIND_LIMIT_S",
    "MAX_DWELL_S",
    "MAX_FRESHNESS_S",
    "MIN_DWELL_S",
    "SOURCE_NAME",
    "ClickContext",
    "ClickResult",
    "DwellFeedback",
    "HeadPointerController",
    "HeadPointerSettings",
    "HeadPointerStatus",
    "ResumeResult",
    "State",
    "Step",
    "effective_dwell_s",
    "effective_freshness_s",
]

log = logging.getLogger(__name__)

#: The name this feature goes by in the global safety gate (``handsfree/safety.py``).
SOURCE_NAME = "headpointer"

#: Oldest a head-pose sample may be and still move the pointer. **Not a measured value** -- the
#: same 500 ms placeholder ``SafetyLimits`` ships, for the same reason (no frame-interval or
#: tracking-loss distribution exists for this programme). It errs long on purpose: a false trip
#: costs a hands-free user their input method until they recover.
DEFAULT_FRESHNESS_S = 0.5

#: Longest freshness window that still means anything. Past a minute a head pose is "fresh"
#: for so long that the stale-signal guard is effectively off (and ``float(10**400)`` is an
#: ``OverflowError``). **Provisional:** a sanity bound, not a measured value. It is the same
#: bound ``[headpointer] freshness_ms`` declares in ``config.py``, which is what keeps the
#: value ``Config`` reports equal to the value this controller applies.
MAX_FRESHNESS_S = 60.0

#: How long the pointer must hold still before a dwell-click. **Provisional, unmeasured:**
#: about the old default of 20 frames at a 30 fps camera (667 ms), rounded. No study of how
#: long a person can comfortably hold their head still exists for this programme yet
#: (``design/eye-control/GOVERNANCE.md``).
DEFAULT_DWELL_S = 0.7

#: Shortest and longest dwell the controller will apply. The floor is a safety bound (a dwell
#: that short clicks on a head merely resting); both are provisional, and both are the bounds
#: ``[headpointer] dwell_ms`` declares in ``config.py``.
MIN_DWELL_S = 0.05
MAX_DWELL_S = 10.0

#: The camera rate a legacy ``dwell_hold_frames`` value is read at. Those values were counted
#: in samples, so their duration was whatever the camera made it; 30 fps is the nominal rate
#: the dev webcam ran at (26-30 fps measured informally), not a property of any camera.
LEGACY_FRAME_S = 1.0 / 30.0

#: Lowest sample confidence that may move the pointer. ``HeadPoseSignal.confidence`` is the
#: MediaPipe presence score and 0.5 is that backend's own default floor
#: (``perception.mediapipe_backend.DEFAULT_PRESENCE_CONFIDENCE``); a graded quality signal does
#: not exist yet.
DEFAULT_MIN_CONFIDENCE = 0.5

#: The furthest back (seconds before the newest accepted sample) a clutch may ask this controller
#: to undo its own motion. A safety bound, not a measurement: it is what keeps "undo the step the
#: gesture caused" from ever becoming "undo what the user was doing a second ago".
REWIND_LIMIT_S = 0.5


class State(str, Enum):
    """What the controller is doing, in the words status and ``doctor`` print."""

    #: Running, but no usable sample has been seen yet.
    WAITING = "waiting"
    #: Following the head.
    TRACKING = "tracking"
    #: The signal is missing, stale or untrusted; the pointer is still.
    LOST = "lost"
    #: Feature-level pause: no motion, no dwell, no click.
    PAUSED = "paused"
    #: A clutch input is holding the pointer still.
    CLUTCHED = "clutched"
    #: The global hands-free gate refused (paused, faulted, not armed, stale).
    SUPPRESSED = "suppressed"
    #: The pointer backend failed; cleared only by an explicit resume.
    FAULTED = "faulted"
    #: The desktop is asking the user for permission to move the pointer and they have not
    #: answered. Not a fault: nothing is wrong, and it clears itself on approval.
    PENDING_CONSENT = "pending_consent"
    #: The user declined the desktop's permission. Distinct from a backend that broke.
    DENIED = "denied"
    #: The desktop answered and has no pointer to give. Distinct from a refusal.
    UNAVAILABLE = "unavailable"
    #: Closed for good.
    CLOSED = "closed"


class DwellFeedback(Protocol):
    """Where the user sees a click coming. Injected; the overlay or tray implements it.

    Called only on a change, never per frame, and never allowed to break the pointer: the
    controller swallows anything it raises.
    """

    def show(self, progress: float) -> None:
        """A dwell is ``progress`` (0..1) of the way to firing."""
        ...

    def hide(self) -> None:
        """No dwell is in progress any more (it fired, was reset or was abandoned)."""
        ...


@dataclass(frozen=True)
class HeadPointerSettings:
    """Everything tunable, as plain numbers. Built from ``[headpointer]`` by the factory."""

    calib: PointerCalib = PointerCalib()
    #: Samples older than this (seconds) are treated as no signal. Anything outside
    #: ``(0, MAX_FRESHNESS_S]`` is repaired to the default (:func:`effective_freshness_s`).
    freshness_s: float = DEFAULT_FRESHNESS_S
    min_confidence: float = DEFAULT_MIN_CONFIDENCE
    #: Longest time step (seconds) one sample may move the pointer over; a longer gap is
    #: clamped to this, so a stall yields one bounded step. A safety bound, not a measurement.
    max_dt_s: float = DEFAULT_MAX_DT_S
    #: Dwell-click is its own switch: motion alone is a complete, useful feature.
    dwell_enabled: bool = False
    dwell_radius_px: float = 15.0
    #: Seconds the pointer must hold still before the click, on the samples' own clock.
    dwell_hold_s: float = DEFAULT_DWELL_S
    #: Legacy spelling of the hold, in samples. ``0`` = unset; when above zero it wins and is
    #: read as that many frames at a nominal 30 fps (:func:`effective_dwell_s`).
    dwell_hold_frames: int = 0


@dataclass(frozen=True)
class Step:
    """What one :meth:`HeadPointerController.update` did. Units are whole pointer units."""

    state: State
    dx: int = 0
    dy: int = 0
    clicked: bool = False
    reason: str = ""


@dataclass(frozen=True)
class HeadPointerStatus:
    """A privacy-safe snapshot: states, flags, ages -- never an angle, position or sample."""

    state: State
    reason: str
    paused: bool
    clutched: bool
    calibrated: bool
    sample_age_s: float | None
    dwell_enabled: bool
    dwell_armed: bool
    dwell_progress: float
    fault: str
    backend: str
    #: The sink's permission state (``PointerConsent`` value), or ``""`` for a sink that has
    #: no such concept. ``not_required`` is a sink saying nobody needs to be asked.
    consent: str = ""
    #: One sentence about it, e.g. what the user has to do. Never a position or an angle.
    consent_detail: str = ""


@dataclass(frozen=True)
class ClickContext:
    """What a commit click is judged on: flags and words, never a pose or a position.

    ``clutched`` already leaves out any clutch the caller named as its own, and
    ``gate_allowed`` is ``None`` when no hands-free gate exists (which is not a closed gate).
    ``state`` is the controller's last state word (``tracking``, ``lost``, ...). Satisfies
    :class:`yazses.facegesture.actions.ClickView` structurally; this package does not import it.
    """

    state: str
    paused: bool
    clutched: bool
    faulted: bool
    closed: bool
    gate_allowed: bool | None


@dataclass(frozen=True)
class ClickResult:
    """The outcome of :meth:`HeadPointerController.commit_click`."""

    ok: bool
    reason: str = ""


@dataclass(frozen=True)
class ResumeResult:
    """The outcome of :meth:`HeadPointerController.resume`."""

    ok: bool
    reason: str = ""


def effective_freshness_s(value: object) -> float:
    """The freshness window actually applied, in seconds. Pure.

    Zero or negative cannot express "how old is too old" -- applied literally, a window of 0
    calls every real sample stale, so the pointer never moves and nothing says why -- and a
    window past :data:`MAX_FRESHNESS_S` is "never stale". Either, like a non-number, is
    repaired to :data:`DEFAULT_FRESHNESS_S`: the same posture as the loader, which reports
    the repair (``configcheck.build_section``), so what ``Config`` shows is what runs.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return DEFAULT_FRESHNESS_S
    try:
        seconds = float(value)
    except OverflowError:
        return DEFAULT_FRESHNESS_S
    if math.isfinite(seconds) and 0.0 < seconds <= MAX_FRESHNESS_S:
        return seconds
    return DEFAULT_FRESHNESS_S


def effective_dwell_s(dwell_hold_s: object, legacy_hold_frames: object = 0) -> float:
    """The dwell hold actually applied, in seconds. Pure.

    A positive ``legacy_hold_frames`` (the old ``dwell_hold_frames`` key) wins and means that
    many frames at a nominal 30 fps -- so an old config keeps roughly the wait it had on the
    camera it was written for, and is no longer stretched or squeezed by the camera's rate.
    Otherwise ``dwell_hold_s`` is used. Anything outside ``[MIN_DWELL_S, MAX_DWELL_S]`` or not a
    finite number is repaired to :data:`DEFAULT_DWELL_S`, as the loader repairs it.
    """
    value: object = dwell_hold_s
    if (
        not isinstance(legacy_hold_frames, bool)
        and isinstance(legacy_hold_frames, (int, float))
        and legacy_hold_frames > 0
    ):
        value = legacy_hold_frames
        scale = LEGACY_FRAME_S
    else:
        scale = 1.0
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return DEFAULT_DWELL_S
    try:
        seconds = float(value) * scale
    except OverflowError:  # an int too large for a float
        return DEFAULT_DWELL_S
    if math.isfinite(seconds) and MIN_DWELL_S <= seconds <= MAX_DWELL_S:
        return seconds
    return DEFAULT_DWELL_S


def _finite_or(value: float, default: float) -> float:
    return value if isinstance(value, (int, float)) and math.isfinite(value) else default


def _positive_or(value: float, default: float, name: str) -> float:
    """A speed cap or time bound must be finite and above zero; anything else is the default.

    A cap cannot be switched off by a bad or zero value -- the safe reading of "no usable cap"
    is "the shipped cap", never "unlimited".
    """
    if isinstance(value, (int, float)) and math.isfinite(value) and value > 0.0:
        return float(value)
    log.warning("head-pointer: %s=%r is not a positive number; using %s", name, value, default)
    return default


class HeadPointerController:
    """Pose in, pointer intent out. Thread-safe: ``update`` runs on the runner thread while
    ``recenter``/``pause``/``resume``/``set_clutch`` arrive from IPC or a switch.

    ``safety`` is the optional global gate (``handsfree/safety.py``); ``None`` means the
    hands-free state is not in play and only this controller's own freshness and pause rules
    apply -- which is exactly the behaviour of an install that never opted in to it.
    """

    def __init__(
        self,
        sink: PointerSink,
        settings: HeadPointerSettings | None = None,
        *,
        safety: HandsFreeSafety | None = None,
        feedback: DwellFeedback | None = None,
        source_name: str = SOURCE_NAME,
        backend: str = "",
    ) -> None:
        self._sink = sink
        self._s = settings or HeadPointerSettings()
        self._safety = safety
        self._feedback = feedback
        self._source = source_name
        self._backend = backend or _backend_name(sink)
        self._lock = threading.RLock()

        calib = self._s.calib
        self._calib = PointerCalib(
            x_gain=_finite_or(calib.x_gain, PointerCalib.x_gain),
            y_gain=_finite_or(calib.y_gain, PointerCalib.y_gain),
            deadzone=max(0.0, _finite_or(calib.deadzone, PointerCalib.deadzone)),
            max_speed_x=_positive_or(calib.max_speed_x, PointerCalib.max_speed_x, "max_speed_x"),
            max_speed_y=_positive_or(calib.max_speed_y, PointerCalib.max_speed_y, "max_speed_y"),
            max_speed_overall=_positive_or(calib.max_speed_overall, PointerCalib.max_speed_overall, "max_speed_overall"),
        )
        self._max_dt = _positive_or(self._s.max_dt_s, DEFAULT_MAX_DT_S, "max_dt_s")
        self._freshness_s = effective_freshness_s(self._s.freshness_s)
        self._min_conf = _finite_or(self._s.min_confidence, DEFAULT_MIN_CONFIDENCE)
        self._radius = max(1.0, _finite_or(self._s.dwell_radius_px, 15.0))
        self._hold_s = effective_dwell_s(self._s.dwell_hold_s, self._s.dwell_hold_frames)

        self._acc = SubPixelAccumulator()
        self._clicker = DwellClicker(
            radius=self._radius, hold_s=self._hold_s, max_dt_s=self._max_dt
        )
        self._dwell_enabled = bool(self._s.dwell_enabled)

        self._neutral: tuple[float, float] | None = None
        self._recenter_pending = False
        self._paused = False
        self._clutches: set[str] = set()
        self._fault = ""
        self._closed = False
        self._settle = True  # the first sample after any interruption is only observed

        self._last_ts = -math.inf
        self._tracking = False
        self._pos = (0, 0)
        #: (sample timestamp, whole units x, y) of recent moves, newest last -- what a
        #: clutch with ``since_s`` may take back. Cleared by every quiesce.
        self._trail: deque[tuple[float, int, int]] = deque()
        self._dwell_armed = False
        self._dwell_origin = (0, 0)
        self._shown: float | None = None  # last progress pushed to feedback

        self._state = State.WAITING
        self._reason = ""
        self._age_s: float | None = None

    # ------------------------------------------------------------------ the hot path

    def update(self, sample: HeadPoseSignal | None, now_s: float) -> Step:
        """Advance one runner tick. ``now_s`` is the same monotonic clock as the sample's.

        Called every tick whether or not the camera produced anything new, because staleness
        is a fact about *now*: a dead camera produces no samples at all, and this is the call
        that notices.
        """
        with self._lock:
            if self._closed:
                return Step(State.CLOSED)
            valid = self._is_valid(sample, now_s)
            new = valid and sample is not None and sample.timestamp_s > self._last_ts
            self._age_s = None if sample is None else now_s - sample.timestamp_s

            decision = None
            if self._safety is not None:
                if new and sample is not None:
                    self._safety.sample(self._source, at_ms=sample.timestamp_s * 1000.0)
                decision = self._safety.gate(self._source, at_ms=now_s * 1000.0)
                if decision.clear_pending:
                    self._quiesce()

            # Permission comes before signal quality: with the dialog unanswered the pointer
            # cannot move whatever the camera sees, and that -- not "no sample" -- is what a
            # user needs to be told.
            blocked = self._consent_block()
            if blocked is not None:
                self._tracking = False
                return self._rest(*blocked)

            if not valid:
                return self._lost(sample)
            assert sample is not None
            if not new:
                # The same observation again: nothing new happened, so nothing is done.
                return Step(self._state, reason=self._reason)
            prev_ts = self._last_ts
            self._last_ts = sample.timestamp_s
            self._tracking = True

            if self._fault:
                return self._rest(State.FAULTED, self._fault)
            if decision is not None and not decision.allowed:
                return self._rest(State.SUPPRESSED, decision.reason)
            if self._paused:
                return self._rest(State.PAUSED, "paused")
            if self._clutches:
                return self._rest(State.CLUTCHED, "clutch held")

            if self._neutral is None or self._recenter_pending:
                self._neutral = (sample.yaw, sample.pitch)
                self._recenter_pending = False
                self._quiesce()
                self._settle = False  # the capture frame *is* the settling frame
                return self._set(State.TRACKING, "centred")
            if self._settle:
                self._settle = False
                return self._set(State.TRACKING, "settling")
            return self._follow(
                sample, elapsed_s(prev_ts, sample.timestamp_s, self._max_dt), sample.timestamp_s
            )

    # ------------------------------------------------------------------ controls

    def recenter(self) -> None:
        """Make the next valid pose the neutral one. No motion and no click while it happens.

        Callable without precise pointer use: it takes no argument and has no target.
        """
        with self._lock:
            self._recenter_pending = True
            self._quiesce()

    def pause(self) -> None:
        """Feature-level pause: no motion, no dwell accumulation, no click. Idempotent."""
        with self._lock:
            self._paused = True
            self._quiesce()
            self._set(State.PAUSED, "paused")

    def resume(self) -> ResumeResult:
        """Leave pause and any fault, and re-arm the global gate for this source.

        The only way out of a fault. The first sample after resuming is a settling frame, so
        resuming can never itself move or click. Refused (``ok=False``) when the global gate
        will not arm this source yet -- typically because no fresh sample has arrived -- with
        the gate's own reason, so the caller can say why and try again.
        """
        with self._lock:
            if self._closed:
                return ResumeResult(False, "closed")
            self._paused = False
            self._fault = ""
            self._quiesce()
            self._set(State.WAITING, "resumed")
            if self._safety is None:
                return ResumeResult(True)
            self._safety.clear_fault(self._source)
            result = self._safety.resume([self._source])
            if result.ok:
                return ResumeResult(True)
            return ResumeResult(False, result.reason or f"{self._source}: not ready to arm")

    def set_clutch(
        self,
        source: str,
        active: bool,
        *,
        since_s: float | None = None,
        max_rewind_s: float | None = None,
    ) -> None:
        """Hold (``active``) or release one named clutch. Motion is frozen while any is held.

        Several callers can clutch independently -- a face gesture, a switch, a key -- and the
        pointer stays frozen until every one of them has let go. Head-Pointer sees only that
        generic state, never why (spec: "consumes only a generic clutch state").

        ``since_s`` (a sample timestamp on the controller's clock) is the first frame the caller
        knows to have been disturbed: motion this controller sent for samples at or after it is
        taken back first, so a clutch that landed one frame late leaves the pointer where it
        was. ``max_rewind_s`` narrows that further (never past :data:`REWIND_LIMIT_S`); zero
        disables it. Releasing a clutch ignores both.
        """
        with self._lock:
            if active:
                if since_s is not None:
                    self._rewind(since_s, max_rewind_s)
                self._clutches.add(str(source))
                self._quiesce()
            else:
                if str(source) in self._clutches:
                    self._clutches.discard(str(source))
                    self._quiesce()

    def fail(self, reason: str) -> None:
        """Fault the controller from outside, e.g. when the runner loop itself breaks.

        Same effect as a sink failure: motion and clicks stop, the global gate is told, and
        only :meth:`resume` clears it.
        """
        with self._lock:
            if not self._closed:
                self._fail(reason[:200])

    def commit_click(
        self,
        policy: Callable[[ClickContext], str],
        *,
        own_clutches: Iterable[str] = (),
    ) -> ClickResult:
        """One left click where the pointer already is, if ``policy`` allows it. Never raises.

        The entry point for a *commit* from outside the dwell path (a face switch's ``select``).
        The context is built and ``policy`` is asked under the same lock the pose updates and
        ``pause`` take, so a pause cannot land between "allowed" and "clicked". A non-empty
        ``policy`` return is a refusal and nothing is sent. ``own_clutches`` names clutches the
        caller itself holds (the face switch freezes the pointer while its gesture is down) so
        they do not count against it; every other clutch does.

        The click goes through the same sink the pointer moves with, once, and is never
        retried: a sink failure faults the controller exactly as a failed dwell click does
        (only an explicit ``resume`` clears it). A successful click disarms dwell, so the two
        click paths cannot fire on one pause of the head.
        """
        own = {str(c) for c in own_clutches}
        with self._lock:
            gate_allowed: bool | None = None
            if self._safety is not None:
                try:
                    gate_allowed = bool(self._safety.gate(self._source).allowed)
                except Exception:
                    gate_allowed = False  # a gate that cannot answer does not say yes
            context = ClickContext(
                state=self._state.value,
                paused=self._paused,
                clutched=bool(self._clutches - own),
                faulted=bool(self._fault),
                closed=self._closed,
                gate_allowed=gate_allowed,
            )
            try:
                reason = policy(context)
            except Exception as exc:
                return ClickResult(False, f"could not decide ({type(exc).__name__})")
            if reason:
                return ClickResult(False, reason)
            # Disarm before the call, as the dwell path does: a failing sink is not retried.
            self._clicker.reset()
            self._dwell_armed = False
            self._dwell_origin = self._pos
            try:
                self._sink.click(PointerButton.LEFT)
            except Exception as exc:
                self._fail(_describe(exc))
                return ClickResult(False, "the pointer backend failed the click")
            return ClickResult(True)

    def set_dwell_enabled(self, enabled: bool) -> None:
        """Turn dwell-click on or off at runtime, independently of motion."""
        with self._lock:
            self._dwell_enabled = bool(enabled)
            # Dwell is its own switch: flipping it must not also hold the pointer for a frame.
            self._quiesce(settle=False)

    def close(self) -> None:
        """Stop for good and release the sink. Idempotent; never raises."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._quiesce()
            self._state = State.CLOSED
            try:
                self._sink.close()
            except Exception:
                log.debug("head-pointer: closing the pointer sink raised", exc_info=True)

    # ------------------------------------------------------------------ observation

    def status(self) -> HeadPointerStatus:
        """Privacy-safe health for ``yazses headpointer status`` and the daemon."""
        with self._lock:
            consent = consent_of(self._sink)
            return HeadPointerStatus(
                state=self._state,
                reason=self._reason,
                paused=self._paused,
                clutched=bool(self._clutches),
                calibrated=self._neutral is not None and not self._recenter_pending,
                sample_age_s=self._age_s,
                dwell_enabled=self._dwell_enabled,
                dwell_armed=self._dwell_enabled and self._dwell_armed,
                dwell_progress=self._progress(),
                fault=self._fault,
                backend=self._backend,
                consent="" if consent is None else consent.state.value,
                consent_detail="" if consent is None else consent.detail,
            )

    # ------------------------------------------------------------------ internals

    def _is_valid(self, sample: HeadPoseSignal | None, now_s: float) -> bool:
        """Fresh, confident, and on a sane clock. Anything doubtful is *no signal*."""
        if sample is None or not math.isfinite(now_s):
            return False
        age = now_s - sample.timestamp_s
        if age < 0.0 or age > self._freshness_s:
            return False  # a sample from the future is a clock fault, not a fresh pose
        return sample.confidence >= self._min_conf

    def _consent_block(self) -> tuple[State, str] | None:
        """The state to rest in while the platform has not allowed the pointer, or ``None``.

        ``None`` for a sink with no consent step, for one that says nobody needs asking, for
        a granted one -- and for ``UNKNOWN``, which must not be read as a refusal: the sink
        is then tried, and a real failure still faults it honestly.
        """
        report: ConsentReport | None = consent_of(self._sink)
        if report is None:
            return None
        if report.state is PointerConsent.PENDING:
            return State.PENDING_CONSENT, report.detail or "waiting for the desktop's permission"
        if report.state is PointerConsent.DENIED:
            return State.DENIED, report.detail or "the desktop's permission was not given"
        if report.state is PointerConsent.UNAVAILABLE:
            return State.UNAVAILABLE, report.detail or "the desktop offers no pointer"
        return None

    def _lost(self, sample: HeadPoseSignal | None) -> Step:
        """No usable signal: freeze, forget, and require a settling frame on return."""
        self._tracking = False
        self._quiesce()
        reason = "no sample" if sample is None else "sample stale or low confidence"
        if self._fault:
            return self._set(State.FAULTED, self._fault)
        return self._set(State.LOST, reason)

    def _rest(self, state: State, reason: str) -> Step:
        """A sample arrived but something forbids acting on it."""
        self._quiesce()
        return self._set(state, reason)

    def _quiesce(self, *, settle: bool = True) -> None:
        """Drop every half-built action: the remainder, the dwell, the arming.

        The next valid sample is then only observed (``_settle``), and dwell is disarmed until
        the pointer has moved. Together they are what makes "no click on startup / reconnect /
        recenter / resume" a property of the state machine rather than of luck.
        """
        self._acc.reset()
        self._clicker.reset()
        self._trail.clear()
        self._dwell_armed = False
        self._dwell_origin = self._pos
        if settle:
            self._settle = True
        self._sync_feedback()

    def _follow(self, sample: HeadPoseSignal, dt: float, ts: float) -> Step:
        """Move by the capped velocity for the offset from neutral, over ``dt`` seconds.

        ``ts`` is the sample's own timestamp, which is what the dwell is timed on.
        """
        assert self._neutral is not None
        vx, vy = limit_velocity(
            *pose_to_cursor(
                sample.yaw - self._neutral[0], sample.pitch - self._neutral[1], self._calib
            ),
            self._calib,
        )
        dx, dy = vx * dt, vy * dt
        try:
            ix, iy = self._acc.take(dx, dy)
        except ValueError:
            return self._fail("non-finite pointer delta")
        if ix or iy:
            try:
                self._sink.move_relative(float(ix), float(iy))
            except Exception as exc:
                return self._fail(_describe(exc))
            self._pos = (self._pos[0] + ix, self._pos[1] + iy)
            self._trail.append((sample.timestamp_s, ix, iy))
            horizon = sample.timestamp_s - REWIND_LIMIT_S
            while self._trail and self._trail[0][0] < horizon:
                self._trail.popleft()
        clicked = False
        if self._dwell_enabled:
            clicked_or_fail = self._dwell(ts)
            if isinstance(clicked_or_fail, Step):
                return clicked_or_fail
            clicked = clicked_or_fail
        self._sync_feedback()
        return self._set(State.TRACKING, "", dx=ix, dy=iy, clicked=clicked)

    def _rewind(self, since_s: float, max_rewind_s: float | None) -> None:
        """Send the opposite of the whole units moved for samples at or after ``since_s``.

        Bounded three ways: by ``since_s``, by ``max_rewind_s`` and by :data:`REWIND_LIMIT_S`
        (each measured back from the newest moved sample). Nothing is sent when there is
        nothing to take back, when the feature is paused, faulted or closed, or when the
        arguments are not finite numbers -- doubt is no rewind.
        """
        if self._closed or self._fault or self._paused or not self._trail:
            return
        if not (isinstance(since_s, (int, float)) and math.isfinite(since_s)):
            return
        reach = REWIND_LIMIT_S
        if max_rewind_s is not None:
            if not (isinstance(max_rewind_s, (int, float)) and math.isfinite(max_rewind_s)):
                return
            if max_rewind_s <= 0.0:
                return
            reach = min(reach, float(max_rewind_s))
        floor = max(float(since_s), self._trail[-1][0] - reach)
        back_x = sum(x for t, x, _ in self._trail if t >= floor)
        back_y = sum(y for t, _, y in self._trail if t >= floor)
        self._trail.clear()
        if not (back_x or back_y):
            return
        try:
            self._sink.move_relative(float(-back_x), float(-back_y))
        except Exception as exc:
            self._fail(_describe(exc))
            return
        self._pos = (self._pos[0] - back_x, self._pos[1] - back_y)

    def _dwell(self, ts: float) -> bool | Step:
        """Advance dwell for the current position at time ``ts``. ``True`` iff a click was sent."""
        if not self._dwell_armed:
            # Armed only by real travel past the radius from where the last interruption (or
            # click) left the pointer -- never by stillness alone.
            ox, oy = self._dwell_origin
            if (self._pos[0] - ox) ** 2 + (self._pos[1] - oy) ** 2 > self._radius**2:
                self._dwell_armed = True
            else:
                return False
        # A click is allowed only if an earlier sample already published progress above zero
        # (``_shown``): the user must have been *shown* the dwell before it can fire. At the
        # shipped hold this is always so; it matters for a hold at or below one camera frame.
        if not self._clicker.update(
            float(self._pos[0]), float(self._pos[1]), ts, may_fire=self._shown is not None
        ):
            return False
        # Disarm *before* the call: if the sink fails the click is not retried, and if it
        # succeeds the user has to move before another can come.
        self._clicker.reset()
        self._dwell_armed = False
        self._dwell_origin = self._pos
        try:
            self._sink.click(PointerButton.LEFT)
        except Exception as exc:
            return self._fail(_describe(exc))
        return True

    def _fail(self, reason: str) -> Step:
        """The pointer backend failed: stop, tell the gate, retry nothing."""
        self._fault = reason
        self._quiesce()
        if self._safety is not None:
            try:
                self._safety.fault(self._source, reason)
            except Exception:
                log.debug("head-pointer: reporting a fault to the gate raised", exc_info=True)
        log.warning("Head-Pointer stopped: %s (resume with `yazses headpointer resume`)", reason)
        return self._set(State.FAULTED, reason)

    def _set(
        self, state: State, reason: str, *, dx: int = 0, dy: int = 0, clicked: bool = False
    ) -> Step:
        self._state = state
        self._reason = reason
        return Step(state, dx, dy, clicked, reason)

    def _progress(self) -> float:
        if not (self._dwell_enabled and self._dwell_armed):
            return 0.0
        return self._clicker.progress

    def _sync_feedback(self) -> None:
        """Tell the user about dwell progress, on change only."""
        progress = self._progress()
        shown = self._shown
        if progress > 0.0 and progress != shown:
            self._shown = progress
            self._notify("show", progress)
        elif progress == 0.0 and shown is not None:
            self._shown = None
            self._notify("hide")

    def _notify(self, method: str, *args: float) -> None:
        feedback = self._feedback
        if feedback is None:
            return
        try:
            getattr(feedback, method)(*args)
        except Exception:
            log.debug("head-pointer: dwell feedback raised", exc_info=True)


def _backend_name(sink: object) -> str:
    try:
        return str(sink.capabilities().backend)  # type: ignore[attr-defined]
    except Exception:
        return ""


def _describe(exc: Exception) -> str:
    """A short reason from a sink failure: its type and its own message, bounded."""
    text = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
    return text[:200]
