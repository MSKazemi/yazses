"""Glance-Type gaze on the shared camera source — the adapter, not a new feature (#396).

ADR-v2-145 puts one owner behind every camera feature, and says the existing
``GazeTargeter`` "should receive a small gaze-provider adapter so the routing/deixis
logic does not care whether samples came from shared webcam perception, the L2CS
backend, or a future dedicated eye tracker". This is that adapter.

:class:`SharedGazeBackend` is shaped exactly like the backend the targeter already
consumes (``estimate_sample`` / ``estimate`` / ``close``), so ``gaze/targeter.py``,
``gaze/route.py`` and the deixis path are untouched. What changes is who owns the
camera: the backend holds a **lease** on the shared source instead of a
``cv2.VideoCapture``, so enabling another camera feature cannot open a second device.

## What is preserved, deliberately

*The number.* The confidence a sample carries is the eye-agreement figure
``gaze/confidence.py`` has always computed, derived by the very function
(``perception/derive.py``) the legacy backend now calls too, so ``[gaze]
confidence_min`` gates exactly the same quantity. ``tests/test_gaze_glance_type_unchanged.py``
pins the two paths number for number.

*The lazy open.* The legacy backend opened the camera on the first sample, not at
daemon start. This one takes its lease on the first sample for the same reason: a
webcam light that comes on because gaze is *enabled*, rather than because a hold
asked, would be a visible change.

*The fallback.* No face, a low-confidence face, a failed camera and a sample that is
too old all answer ``None``, which the targeter already treats as "keep the focused
window". Nothing here invents a point.

## What necessarily differs, and why it is safe

The legacy backend read a frame *at hold time*. The shared source reads on its own
cadence, so what the adapter gets is the newest observation, which may be a few tens
of milliseconds old. :data:`MAX_SAMPLE_AGE_S` bounds that: an older observation is
treated as no observation, because routing dictation by where someone looked a
second ago is the wrong-window error this feature exists to avoid. The bound is a
documented starting point, not a measurement (see ``design/eye-control/``).

The first hold after the lease opens has no sample yet — the loop has not run — so
that one call waits briefly for the first observation instead of reporting "no face"
for a camera that simply has not warmed up. Only the call that opened the lease
waits; every later call is a plain read.

Nothing here imports OpenCV, MediaPipe or a thread: the lease arrives from outside.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

from yazses.gaze.confidence import GazeSample
from yazses.perception.signals import FacePerceptionSource

__all__ = [
    "FIRST_SAMPLE_WAIT_S",
    "MAX_SAMPLE_AGE_S",
    "SharedGazeBackend",
    "SharedSourceChoice",
    "shared_source_for_gaze",
]

log = logging.getLogger(__name__)

#: Oldest observation a hold may route on. At the source's default 15 fps a fresh
#: sample is ~70 ms old; this leaves room for a slow frame or two and nothing more.
#: **A starting bound, not a measured threshold.**
MAX_SAMPLE_AGE_S = 0.5

#: How long the call that opened the lease waits for the first observation. Bounded
#: because the caller is a key-hold handler: the legacy backend paid the camera-open
#: cost on its first call too, but it must never become an unbounded wait.
FIRST_SAMPLE_WAIT_S = 1.0

_POLL_S = 0.01


class SharedGazeBackend:
    """``GazeBackend`` over a lease on the shared perception source."""

    def __init__(
        self,
        lease: FacePerceptionSource,
        *,
        max_age_s: float = MAX_SAMPLE_AGE_S,
        first_sample_wait_s: float = FIRST_SAMPLE_WAIT_S,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        failure_reason: Callable[[], str] | None = None,
    ) -> None:
        """*clock* must be the same monotonic clock the source stamps samples with
        (``time.monotonic`` unless the source was built with another), because age is
        a difference between the two. *failure_reason* returns why the source stopped,
        or ``""``; it is read only to explain, once, why gaze has nothing to say."""
        self._lease = lease
        self._max_age_s = max(0.0, float(max_age_s))
        self._first_wait_s = max(0.0, float(first_sample_wait_s))
        self._clock = clock
        self._sleep = sleep
        self._failure_reason = failure_reason
        self._started = False
        self._explained = False

    @property
    def name(self) -> str:
        # The backend *identity* users and docs know. The camera behind it is shared,
        # the estimator is still the MediaPipe iris offset.
        return "mediapipe"

    def estimate(self) -> tuple[float, float] | None:
        sample = self.estimate_sample()
        return None if sample is None else sample.point

    def estimate_sample(self) -> GazeSample | None:
        """The newest fresh gaze observation as a ``GazeSample``, or ``None``."""
        opened_now = False
        if not self._started:
            self._started = True
            opened_now = True
            self._lease.start()
        observation = self._lease.latest()
        if observation is None and opened_now:
            observation = self._wait_for_first()
        if observation is None:
            self._explain_if_failed()
            return None
        if self._clock() - observation.timestamp_s > self._max_age_s:
            # The face is gone or the camera stalled; the last frame is history.
            return None
        gaze = observation.gaze
        if gaze is None:
            return None
        return GazeSample(gaze.raw_x, gaze.raw_y, gaze.confidence)

    def close(self) -> None:
        """Release the lease; the last consumer out closes the camera."""
        self._started = False
        self._lease.stop()

    # -- internals ---------------------------------------------------------- #

    def _wait_for_first(self):
        deadline = self._clock() + self._first_wait_s
        while self._clock() < deadline:
            self._sleep(_POLL_S)
            observation = self._lease.latest()
            if observation is not None:
                return observation
            if self._failure_reason is not None and self._failure_reason():
                return None  # the source gave up; waiting out the clock helps no one
        return None

    def _explain_if_failed(self) -> None:
        """Say once, with the real reason, why gaze has nothing — the legacy factory did."""
        if self._explained or self._failure_reason is None:
            return
        reason = self._failure_reason()
        if not reason:
            return
        self._explained = True
        log.warning(
            "Gaze is enabled but the shared camera is not running: %s. Dictation "
            "stays on the focused window.",
            reason,
        )


@dataclass(frozen=True)
class SharedSourceChoice:
    """Whether gaze should lease the shared source, and the reason in words."""

    source: object | None
    reason: str


def shared_source_for_gaze(gaze_config, perception_config, source) -> SharedSourceChoice:
    """Decide whether Glance-Type gaze may use *source*; pure, nothing is opened.

    Gaze shares the camera only when sharing is *correct*:

    * there is a source at all (``[perception]`` on and a backend wired);
    * the gaze backend is the MediaPipe one — L2CS owns its own pipeline and keeps
      it, which ADR-v2-145 explicitly allows;
    * both sections name the **same camera**. Calibration is bound to the camera that
      produced it (ADR-v2-149), so leasing a different device from the one the
      calibration fingerprint names would route confidently from the wrong geometry.
      Different indexes are different physical cameras, so two owners there is correct
      rather than a contention.
    """
    if source is None:
        return SharedSourceChoice(None, "no shared camera source is configured")
    backend = str(getattr(gaze_config, "backend", "mediapipe") or "mediapipe")
    if backend != "mediapipe":
        return SharedSourceChoice(None, f"the {backend!r} gaze backend owns its own pipeline")
    gaze_index = getattr(gaze_config, "camera_index", 0)
    shared_index = getattr(perception_config, "camera_index", 0)
    if gaze_index != shared_index:
        return SharedSourceChoice(
            None,
            f"[gaze] camera_index = {gaze_index} but [perception] camera_index = "
            f"{shared_index}; they are different cameras, so gaze keeps its own",
        )
    return SharedSourceChoice(source, "gaze leases the shared camera source")
