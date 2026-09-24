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

from collections.abc import Iterable, Mapping

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
    """

    def __init__(
        self,
        hold_threshold: float = 0.5,
        release_threshold: float = 0.35,
        min_hold_frames: int = 3,
        min_release_frames: int = 2,
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
        self._held = False
        self._above = 0
        self._below = 0

    @property
    def held(self) -> bool:
        """True while the gesture is being held (the mic is open)."""
        return self._held

    @property
    def thresholds(self) -> tuple[float, float]:
        """The effective ``(hold, release)`` thresholds after repair."""
        return self._hold_threshold, self._release_threshold

    def update(self, score: float | None) -> str | None:
        """Advance one frame; return ``"start"``, ``"end"`` or None. Pure state.

        ``score`` is None when the frame produced no reading — no face in view,
        a dropped frame, a detector error. That counts toward *release*, never
        toward hold: if the user leaves the camera mid-hold, the alternative is a
        microphone that stays open until they come back. It goes through the same
        ``min_release_frames`` debounce as a low score, so one blurred frame in a
        held gesture does not cut the sentence in half.
        """
        value = -1.0 if score is None else float(score)

        if self._held:
            if value < self._release_threshold:
                self._below += 1
                self._above = 0
                if self._below >= self._min_release:
                    self._held = False
                    self._below = 0
                    return "end"
            else:
                self._below = 0
            return None

        if value >= self._hold_threshold:
            self._above += 1
            self._below = 0
            if self._above >= self._min_hold:
                self._held = True
                self._above = 0
                return "start"
        else:
            self._above = 0
        return None

    def reset(self) -> str | None:
        """Drop any in-flight hold; return ``"end"`` if one was open. Pure state.

        Called when the capture loop stops, so a shutdown mid-gesture releases the
        key instead of leaving the daemon in RECORDING for ever.
        """
        self._above = self._below = 0
        if self._held:
            self._held = False
            return "end"
        return None


def _clamp01(value: float) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.5
    return 0.0 if v < 0.0 else (1.0 if v > 1.0 else v)
