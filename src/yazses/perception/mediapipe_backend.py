"""One FaceLandmarker, three channels — the shared source's model half (EYE-CAM-002).

``src/yazses/perception/source.py`` owns the camera and asks a ``FrameProcessor``
what is in each frame. This is that processor, and it is the object ADR-v2-145
exists to make singular: **one** MediaPipe FaceLandmarker instance, built once per
camera open, whose single ``detect`` call answers gaze, head pose and face
blendshapes together.

Before this, each feature that wanted one of those three built its own landmarker
over its own camera — ``gaze/mediapipe_backend.py`` and ``facegesture/backend.py``
still do, until #396 moves them across. Two models over two devices is not only
twice the CPU: the two results describe the face at two different instants, so a
gaze reading and a jaw-open reading could never be said to belong to the same
moment. Here they share one frame and therefore one timestamp, which is the whole
reason a shared source is worth its complexity.

**Nothing here decides anything about a channel's numbers.** The arithmetic is in
``src/yazses/perception/derive.py``, which imports no camera and no model, so every
branch below is reachable in a test with a list of floats. This file is the glue:
build the model, hand it a frame, ask the pure functions for each channel, and drop
the frame.

## Degradation is per channel, by construction

ADR-v2-145 invariant 6 — one channel failing must not take the others with it — is
the criterion easiest to lose here, because the natural shape ("derive everything,
one try/except") loses all three the moment one raises. So each channel is derived
in its own guarded step: a transform that MediaPipe did not send, or sent broken,
costs head pose and nothing else, and a blendshape list that cannot be read costs
the face channel and nothing else. ``PerceptionSample.channels`` then says which
survived, and a sample is published whenever at least one did.

## What it costs to ask for all three

The two extra outputs are not free — the ADR says so and asks for measurement
rather than assumption. They are on by default anyway, because the processor is
built when the *first* consumer takes a lease and a second consumer can join the
same open a moment later: a processor narrowed to the first consumer's channel
would leave the second one silently blind for the life of that open. A caller that
knows the whole consumer set for the whole open may narrow it with ``channels``.

## Optional dependencies

``cv2`` and ``mediapipe`` are the ``gaze`` extra and are imported **inside** the
constructor (AGENTS.md rule 3), which runs when a camera is opened and never at
import. A base install with no extras imports this module fine; constructing it
raises ``ImportError``, which the source contains as a failed open with a reason.
"""
from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from typing import TypeVar

from yazses.perception.derive import derive_face, derive_gaze, derive_head_pose
from yazses.perception.signals import PerceptionSample

__all__ = [
    "CHANNELS",
    "DEFAULT_PRESENCE_CONFIDENCE",
    "MediapipeFaceProcessor",
    "mediapipe_processor_factory",
]

log = logging.getLogger(__name__)

#: What one guarded derivation returns — a channel's signal type.
_Signal = TypeVar("_Signal")

#: The channels one FaceLandmarker result can carry, in ``PerceptionSample`` order.
CHANNELS = ("gaze", "head_pose", "face")

#: The detection threshold the landmarker is built with, and — because MediaPipe's
#: result carries no per-face score — the confidence reported for the head-pose and
#: face channels. It is a **documented lower bound, not a measurement**: a face in
#: the result is one whose detection passed this, and that is all that is known.
#: Deliberately not ``1.0``, which would be an invented certainty of the kind
#: ``src/yazses/gaze/confidence.py`` was written to remove. The gaze channel does
#: better — its confidence is real, per-frame eye agreement — and giving the other
#: two a graded quality signal needs a backend that reports one, which is measurement
#: work (design/eye-control/ROADMAP.md), not something to invent at this seam.
DEFAULT_PRESENCE_CONFIDENCE = 0.5


class MediapipeFaceProcessor:
    """``FrameProcessor`` over one MediaPipe FaceLandmarker (gaze + head pose + face).

    One instance holds one model and is built once per camera open by the source's
    ``processor_factory``. It opens no camera, starts no thread and keeps no frame:
    a frame exists inside :meth:`process` and is gone when it returns.
    """

    def __init__(
        self,
        *,
        model_path: str = "",
        channels: Iterable[str] | None = None,
        presence_confidence: float = DEFAULT_PRESENCE_CONFIDENCE,
    ) -> None:
        """Build the one landmarker. Raises when the extra or the model is missing.

        ``model_path`` empty means "wherever the shipped resolver puts it", which is
        the same asset and the same policy the two feature backends already use —
        already downloaded, it is reused; absent, it is fetched once
        (``src/yazses/gaze/download.py``, the only outbound path here, registered in
        ADR-019). Nothing about inference is online afterwards.
        """
        import cv2  # noqa: PLC0415 - optional extra, imported when a camera opens
        import mediapipe as mp  # noqa: PLC0415
        from mediapipe.tasks import python  # noqa: PLC0415
        from mediapipe.tasks.python import vision  # noqa: PLC0415

        from yazses.gaze.download import ensure_face_landmarker  # noqa: PLC0415

        self._cv2 = cv2
        self._mp = mp
        self._channels = _channels(channels)
        self._presence = min(1.0, max(0.0, float(presence_confidence)))
        self._closed = False
        model = (model_path or "").strip() or str(ensure_face_landmarker())
        options = vision.FaceLandmarkerOptions(
            base_options=python.BaseOptions(model_asset_path=model),
            num_faces=1,
            # Asking for the two extra outputs is the whole of EYE-CAM-002 at the
            # MediaPipe layer: one result, three families. Requested only when a
            # channel wants them, because the ADR flags their cost as real.
            output_face_blendshapes="face" in self._channels,
            output_facial_transformation_matrixes="head_pose" in self._channels,
            # The same number this reports as the head-pose and face confidence, so
            # the floor it claims and the floor the detector enforces cannot drift.
            min_face_detection_confidence=self._presence,
            min_face_presence_confidence=self._presence,
            running_mode=vision.RunningMode.IMAGE,
        )
        #: The one model. Nothing else in this class builds a landmarker, which is
        #: what makes "one FaceLandmarker per open" countable rather than promised.
        self._landmarker = vision.FaceLandmarker.create_from_options(options)

    @property
    def name(self) -> str:
        """The backend name that appears in status and in ``doctor``."""
        return "mediapipe"

    @property
    def channels(self) -> tuple[str, ...]:
        """Which channels this processor was built to derive."""
        return self._channels

    def process(self, frame: object, timestamp_s: float) -> PerceptionSample | None:
        """Derive every requested channel from one frame, or ``None`` for no face.

        ``None`` is also the answer to a frame that could not be converted or an
        inference that raised: one bad frame must not end the source, because the
        source would take the user's camera-driven input method with it. The next
        frame is tried normally, and nothing is restamped in the meantime.
        """
        image = self._to_image(frame)
        if image is None:
            return None
        try:
            result = self._landmarker.detect(image)
        except Exception as exc:
            # The type name only, and no `exc_info`. A frame reaching a log is the
            # one privacy hole this seam could open (ADR-011), and an exception
            # from a model that was handed pixels is the plausible carrier.
            log.debug("perception: %s from face inference; frame skipped", type(exc).__name__)
            return None
        finally:
            del image

        landmarks = _first(getattr(result, "face_landmarks", None))
        matrix = _first(getattr(result, "facial_transformation_matrixes", None))
        categories = _first(getattr(result, "face_blendshapes", None))

        # Three independent steps. Each one's failure is its own channel's failure —
        # the guard is here rather than around the group precisely because a group
        # guard is how a missing transform ends up costing gaze as well.
        gaze = self._derive("gaze", derive_gaze, landmarks, timestamp_s)
        head_pose = self._derive("head_pose", derive_head_pose, matrix, timestamp_s, self._presence)
        face = self._derive("face", derive_face, categories, timestamp_s, self._presence)
        if gaze is None and head_pose is None and face is None:
            return None
        return PerceptionSample(
            timestamp_s=timestamp_s, gaze=gaze, head_pose=head_pose, face=face
        )

    def close(self) -> None:
        """Release the model. Idempotent, and never raises into the source."""
        if self._closed:
            return
        self._closed = True
        close = getattr(self._landmarker, "close", None)
        if close is None:
            return
        try:
            close()
        except Exception as exc:
            log.debug("perception: %s while closing the face model", type(exc).__name__)

    # -- internals ---------------------------------------------------------- #

    def _to_image(self, frame: object) -> object | None:
        """The capture's frame as a MediaPipe image, or ``None`` if it cannot be.

        The conversion the two shipped backends already do — OpenCV hands back BGR,
        MediaPipe wants RGB — kept on this side of the seam so a capture stays the
        narrowest thing a camera can be.
        """
        try:
            rgb = self._cv2.cvtColor(frame, self._cv2.COLOR_BGR2RGB)
            return self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb)
        except Exception as exc:
            log.debug("perception: %s converting a frame; frame skipped", type(exc).__name__)
            return None

    def _derive(
        self, channel: str, derive: Callable[..., _Signal | None], *args: object
    ) -> _Signal | None:
        """One channel, or ``None`` — never an exception that could cost another.

        ``derive.py`` already answers ``None`` for every missing or malformed input
        it knows about. This exists for the ones it does not: a landmark object that
        raises from a property, a matrix type nobody anticipated, a bug in a
        derivation added later. Belt and braces, because the invariant it protects
        is a person's only input method and the failure is silent.
        """
        if channel not in self._channels:
            return None
        try:
            return derive(*args)
        except Exception as exc:
            log.debug(
                "perception: %s deriving the %s channel; that channel is skipped",
                type(exc).__name__, channel,
            )
            return None


def mediapipe_processor_factory(
    *,
    model_path: str = "",
    channels: Iterable[str] | None = None,
    presence_confidence: float = DEFAULT_PRESENCE_CONFIDENCE,
) -> Callable[[], MediapipeFaceProcessor]:
    """A zero-argument ``ProcessorFactory`` for ``build_perception_source``.

    The source builds a processor per camera open, so this returns the callable
    rather than the processor: nothing here touches MediaPipe until the first
    consumer takes a lease.
    """

    def build() -> MediapipeFaceProcessor:
        return MediapipeFaceProcessor(
            model_path=model_path, channels=channels, presence_confidence=presence_confidence
        )

    return build


def _channels(requested: Iterable[str] | None) -> tuple[str, ...]:
    """The requested channel names, in a stable order; ``None`` means all of them.

    An unknown name is dropped rather than raised on: this runs inside the source's
    open, where raising means a camera feature that will not start at all. A request
    that leaves nothing recognisable falls back to every channel, because a
    processor deriving nothing is a camera running for no reason.
    """
    if requested is None:
        return CHANNELS
    wanted = {str(name) for name in requested}
    unknown = sorted(wanted - set(CHANNELS))
    if unknown:
        log.debug("perception: ignoring unknown channel(s) %s", ", ".join(unknown))
    kept = tuple(name for name in CHANNELS if name in wanted)
    return kept or CHANNELS


def _first(items: object) -> object | None:
    """The first element of a per-face list, or ``None`` when there is not one.

    MediaPipe returns one list per detected face for each output, and an output that
    was not requested is an empty list rather than a missing attribute. ``None`` here
    is what makes that "this channel is absent" one step later.
    """
    try:
        return items[0] if items else None  # type: ignore[index]
    except (IndexError, KeyError, TypeError):
        return None
