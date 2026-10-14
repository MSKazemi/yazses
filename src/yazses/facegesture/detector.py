"""Face-gesture switch: a blendshape score stream → hold-start / hold-end (pure).

The switch-access half of the hands-free bundle (#102). MediaPipe's FaceLandmarker
already runs for Glance-Type and emits 52 ARKit-style *blendshape* scores per frame,
each a 0..1 activation of one facial movement. One of those movements — jaw open,
brows raised — becomes the key you hold: the mic opens while the gesture is held and
closes when it relaxes, exactly like the keyboard hotkey.

Everything here is pure: it consumes a score per frame and returns an event, so the
whole activation policy is unit-testable with no camera, no model and no MediaPipe.
The capture loop lives in :mod:`yazses.facegesture.backend`.
"""
from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING

from yazses.facegesture.calibration import Reading, normalise

if TYPE_CHECKING:  # pragma: no cover - typing only; this module stays camera-free
    from yazses.perception.signals import FaceSignal

#: Gesture name → the blendshape categories that evidence it. A gesture scores as
#: the **max** over its categories rather than the mean: a brow raise is often
#: asymmetric (one brow leads), and averaging a strong left against a weak right
#: halves the score of a movement the user did make.
GESTURES: dict[str, tuple[str, ...]] = {
    "jaw_open": ("jawOpen",),
    "brow_raise": ("browInnerUp", "browOuterUpLeft", "browOuterUpRight"),
    "mouth_pucker": ("mouthPucker",),
    "smile": ("mouthSmileLeft", "mouthSmileRight"),
    # Deliberately not offered as a default, but offered: a blink is the classic
    # switch, and for someone with no reliable jaw or brow control it may be the
    # only voluntary movement left. It needs a long `min_hold_frames` to separate
    # an intentional squeeze from the ~15 involuntary blinks a minute everyone makes.
    "eyes_closed": ("eyeBlinkLeft", "eyeBlinkRight"),
}

#: The default. Jaw-open is large, easy to hold, easy to release, and — unlike a
#: blink or a smile — almost never happens by accident while sitting at a screen.
DEFAULT_GESTURE = "jaw_open"


def gesture_names() -> tuple[str, ...]:
    """The supported gesture names, in a stable order. Pure."""
    return tuple(GESTURES)


def gesture_score(scores: Mapping[str, float], gesture: str) -> float | None:
    """Score ``gesture`` from one frame's blendshape ``scores``, or None. Pure.

    None means *no reading*, which is not the same as *not doing it*: an unknown
    gesture name, or a frame in which none of the gesture's categories were
    reported. :class:`GestureSwitch` treats that as a release candidate rather
    than as a held key — see :meth:`GestureSwitch.update`.
    """
    categories = GESTURES.get(gesture)
    if not categories:
        return None
    present = [scores[c] for c in categories if c in scores]
    return max(present) if present else None


def blendshape_scores(categories: Iterable) -> dict[str, float]:
    """Flatten MediaPipe's blendshape category list into ``{name: score}``. Pure.

    Accepts anything with ``category_name``/``score`` attributes, so the capture
    loop hands its result straight through and the tests hand fakes.
    """
    out: dict[str, float] = {}
    for c in categories or ():
        name = getattr(c, "category_name", None)
        score = getattr(c, "score", None)
        if name is None or score is None:
            continue
        out[str(name)] = float(score)
    return out


def gesture_reading(
    face: FaceSignal | None,
    gesture: str,
    *,
    now_s: float | None = None,
    max_age_s: float | None = None,
) -> Reading:
    """One shared-perception :class:`FaceSignal` as the switch's ``(score, confidence)``. Pure.

    This is the seam where a *missing channel* costs only the face switch. ``face is None``
    (no blendshape channel this observation), an unknown gesture, or a signal that did not
    report any of the gesture's categories all come back as ``Reading(None, None)`` -- "no
    reading", which the switch treats as a release candidate and never as a held key. Head
    pose and gaze are other channels of the same sample and are not touched.

    ``max_age_s`` is the freshness timeout: with both it and ``now_s`` given, a signal older
    than that is stale and also reads as no reading, so a camera that stopped delivering can
    never keep a gesture held on its last value. A signal stamped in the future is also
    refused (a clock fault, not freshness).
    """
    if face is None:
        return Reading(None, None)
    if max_age_s is not None and now_s is not None:
        age = float(now_s) - float(face.timestamp_s)
        if not math.isfinite(age) or age < 0.0 or age > float(max_age_s):
            return Reading(None, None)
    score = gesture_score(face.blendshapes, gesture)
    if score is None:
        return Reading(None, None)
    return Reading(score, float(face.confidence))


class GestureSwitch:
    """Debounced, hysteretic hold detector over a per-frame gesture score.

    Two thresholds, not one. A blendshape score is continuous and noisy, so a
    gesture held right at a single threshold crosses it several times a second,
    and each crossing would be a separate recording — a burst of one-word
    transcripts instead of one sentence. The mic opens at ``hold_threshold`` and
    closes only below ``release_threshold``; between them, nothing changes.

    Frame counts, not milliseconds, because the caller owns the frame rate.
    ``min_hold_frames`` is the Midas-touch defence: talking, laughing and yawning
    all spike ``jawOpen`` transiently, and a switch that fires on one frame fires
    on all of them. The latency it costs is affordable here specifically because
    the audio path prepends ``[accessibility] pre_speech_padding_ms`` of buffered
    audio, so the words spoken during the debounce are still in the recording.

    **Baseline.** Given ``baseline`` (the user's resting score for this gesture, from
    :mod:`yazses.facegesture.calibration`), the thresholds apply to the score
    *normalised* against it -- a fraction of the user's own headroom -- instead of to the raw
    number. ``None`` keeps the absolute behaviour exactly. A baseline with too little
    headroom to divide by makes the switch inert (and says so in :attr:`last_frame`): a
    face that rests at the top of the range cannot be told apart from a gesture, and
    guessing would hold the microphone open.

    **Confidence floor.** ``confidence_floor`` is a *second input*, ``update(score,
    confidence)``, deliberately not folded into the score. A frame whose landmarker
    confidence is below the floor is treated as having no reading: it can never count
    toward a hold, and while held it counts toward release through the same
    ``min_release_frames`` debounce. Zero (the default) disables the gate and ``confidence``
    is ignored. With a floor set, a missing confidence is *not* trusted.

    **Refractory.** ``refractory_frames`` frames after an ``"end"`` no score counts toward a
    new hold, so a gesture that bounces on release does not re-fire. Zero (the default) is
    the behaviour before this existed.

    **Maximum hold.** ``max_hold_s`` (seconds, default 0 = off) bounds how long one hold may
    stay open. It exists for one specific, checkable failure: a face whose *resting* score
    sits at or above ``release_threshold`` fires once and can never let go, which for
    hold-to-talk is a microphone open indefinitely. When a hold has lasted ``max_hold_s`` the
    switch emits one ordinary ``"end"`` (``last_end_reason == "max_hold"``) and **latches**:
    it counts no new hold until it has observed a real reading *below* ``release_threshold``,
    so a stuck switch cannot immediately re-fire. A frame with no reading never clears the
    latch (a camera dropout is not evidence the face relaxed). The clock is the caller's
    ``now_s`` -- this class reads none -- and without a finite ``now_s`` the limit is not
    enforced. It only ever *ends* a hold; nothing about it gates a release.
    """

    def __init__(
        self,
        hold_threshold: float = 0.5,
        release_threshold: float = 0.35,
        min_hold_frames: int = 3,
        min_release_frames: int = 2,
        *,
        baseline: float | None = None,
        confidence_floor: float = 0.0,
        refractory_frames: int = 0,
        max_hold_s: float = 0.0,
    ) -> None:
        hold = _clamp01(hold_threshold)
        release = _clamp01(release_threshold)
        # A release threshold at or above the hold threshold is not hysteresis at
        # all -- it is a single threshold with an extra name, and it chatters. It
        # is repaired rather than rejected (a bad number must not cost someone
        # their only input method) and recorded so the backend can say so once.
        self.repaired_release = release >= hold
        if self.repaired_release:
            release = hold * 0.7
        self._hold_threshold = hold
        self._release_threshold = release
        self._min_hold = max(1, int(min_hold_frames))
        self._min_release = max(1, int(min_release_frames))
        self._baseline = baseline
        # Probed with a mid-range score: normalise() refuses (None) exactly when the
        # baseline is non-finite, out of 0..1, or leaves less than MIN_HEADROOM of room.
        self.baseline_usable = baseline is None or normalise(0.5, baseline) is not None
        self._floor = _floor(confidence_floor)
        self._refractory = max(0, int(refractory_frames))
        self._cooldown = 0
        self._max_hold_s = _max_hold(max_hold_s)
        self._held_since: float | None = None
        self._latched = False
        self._held = False
        self._above = 0
        self._below = 0
        self._last_frame = "no_reading"
        self._last_end = ""

    @property
    def held(self) -> bool:
        """True while the gesture is being held (the mic is open)."""
        return self._held

    @property
    def thresholds(self) -> tuple[float, float]:
        """The effective ``(hold, release)`` thresholds after repair."""
        return self._hold_threshold, self._release_threshold

    @property
    def last_frame(self) -> str:
        """Why the latest frame counted as it did: ``"reading"``, ``"no_reading"``,
        ``"low_confidence"`` or ``"unusable_baseline"``. For status and tests; the three
        non-reading values are all treated as release candidates, never as a hold."""
        return self._last_frame

    @property
    def max_hold_s(self) -> float:
        """The effective maximum hold in seconds; 0.0 means the limit is off."""
        return self._max_hold_s

    @property
    def latched(self) -> bool:
        """True after a max-hold release, until a reading below ``release_threshold``."""
        return self._latched

    @property
    def last_end_reason(self) -> str:
        """Why the latest ``"end"`` happened: ``"release"``, ``"max_hold"`` or ``"reset"``.

        Empty before the first end. Read it right after :meth:`update` returned ``"end"``.
        """
        return self._last_end

    def update(
        self,
        score: float | None,
        confidence: float | None = None,
        now_s: float | None = None,
    ) -> str | None:
        """Advance one frame; return ``"start"``, ``"end"`` or None. Pure state.

        ``score`` is None when the frame produced no reading — no face in view,
        a dropped frame, a detector error. That counts toward *release*, never
        toward hold: if the user leaves the camera mid-hold, the alternative is a
        microphone that stays open until they come back. It goes through the same
        ``min_release_frames`` debounce as a low score, so one blurred frame in a
        held gesture does not cut the sentence in half.
        """
        value = self._frame_value(score, confidence)

        if self._latched:
            # Tripped by the maximum hold. Only a genuine reading below release re-arms: a
            # sentinel (no face, low confidence, unusable baseline) is not evidence that the
            # face relaxed, and the stuck state is exactly a score that never falls.
            if self._last_frame == "reading" and value < self._release_threshold:
                self._latched = False
            else:
                self._above = 0
                return None

        if self._held:
            if value < self._release_threshold:
                self._below += 1
                self._above = 0
                if self._below >= self._min_release:
                    return self._end("release")
            else:
                self._below = 0
            if self._over_max_hold(now_s):
                self._latched = True
                return self._end("max_hold")
            return None

        if self._cooldown > 0:
            self._cooldown -= 1
            self._above = 0
            return None

        if value >= self._hold_threshold:
            self._above += 1
            self._below = 0
            if self._above >= self._min_hold:
                self._held = True
                self._held_since = _finite_time(now_s)
                self._above = 0
                return "start"
        else:
            self._above = 0
        return None

    def _end(self, reason: str) -> str:
        self._held = False
        self._held_since = None
        self._below = 0
        self._above = 0
        self._cooldown = self._refractory
        self._last_end = reason
        return "end"

    def _over_max_hold(self, now_s: float | None) -> bool:
        """Has the open hold lasted ``max_hold_s``? False when off, untimed or the clock jumped back."""
        if self._max_hold_s <= 0.0:
            return False
        now = _finite_time(now_s)
        if now is None:
            return False
        if self._held_since is None:
            self._held_since = now  # the hold began on an untimed frame: start counting here
            return False
        return (now - self._held_since) >= self._max_hold_s

    def reset(self) -> str | None:
        """Drop any in-flight hold; return ``"end"`` if one was open. Pure state.

        Called when the capture loop stops, so a shutdown mid-gesture releases the
        key instead of leaving the daemon in RECORDING for ever.
        """
        self._above = self._below = 0
        self._cooldown = 0
        self._latched = False
        self._held_since = None
        if self._held:
            self._held = False
            self._last_end = "reset"
            return "end"
        return None

    def _frame_value(self, score: float | None, confidence: float | None) -> float:
        """The comparable value for one frame; -1.0 stands for "no usable reading".

        Everything that is not a trustworthy reading collapses to the one sentinel below
        every threshold, so it can only ever count toward release. Non-finite scores are
        in that set: NaN compares false against every threshold, so as a raw value it
        counted toward *neither* side and froze a held gesture (an open microphone) in
        place.
        """
        if not self.baseline_usable:
            self._last_frame = "unusable_baseline"
            return -1.0
        if self._floor > 0.0 and not (
            confidence is not None and _finite(confidence) and float(confidence) >= self._floor
        ):
            self._last_frame = "low_confidence"
            return -1.0
        value = normalise(score, self._baseline)
        if value is None:
            self._last_frame = "no_reading"
            return -1.0
        self._last_frame = "reading"
        return value


def _finite(value: object) -> bool:
    try:
        return math.isfinite(float(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False


def _finite_time(value: object) -> float | None:
    return float(value) if value is not None and _finite(value) else None  # type: ignore[arg-type]


def _max_hold(value: object) -> float:
    """A maximum hold in seconds; anything unreadable, negative or non-finite is 0.0 (off)."""
    if value is None or isinstance(value, bool) or not _finite(value):
        return 0.0
    return max(0.0, float(value))  # type: ignore[arg-type]


def _floor(value: object) -> float:
    """A confidence floor in 0..1; anything unreadable is 0.0 (gate off), not a lockout."""
    if not _finite(value):
        return 0.0
    return min(1.0, max(0.0, float(value)))  # type: ignore[arg-type]


def _clamp01(value: float) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.5
    if math.isnan(v):
        # NaN compares false against everything, so a NaN release threshold could never be
        # crossed and the hold it belongs to could never end. A non-number already falls back
        # to the default above; NaN does the same. (+-inf clamp to the ends, as before.)
        return 0.5
    return 0.0 if v < 0.0 else (1.0 if v > 1.0 else v)
