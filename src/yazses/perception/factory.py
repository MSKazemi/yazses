"""Build the one camera owner from ``[perception]``, or build nothing at all.

The dormancy half of ADR-v2-145 invariant 2: *zero camera work when no camera
feature is enabled*. ``None`` is the shipped answer and it is not an error — the
caller treats it exactly as ``src/yazses/gaze/factory.py`` treats its own ``None``:
there is no shared source, so nothing asks it for a lease, and no code path in the
daemon reaches a device.

Nothing here imports OpenCV, MediaPipe, a model or ``yazses.config``. The camera
and the model arrive as factories from whoever wires this up, which is what lets
the lifecycle be tested with numbers and keeps the optional extras out of a base
install (AGENTS.md rule 3). The config object is duck-typed for the same reason the
gaze factory duck-types its own: a test should be able to pass a stub section
without constructing the whole 100-section config.
"""
from __future__ import annotations

import logging
from collections.abc import Callable

from yazses.perception.source import FrameCapture, FrameProcessor, SharedPerceptionSource

__all__ = ["CaptureFactory", "ProcessorFactory", "build_perception_source"]

log = logging.getLogger(__name__)

#: A camera index in, an **unopened** capture out. The index comes from
#: ``[perception] camera_index`` so that the one owner is the one thing that
#: decides which device is opened.
CaptureFactory = Callable[[int], FrameCapture]

#: Builds the model that derives signals from frames, once per camera open.
ProcessorFactory = Callable[[], FrameProcessor]

#: Frame rate used when the section carries nothing usable, and the bounds it is
#: held to. 0 would divide by zero and a negative interval would spin a core.
DEFAULT_FPS = 15
MIN_FPS = 1
MAX_FPS = 60


def build_perception_source(
    config,
    *,
    capture_factory: CaptureFactory | None = None,
    processor_factory: ProcessorFactory | None = None,
) -> SharedPerceptionSource | None:
    """Return the shared camera source for the ``[perception]`` section, or ``None``.

    ``None`` means "no shared source", which is the case in three situations and
    none of them is a failure: the section is off (the shipped default), or no
    camera backend has been wired to it yet, or a caller deliberately passed only
    one half of the pair. In each, every camera feature keeps the path it has
    today, and no device is touched.

    Building a source still opens nothing. The camera is opened by the first
    consumer that takes a lease, so an install that enables this and enables no
    camera feature runs no capture loop at all.
    """
    if not getattr(config, "enabled", False):
        return None
    if capture_factory is None or processor_factory is None:
        log.debug(
            "[perception] is enabled but no shared camera backend is wired to it yet, "
            "so camera features keep their own path."
        )
        return None

    # Narrowed locals: the lambda below closes over these, and a closure over the
    # optional parameters would be a closure over something that could be None.
    open_capture: CaptureFactory = capture_factory
    build_processor: ProcessorFactory = processor_factory

    index = _int(getattr(config, "camera_index", 0), default=0)
    fps = min(MAX_FPS, max(MIN_FPS, _int(getattr(config, "fps", DEFAULT_FPS), DEFAULT_FPS)))
    return SharedPerceptionSource(
        capture_factory=lambda: open_capture(index),
        processor_factory=build_processor,
        interval_s=1.0 / fps,
    )


def _int(value: object, default: int) -> int:
    """*value* as an int, falling back to *default* rather than raising.

    The loader coerces types and ``doctor`` reports what it rejects, so a value
    this cannot read has already been reported once. Refusing it a second time
    here, by raising inside a factory whose whole contract is "returns None when
    there is nothing to build", would turn a typo into a daemon that does not start.
    """
    try:
        return int(value)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return default
