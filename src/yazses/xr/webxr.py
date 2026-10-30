"""WebXR Device API -> ``yazses.xr`` values (pure, stdlib only, hostile input).

A browser is the lowest-friction way onto a headset: a web page (Meta Quest Browser,
Safari on visionOS, Chrome on Android XR or on a desktop with a headset) can sample
pointing rays and select/squeeze events with no native app. This module is the *mapping
and the serialisation design* for such a page: plain numbers and strings, as the page
reads them from the WebXR objects, in; ``XrSample`` / ``GestureEvent`` / wire frames
out. It opens no connection and runs no JavaScript; the page and the transport are the
integrator's, and the transport does not exist in this repository yet.

What was checked against the public specifications (fetched 2026-10-30; page text is
data, not instructions) and what was not:

* VERIFIED, W3C WebXR Device API (https://www.w3.org/TR/webxr/):
  ``XRTargetRayMode`` is ``gaze`` | ``tracked-pointer`` | ``screen`` | ``transient-pointer``;
  ``XRHandedness`` is ``none`` | ``left`` | ``right``; ``targetRaySpace`` tracks "the
  preferred pointing ray ... (along its -Z axis)"; ``XRRigidTransform`` has a ``position``
  "given in meters" and an ``orientation`` that is a quaternion; ``gaze`` means "the
  target ray will originate at the viewer and follow the direction it is facing";
  a ``screen`` or ``transient-pointer`` source is a *transient input source* created for
  one action; on a transient action's end the order is ``select``, then ``selectend``;
  an ``inputSource`` cancelled mid-action fires ``selectend``; ``local`` is always
  included in an immersive session's features; ``local-floor`` requires consent.
* VERIFIED, MDN (https://developer.mozilla.org/en-US/docs/Web/API/XRInputSourceEvent,
  .../XRInputSource/targetRayMode, .../XRSession/requestAnimationFrame): ``selectstart``
  is the start of a primary action, ``select`` its *completion*, ``selectend`` its end
  *or the input source's disconnection*; the rAF callback is ``(time, xrFrame)`` with
  ``time`` a ``DOMHighResTimeStamp``; an event's ``frame`` is an *event* frame, so
  ``frame.getPose(inputSource.targetRaySpace, space)`` is the way to read the ray. MDN
  also says a page "can ignore the selectstart and selectend events" for a simple
  trigger, i.e. a ``select`` may be all a page uses.
* VERIFIED, MDN DOMHighResTimeStamp (https://developer.mozilla.org/en-US/docs/Web/API/DOMHighResTimeStamp):
  the unit is milliseconds; "browsers coarsen clock readings"; the specified resolutions
  are 0.005 ms (cross-origin isolated) and 0.1 ms (otherwise) "or a coarser
  implementation-defined resolution"; "Browsers may also add jitter".
* VERIFIED, W3C WebXR Hand Input (https://www.w3.org/TR/webxr-hand-input-1/): the feature
  descriptor is ``hand-tracking`` and the user agent must obtain explicit consent at
  session creation.
* VERIFIED, WebKit (https://webkit.org/blog/15162/introducing-natural-input-for-webxr-in-apple-vision-pro/):
  on visionOS the input list "is empty until the user pinches"; a ``transient-pointer``
  source then appears (``inputsourceschange``, then ``selectstart``), its ray starts at
  the gaze and thereafter "is updated with the movement of their hand rather than their
  eyes", and it is removed after ``select``/``selectend``.
* NOT FOUND (a search of the above found no such thing): a standard WebXR feature
  descriptor ``eye-tracking``. Treat it as unverified; see :func:`describe_feature`.
* UNVERIFIED, from memory and not re-fetched: that ``select`` is delivered *before*
  ``selectend`` for non-transient sources too (:class:`InputEventMapper` does not
  depend on it); that ``getPose`` returns null while an input is untracked; the -Z
  orientation of the ``viewer`` space; the time origin of ``Event.timeStamp`` versus the
  rAF ``time`` (hence the encoder keeps one timeline per stream); the exact
  coarsening a given browser applies (Firefox's fingerprinting-resistance mode is
  believed to be much coarser than the specification's minimum).

Conventions: WebXR is right-handed, +Y up, -Z forward, metres, so poses pass through
unconverted (the same frame as ``xr.types``). Positions are relative to the page's
reference space; the page must report rays and panels in the *same* reference space.
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum

from yazses.xr.geometry import normalize
from yazses.xr.types import (
    GestureEvent,
    GestureKind,
    Ray,
    RaySource,
    Vec3,
    XrSample,
)
from yazses.xr.wire import WireError, encode_frame

_MAX_TIME_MS = 1e12     # == the wire layer's 1e9 s device-time ceiling
_MAX_COORD_M = 1e6      # == the wire layer's coordinate ceiling
_QUAT_TOL = 1e-3        # a quaternion this near unit length is renormalised, else refused
_MAX_KEY_LEN = 128
_MAX_SLOTS = 32         # per-(source, family) action state; the oldest is evicted
_MAX_PROFILES = 16
_MAX_JITTER_MS = 1000.0
_DEFAULT_JITTER_MS = 1.0
_DEFAULT_LATE_SELECT_S = 0.05


class WebXrError(WireError):
    """Input from the page was refused. A ``WireError``, so a session that already drops
    frames on ``WireError`` drops these too; nothing else escapes this module's API."""


# -- plain-value validators ---------------------------------------------------


def _number(name: str, value: object, *, lo: float, hi: float) -> float:
    """A finite number in [lo, hi]. ``bool`` and numeric strings are not numbers."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise WebXrError(f"{name} must be a number")
    try:
        number = float(value)
    except OverflowError:  # an int too wide for a float (10**400)
        raise WebXrError(f"{name} is outside [{lo:g}, {hi:g}]") from None
    if not math.isfinite(number):
        raise WebXrError(f"{name} must be finite")
    if not lo <= number <= hi:
        raise WebXrError(f"{name} is outside [{lo:g}, {hi:g}]")
    return number + 0.0  # -0.0 -> 0.0


def _components(name: str, value: object, count: int, *, limit: float) -> tuple[float, ...]:
    """``count`` numbers from a list or tuple (a JSON array); anything else is refused."""
    if not isinstance(value, (list, tuple)) or len(value) != count:
        raise WebXrError(f"{name} must be an array of {count} numbers")
    return tuple(_number(f"{name}[{i}]", c, lo=-limit, hi=limit) for i, c in enumerate(value))


def _short(value: object) -> str:
    text = repr(value)
    return text if len(text) <= 40 else text[:37] + "..."


def _key(value: object) -> str:
    """An input-source key: the page's index or id for one ``XRInputSource``."""
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise WebXrError("source_key must be an int or a string")
    if isinstance(value, int) and not -(2**63) <= value < 2**63:
        raise WebXrError("source_key integer is out of range")  # also keeps str() cheap
    text = str(value)
    if not text or len(text) > _MAX_KEY_LEN or not text.isprintable():
        raise WebXrError("source_key must be printable and up to 128 characters")
    return text


def _confidence(value: object) -> float:
    return _number("confidence", value, lo=0.0, hi=1.0)


# -- input-source description -------------------------------------------------


class TargetRayMode(Enum):
    """``XRInputSource.targetRayMode`` (W3C WebXR, "XRTargetRayMode"). Closed."""

    GAZE = "gaze"
    TRACKED_POINTER = "tracked-pointer"
    SCREEN = "screen"
    TRANSIENT_POINTER = "transient-pointer"


class InputHandedness(Enum):
    """``XRInputSource.handedness``. Unlike ``conventions.Handedness`` it has ``none``,
    which gaze, screen and transient-pointer sources report."""

    NONE = "none"
    LEFT = "left"
    RIGHT = "right"


def _parse_enum(name: str, value: object, enum: type[Enum]) -> Enum:
    if not isinstance(value, str):
        raise WebXrError(f"{name} must be a string")
    try:
        return enum(value)  # exact, lower-case: a mixed-case string is not the spec's
    except ValueError:
        raise WebXrError(f"unknown {name} {_short(value)}") from None


def parse_target_ray_mode(value: object) -> TargetRayMode:
    """``"tracked-pointer"`` -> ``TargetRayMode.TRACKED_POINTER``; unknown -> ``WebXrError``.

    An unknown string is refused rather than guessed: a browser that adds a mode
    tomorrow must be reviewed before its rays are trusted as pointing."""
    mode = _parse_enum("targetRayMode", value, TargetRayMode)
    assert isinstance(mode, TargetRayMode)
    return mode


def parse_handedness(value: object) -> InputHandedness:
    hand = _parse_enum("handedness", value, InputHandedness)
    assert isinstance(hand, InputHandedness)
    return hand


def ray_source_for(mode: TargetRayMode, *, has_hand: bool = False) -> RaySource:
    """Which :class:`RaySource` a WebXR input source's ray is recorded as.

    * ``gaze`` -> ``HEAD``. The W3C text says the ray follows "the direction [the
      viewer] is facing"; MDN calls it a gaze-tracking system, and a W3C TAG review
      asked whether "gaze" there means eye tracking or head direction. Until that is
      settled the ray is never recorded as ``EYE``: an eye ray earns more trust from
      the binder than a head ray should.
    * ``tracked-pointer`` -> ``HAND`` when ``has_hand`` (the page saw ``inputSource.hand``;
      the hand-input module, unverified here) else ``CONTROLLER``.
    * ``transient-pointer`` -> ``HAND``: a pinch, whose ray starts at the gaze but is then
      steered by the hand (WebKit), so it is not a gaze trace and is not claimed as one.
    * ``screen`` -> ``CONTROLLER``: the closest closed member for a touch/mouse ray; there
      is no ``SCREEN`` source and adding one is a reviewed ``types.py`` change.
    """
    if not isinstance(mode, TargetRayMode):
        raise WebXrError("mode must be a TargetRayMode")
    if mode is TargetRayMode.GAZE:
        return RaySource.HEAD
    if mode is TargetRayMode.TRANSIENT_POINTER:
        return RaySource.HAND
    if mode is TargetRayMode.TRACKED_POINTER and has_hand is True:
        return RaySource.HAND
    return RaySource.CONTROLLER


@dataclass(frozen=True)
class InputSourceInfo:
    """What the page knows about one ``XRInputSource`` (no pose, no time).

    ``profiles`` are the source's ``profiles`` strings, kept only as bounded, printable
    text for the integrator's logs and device quirks; nothing here depends on them.
    """

    mode: TargetRayMode
    handedness: InputHandedness = InputHandedness.NONE
    has_hand: bool = False
    profiles: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.mode, TargetRayMode):
            raise ValueError("InputSourceInfo.mode must be a TargetRayMode")
        if not isinstance(self.handedness, InputHandedness):
            raise ValueError("InputSourceInfo.handedness must be an InputHandedness")
        if not isinstance(self.has_hand, bool):
            raise ValueError("InputSourceInfo.has_hand must be a bool")
        if not isinstance(self.profiles, tuple) or len(self.profiles) > _MAX_PROFILES:
            raise ValueError("InputSourceInfo.profiles must be a tuple of at most 16 strings")
        for p in self.profiles:
            if not isinstance(p, str) or not p or len(p) > _MAX_KEY_LEN or not p.isprintable():
                raise ValueError("InputSourceInfo.profiles entries must be short printable strings")

    @property
    def ray_source(self) -> RaySource:
        return ray_source_for(self.mode, has_hand=self.has_hand)


def describe_input_source(
    target_ray_mode: object,
    handedness: object = "none",
    *,
    has_hand: object = False,
    profiles: object = (),
) -> InputSourceInfo:
    """Build an :class:`InputSourceInfo` from the page's raw strings; ``WebXrError`` on any
    unknown or mistyped value (including a non-bool ``has_hand``)."""
    if not isinstance(has_hand, bool):
        raise WebXrError("has_hand must be a boolean")
    if not isinstance(profiles, (list, tuple)):
        raise WebXrError("profiles must be an array of strings")
    try:
        return InputSourceInfo(
            parse_target_ray_mode(target_ray_mode),
            parse_handedness(handedness),
            has_hand,
            tuple(profiles),
        )
    except WebXrError:
        raise
    except ValueError as exc:
        raise WebXrError(f"invalid input source: {exc}"[:200]) from None


@dataclass(frozen=True)
class ModeCapabilities:
    """What a target-ray mode can give the deixis binder, as a static summary.

    ``ray_only_during_action`` is True where the specification or the WebKit post says the
    source exists only for the length of one action (``screen``, ``transient-pointer``);
    False means "not stated to be transient", not "proven continuous"."""

    mode: TargetRayMode
    ray_source: RaySource
    ray_only_during_action: bool
    note: str


_CAPABILITIES: dict[TargetRayMode, ModeCapabilities] = {
    TargetRayMode.GAZE: ModeCapabilities(
        TargetRayMode.GAZE,
        RaySource.HEAD,
        False,
        "Ray from the viewer along the facing direction: a head ray, not an eye trace.",
    ),
    TargetRayMode.TRACKED_POINTER: ModeCapabilities(
        TargetRayMode.TRACKED_POINTER,
        RaySource.CONTROLLER,
        False,
        "Handheld device or tracked hand; sampled every frame while tracked, so a "
        "rolling ray history exists. The pose can be unavailable while tracking is lost.",
    ),
    TargetRayMode.SCREEN: ModeCapabilities(
        TargetRayMode.SCREEN,
        RaySource.CONTROLLER,
        True,
        "Touch, mouse or stylus; a transient source that exists for the action only.",
    ),
    TargetRayMode.TRANSIENT_POINTER: ModeCapabilities(
        TargetRayMode.TRANSIENT_POINTER,
        RaySource.HAND,
        True,
        "visionOS gaze+pinch: the browser exposes a source only from pinch to release, "
        "so there is NO ray before the pinch and no continuous gaze history; once "
        "pinched the ray follows the hand, not the eyes.",
    ),
}


def mode_capabilities(mode: TargetRayMode) -> ModeCapabilities:
    if not isinstance(mode, TargetRayMode):
        raise WebXrError("mode must be a TargetRayMode")
    return _CAPABILITIES[mode]


# -- pose -> ray --------------------------------------------------------------


def ray_from_pose(position: Sequence[float], orientation: Sequence[float]) -> Ray:
    """The pointing ray of an ``XRRigidTransform``: origin ``position``, direction the
    transformed -Z axis.

    ``position`` is ``[x, y, z]`` metres (``DOMPointReadOnly`` x, y, z) and
    ``orientation`` is the quaternion ``[x, y, z, w]`` in WebXR's component order, with
    ``w`` last. A quaternion within 1e-3 of unit length is renormalised; further out, or
    zero, it is refused. ``q`` and ``-q`` give the same ray (double cover).

    The direction is ``-R e_z``, the negated third column of the rotation matrix::

        (-2(xz + wy),  2(wx - yz),  2(x^2 + y^2) - 1)

    so the identity quaternion looks along (0, 0, -1), a +90 degree turn about +Y looks
    along (-1, 0, 0) and a +90 degree pitch about +X looks straight up.
    """
    px, py, pz = _components("position", position, 3, limit=_MAX_COORD_M)
    qx, qy, qz, qw = _components("orientation", orientation, 4, limit=2.0)
    length = math.hypot(qx, qy, qz, qw)
    if abs(length - 1.0) > _QUAT_TOL:
        raise WebXrError(f"orientation must be a unit quaternion (got length {length:.6g})")
    qx, qy, qz, qw = qx / length, qy / length, qz / length, qw / length
    direction = Vec3(
        -2.0 * (qx * qz + qw * qy) + 0.0,  # + 0.0 turns -0.0 into 0.0
        2.0 * (qw * qx - qy * qz) + 0.0,
        2.0 * (qx * qx + qy * qy) - 1.0,
    )
    try:
        return Ray(Vec3(px, py, pz), normalize(direction))
    except ValueError as exc:  # unreachable for a unit quaternion; stay total anyway
        raise WebXrError(f"invalid pose: {exc}"[:200]) from None


# -- time ---------------------------------------------------------------------


def ms_to_seconds(time_ms: object) -> float:
    """A ``DOMHighResTimeStamp`` (milliseconds) as seconds, validated.

    The wire layer takes seconds; passing the page's value through unconverted is a
    thousand-fold error that no check can see (a seconds value reads as a perfectly good
    millisecond one). What *is* caught: a string, a bool, NaN/inf, a negative, and
    anything above 1e12 ms, which includes ``Date.now()`` (about 1.7e12 ms) -- the usual
    wrong clock. A seconds-for-milliseconds slip is left to the downstream ``ClockMap``,
    whose rate bound refuses a stream whose clock runs a thousand times slow.
    """
    return _number("time_ms", time_ms, lo=0.0, hi=_MAX_TIME_MS) / 1000.0


class FrameTimeline:
    """Milliseconds from a page-load origin -> non-decreasing seconds, tolerant of coarsening.

    Browsers coarsen ``DOMHighResTimeStamp`` and may add jitter (MDN). That is a
    *precision limit*, not an error, and this class models it in three ways:

    * **Equal stamps are normal.** Several frames, or several input sources in one
      frame, share one coarse tick. They pass through unchanged; the class does not
      spread them (that would invent precision the browser withheld).
    * **A small step back is clamped.** Jitter can make a stamp read earlier than its
      predecessor by up to ``jitter_tolerance_ms``; it is raised to the predecessor so
      the output never decreases, and counted in :attr:`clamped`.
    * **A big step back is refused.** More than the tolerance means a clock restart (a
      reload) or a mixed-up stream: ``WebXrError``, state unchanged, until
      :meth:`reset`. Forward jumps of any size are accepted (a hidden tab stops
      producing frames); ``ClockMap`` downstream judges those against the desktop clock.

    ``jitter_tolerance_ms`` defaults to 1 ms, comfortably above the specified 0.1 ms
    floor. A browser that rounds much more coarsely (believed, unverified, to be true of
    some fingerprinting-resistance modes) needs a tolerance at least as large as its
    rounding step, and its coarse ticks will starve the binder (see
    :attr:`min_positive_step_ms`).
    """

    def __init__(self, *, jitter_tolerance_ms: float = _DEFAULT_JITTER_MS) -> None:
        self._tolerance = _number(
            "jitter_tolerance_ms", jitter_tolerance_ms, lo=0.0, hi=_MAX_JITTER_MS
        )
        self._reset_state()

    def _reset_state(self) -> None:
        self._last: float | None = None
        self._clamped = 0
        self._repeats = 0
        self._min_step: float | None = None

    def reset(self) -> None:
        """Forget the history (a new page load or session)."""
        self._reset_state()

    @property
    def clamped(self) -> int:
        """How many stamps were raised to their predecessor (jitter absorbed)."""
        return self._clamped

    @property
    def repeats(self) -> int:
        """How many stamps equalled their predecessor (coarsening observed)."""
        return self._repeats

    @property
    def min_positive_step_ms(self) -> float | None:
        """Smallest forward step seen: an upper bound on the browser's tick, so a value
        near 100 means the binder is being fed ~10 Hz time and will usually decline."""
        return self._min_step

    def to_seconds(self, time_ms: object) -> float:
        ms = _number("time_ms", time_ms, lo=0.0, hi=_MAX_TIME_MS)
        last = self._last
        if last is not None:
            if ms < last:
                if last - ms > self._tolerance:
                    raise WebXrError(
                        f"timestamp went back {last - ms:.3f} ms (tolerance {self._tolerance:g} ms)"
                    )
                self._clamped += 1
                ms = last
            elif ms == last:
                self._repeats += 1
            else:
                step = ms - last
                if self._min_step is None or step < self._min_step:
                    self._min_step = step
        self._last = ms
        return ms / 1000.0


# -- select / squeeze events -> gestures --------------------------------------


class InputEventName(Enum):
    """The six ``XRInputSourceEvent`` types a page listens for. Closed."""

    SELECT = "select"
    SELECTSTART = "selectstart"
    SELECTEND = "selectend"
    SQUEEZE = "squeeze"
    SQUEEZESTART = "squeezestart"
    SQUEEZEEND = "squeezeend"


def parse_input_event(value: object) -> InputEventName:
    event = _parse_enum("event", value, InputEventName)
    assert isinstance(event, InputEventName)
    return event


_SELECT, _SQUEEZE = "select", "squeeze"


@dataclass
class _Slot:
    held: bool = False
    last_end_s: float | None = None


class InputEventMapper:
    """Turn select/squeeze events into :class:`GestureEvent` with the right hold semantics.

    The package's hold-to-talk needs *both edges*: ``selectstart`` -> ``PINCH_START`` and
    ``selectend`` -> ``PINCH_END`` (``squeezestart``/``squeezeend`` -> ``SQUEEZE_*``). The
    "pinch" name is the package's; the WebXR *primary action* behind it is whatever the
    device defines (a controller trigger, a hand pinch, a tap).

    ``select`` alone is *not* a hold. It is the action's completion, so:

    * ``select`` while that source's action is held -> ``None`` (its ``selectend`` follows
      and carries the edge); reporting it too would double-count.
    * ``select`` within ``late_select_window_s`` after that source's ``selectend`` -> ``None``
      too. The specification fixes ``select`` before ``selectend`` for transient sources;
      for others that ordering is unverified, and a ``select`` straggling in after the end
      must not become a ``TAP``, which in ``toggle_tap`` mode would flip the microphone.
    * otherwise (no start, no recent end: a page or device that reports only ``select``) ->
      ``TAP``. Such a source can drive ``toggle_tap`` but never a hold.
    * ``squeeze`` alone has no gesture (``GestureKind`` has no squeeze tap) -> ``None``.

    An end event is *always* passed on, even with no start seen: the safe direction for a
    microphone. :meth:`source_removed` and :meth:`end_session` synthesise the ends that a
    vanished source or a finished session would otherwise leave dangling (the specification
    sends ``selectend`` on a disconnect; a session ending mid-action is unverified).

    State is per ``(source, family)``, bounded to 32 entries (the oldest is evicted).
    """

    def __init__(self, *, late_select_window_s: float = _DEFAULT_LATE_SELECT_S) -> None:
        self._window = _number("late_select_window_s", late_select_window_s, lo=0.0, hi=5.0)
        self._slots: dict[tuple[str, str], _Slot] = {}

    @property
    def held_count(self) -> int:
        """Actions currently held (a start with no end yet)."""
        return sum(1 for s in self._slots.values() if s.held)

    def reset(self) -> None:
        self._slots.clear()

    def _slot(self, key: str, family: str) -> _Slot:
        k = (key, family)
        slot = self._slots.get(k)
        if slot is None:
            if len(self._slots) >= _MAX_SLOTS:
                # Prefer evicting a slot that is not held; a held one is the only reason
                # a later end event matters, though ends are passed on regardless.
                victim = next(
                    (kk for kk, s in self._slots.items() if not s.held),
                    next(iter(self._slots)),
                )
                del self._slots[victim]
            slot = self._slots[k] = _Slot()
        return slot

    def feed(
        self, event: object, timestamp_s: object, source_key: object
    ) -> GestureEvent | None:
        """Map one event. ``timestamp_s`` is *seconds* (use :class:`FrameTimeline`)."""
        name = parse_input_event(event)
        key = _key(source_key)
        t = _number("timestamp_s", timestamp_s, lo=0.0, hi=_MAX_TIME_MS / 1000.0)
        family = _SQUEEZE if name.value.startswith("squeeze") else _SELECT
        kinds = (
            (GestureKind.SQUEEZE_START, GestureKind.SQUEEZE_END)
            if family == _SQUEEZE
            else (GestureKind.PINCH_START, GestureKind.PINCH_END)
        )
        slot = self._slot(key, family)
        if name.value.endswith("start"):
            slot.held = True
            return GestureEvent(t, kinds[0])
        if name.value.endswith("end"):
            slot.held = False
            slot.last_end_s = t
            return GestureEvent(t, kinds[1])
        # Bare select / squeeze: the action's completion.
        if slot.held:
            return None
        if family == _SQUEEZE:
            return None
        if slot.last_end_s is not None and 0.0 <= t - slot.last_end_s <= self._window:
            return None
        return GestureEvent(t, GestureKind.TAP)

    def _close(self, keys: list[tuple[str, str]], t: float) -> tuple[GestureEvent, ...]:
        out: list[GestureEvent] = []
        for key in keys:
            slot = self._slots[key]
            if slot.held:
                slot.held = False
                slot.last_end_s = t
                kind = GestureKind.SQUEEZE_END if key[1] == _SQUEEZE else GestureKind.PINCH_END
                out.append(GestureEvent(t, kind))
        return tuple(out)

    def source_removed(self, source_key: object, timestamp_s: object) -> tuple[GestureEvent, ...]:
        """The page's ``inputsourceschange`` removed this source: end whatever it held."""
        key = _key(source_key)
        t = _number("timestamp_s", timestamp_s, lo=0.0, hi=_MAX_TIME_MS / 1000.0)
        return self._close([k for k in self._slots if k[0] == key], t)

    def end_session(self, timestamp_s: object) -> tuple[GestureEvent, ...]:
        """The session ended (or the page is closing): end every held action."""
        t = _number("timestamp_s", timestamp_s, lo=0.0, hi=_MAX_TIME_MS / 1000.0)
        return self._close(list(self._slots), t)


# -- pose + event -> wire -----------------------------------------------------


def sample_from_pose(
    timestamp_s: float,
    source: RaySource,
    position: Sequence[float],
    orientation: Sequence[float],
    *,
    confidence: float = 1.0,
) -> XrSample:
    """An :class:`XrSample` from a WebXR pose. ``timestamp_s`` is seconds already.

    WebXR reports no tracker confidence, so the default 1.0 means "the browser gave a
    pose", not "the pose is accurate"; pass a lower value for a source you distrust
    (for example a head-direction ray used as a stand-in for gaze).
    """
    if not isinstance(source, RaySource):
        raise WebXrError("source must be a RaySource")
    try:
        return XrSample(
            timestamp_s=_number("timestamp_s", timestamp_s, lo=0.0, hi=_MAX_TIME_MS / 1000.0),
            source=source,
            ray=ray_from_pose(position, orientation),
            confidence=_confidence(confidence),
        )
    except WebXrError:
        raise
    except ValueError as exc:
        raise WebXrError(f"invalid sample: {exc}"[:200]) from None


class WebXrFrameEncoder:
    """Serialise a page's WebXR observations as ``wire`` frames (bytes). Pure; no transport.

    This is the *design* a companion page follows, kept as tested Python so the numbers
    (axis, quaternion order, milliseconds to seconds, event semantics) are pinned and an
    integrator's JavaScript can be checked against it. The JavaScript is in
    ``docs/xr-webxr.md``; this package does not run it and sends nothing.

    Two timelines, deliberately: rAF poses and DOM events are stamped by different
    mechanisms and the event clock's origin is unverified, so one shared monotone
    timeline could mistake a legitimate event/pose interleaving for a clock step. Each
    stream is monotone on its own; ``ClockMap`` handles the desktop side.

    Every method raises only :class:`WebXrError` (a ``WireError``).
    """

    def __init__(
        self,
        *,
        jitter_tolerance_ms: float = _DEFAULT_JITTER_MS,
        late_select_window_s: float = _DEFAULT_LATE_SELECT_S,
    ) -> None:
        self.poses = FrameTimeline(jitter_tolerance_ms=jitter_tolerance_ms)
        self.events = FrameTimeline(jitter_tolerance_ms=jitter_tolerance_ms)
        self._mapper = InputEventMapper(late_select_window_s=late_select_window_s)

    @property
    def held_count(self) -> int:
        return self._mapper.held_count

    def reset(self) -> None:
        """New page load or reconnect: forget both timelines and any held action."""
        self.poses.reset()
        self.events.reset()
        self._mapper.reset()

    def pose_frame(
        self,
        time_ms: object,
        info: InputSourceInfo,
        position: Sequence[float],
        orientation: Sequence[float],
        *,
        confidence: float = 1.0,
    ) -> bytes:
        """One input source's target-ray pose from an rAF frame -> a ``sample`` frame."""
        if not isinstance(info, InputSourceInfo):
            raise WebXrError("info must be an InputSourceInfo")
        sample = sample_from_pose(
            self.poses.to_seconds(time_ms),
            info.ray_source,
            position,
            orientation,
            confidence=confidence,
        )
        return encode_frame(sample)

    def viewer_frame(
        self,
        time_ms: object,
        position: Sequence[float],
        orientation: Sequence[float],
        *,
        confidence: float = 1.0,
    ) -> bytes:
        """The viewer (head) pose from ``frame.getViewerPose`` -> a ``head`` sample.

        Unlike a transient pointer this exists every frame, so it gives the binder a
        continuous history -- of where the head faced, which is not where the eyes looked.
        """
        sample = sample_from_pose(
            self.poses.to_seconds(time_ms),
            RaySource.HEAD,
            position,
            orientation,
            confidence=confidence,
        )
        return encode_frame(sample)

    def event_frame(self, event: object, time_ms: object, source_key: object) -> bytes | None:
        """A select/squeeze event -> a ``gesture`` frame, or ``None`` when it carries no edge."""
        gesture = self._mapper.feed(event, self.events.to_seconds(time_ms), source_key)
        return None if gesture is None else encode_frame(gesture)

    def source_removed(self, source_key: object, time_ms: object) -> tuple[bytes, ...]:
        """``inputsourceschange`` removed a source: frames ending what it held."""
        ends = self._mapper.source_removed(source_key, self.events.to_seconds(time_ms))
        return tuple(encode_frame(g) for g in ends)

    def end_session(self, time_ms: object) -> tuple[bytes, ...]:
        """The XR session ended: frames ending every held action (closes the microphone)."""
        ends = self._mapper.end_session(self.events.to_seconds(time_ms))
        return tuple(encode_frame(g) for g in ends)


# -- session features ---------------------------------------------------------


@dataclass(frozen=True)
class FeatureNote:
    """What is known about one ``requiredFeatures`` / ``optionalFeatures`` string.

    ``standard`` and ``needs_consent`` are ``None`` when unknown -- never ``False``."""

    name: str
    standard: bool | None
    needs_consent: bool | None
    note: str


_FEATURES: dict[str, FeatureNote] = {
    "local": FeatureNote(
        "local", True, None,
        "Always included in an immersive session (W3C WebXR 3.4); origin at the viewer's "
        "start position. Enough for rays and panels, so nothing else is needed.",
    ),
    "viewer": FeatureNote(
        "viewer", True, None, "Applies to all sessions (W3C WebXR 3.4); the head pose."
    ),
    "local-floor": FeatureNote(
        "local-floor", True, True,
        "Floor-level origin; the W3C text says it always requires consent. Not needed here.",
    ),
    "hand-tracking": FeatureNote(
        "hand-tracking", True, True,
        "Articulated hand joints (W3C WebXR Hand Input). The user agent must obtain "
        "explicit consent at session creation. NOT needed: select/squeeze and "
        "targetRaySpace work without joint data, and YazSes never reads joints.",
    ),
    "eye-tracking": FeatureNote(
        "eye-tracking", None, None,
        "No such feature descriptor was found in the W3C WebXR specification or its Hand "
        "Input module (unverified). Safari on visionOS deliberately gives no continuous "
        "gaze. Do not rely on it; a required unknown feature may fail the whole session "
        "(unverified), so never put it in requiredFeatures.",
    ),
}


def describe_feature(name: object) -> FeatureNote:
    """The note for a feature string; an unknown string is reported as unknown, not guessed."""
    if not isinstance(name, str) or not name or len(name) > _MAX_KEY_LEN or not name.isprintable():
        raise WebXrError("feature name must be a printable, non-empty string up to 128 characters")
    known = _FEATURES.get(name)
    if known is not None:
        return known
    return FeatureNote(name, None, None, "Unknown to this module; check the specification.")


def session_init_features(*, hand_tracking: bool = False) -> dict[str, list[str]]:
    """The ``requiredFeatures`` / ``optionalFeatures`` for ``navigator.xr.requestSession``.

    The minimum: nothing is required (``local`` is implicit in an immersive session) and,
    unless asked, nothing optional either, so the consent prompts the page triggers are
    only the browser's own entry prompt. ``hand_tracking=True`` adds ``hand-tracking`` as
    *optional* (an explicit-consent prompt; the page must tolerate a refusal). There is no
    ``eye_tracking`` switch on purpose (see :func:`describe_feature`).
    """
    if not isinstance(hand_tracking, bool):
        raise WebXrError("hand_tracking must be a boolean")
    return {"requiredFeatures": [], "optionalFeatures": ["hand-tracking"] if hand_tracking else []}
