"""The webcam behind the shared source, as the narrowest thing a camera can be.

``src/yazses/perception/source.py`` counts camera opens because ADR-v2-145's
architectural gate is a number — one physical camera owner per daemon, whatever
happens to be enabled. That count is only worth something if the object it counts
is the one that actually touches the device, which is this: an ``open`` that builds
exactly one ``cv2.VideoCapture``, a ``read`` that returns a frame or ``None``, and a
``close`` that releases it.

There is deliberately nothing else here. No conversion (the processor does that,
because it is the half that knows what the model wants), no retry (the source
contains failures and the user is told), no resolution or format negotiation (that
is tuning, and tuning belongs with the measurement the ADR asks for). Everything
this module could usefully grow is something another file already owns.

``cv2`` is the ``gaze`` extra and is imported inside :meth:`OpenCVFrameCapture.open`
(AGENTS.md rule 3): a base install imports this module fine and only opening a
camera needs the package, which is exactly the point at which a missing extra is a
thing the user can be told about.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable

__all__ = ["STALL_TIMEOUT_S", "OpenCVFrameCapture", "opencv_capture_factory"]

log = logging.getLogger(__name__)

#: Seconds without a single good frame before the camera is declared gone.
#: PROVISIONAL -- chosen, not measured. It has to outlast a webcam's warm-up (auto
#: exposure and focus settle in ~1-2 s on the cameras in common use) and still be short
#: enough that a pulled cable or a device another program took is reported while the user
#: is looking. It is a module constant and not a config key on purpose: a new key is a
#: public-interface change (AGENTS.md, L3), and a number nobody has measured should not be
#: one. Uses the monotonic clock, which does not advance across a suspend, so a laptop
#: that sleeps and wakes is not misread as a stall.
STALL_TIMEOUT_S = 5.0

#: Said when the OS probe could not add anything.
_GENERIC_OPEN_FAILURE = (
    "it may be in use by another application, or the OS may not have granted "
    "camera permission"
)


def _default_explain() -> str:
    """Ask `cameraperm` why, after a failure. Imported here: it is the failure path."""
    from yazses.cameraperm import explain_open_failure

    return explain_open_failure()


class OpenCVFrameCapture:
    """``FrameCapture`` over one ``cv2.VideoCapture``. One device, opened once.

    Constructing it touches nothing — the device is acquired by :meth:`open`, which
    is what lets the source open the camera on the first lease rather than on the
    first daemon start.
    """

    def __init__(
        self,
        index: int = 0,
        *,
        explain: Callable[[], str] | None = None,
        clock: Callable[[], float] = time.monotonic,
        stall_s: float = STALL_TIMEOUT_S,
    ) -> None:
        self._index = int(index)
        self._capture: object | None = None
        self._explain = explain if explain is not None else _default_explain
        self._clock = clock
        self._stall_s = float(stall_s)
        #: When the stream last proved itself, or when it was opened. Reset by a good
        #: frame; a run of dropped frames longer than ``stall_s`` past it is a dead camera.
        self._last_good = 0.0

    def __repr__(self) -> str:
        return f"OpenCVFrameCapture(index={self._index}, open={self._capture is not None})"

    @property
    def index(self) -> int:
        """Which camera this capture is for — the configured device index."""
        return self._index

    def open(self) -> None:
        """Acquire the device, or raise with a reason the source can report.

        Opening an already-open capture is a no-op rather than a second device: the
        source opens once per lifetime of an open and this class is the last place
        that could turn a bookkeeping slip into two camera handles.

        ``cv2.VideoCapture`` does not raise for a camera that is missing, busy or
        refused by the OS — it returns an object whose ``isOpened()`` is false — so
        that is checked and turned into an exception here. Left unchecked it would
        be a source that looks ``RUNNING`` and reads nothing but dropped frames,
        which is the failure mode that tells the user nothing.
        """
        if self._capture is not None:
            return
        try:
            import cv2  # noqa: PLC0415 - optional extra, needed only to open a camera
        except ImportError:
            raise OSError(
                f"camera {self._index} could not be opened — "
                f"{self._why('the camera runtime (opencv) is not installed')}"
            ) from None

        capture = cv2.VideoCapture(self._index)
        if not capture.isOpened():
            _release(capture)
            raise OSError(
                f"camera {self._index} could not be opened — {self._why(_GENERIC_OPEN_FAILURE)}"
            )
        self._capture = capture
        self._last_good = self._clock()

    def _why(self, fallback: str) -> str:
        """The OS-aware reason after a failure, or *fallback* when nothing could be learned.

        Asked after the attempt and never before: see
        :func:`yazses.cameraperm.explain_open_failure` for why the order matters on macOS.
        """
        try:
            return self._explain() or fallback
        except Exception:  # noqa: BLE001 - an error path must not raise a second error
            return fallback

    def read(self) -> object | None:
        """One frame, or ``None`` for a dropped frame or a capture that is not open.

        ``None`` rather than an exception for a failed read: a webcam that misses a
        frame is ordinary, and the source's contract makes that the cheap path.
        """
        capture = self._capture
        if capture is None:
            return None
        ok, frame = capture.read()  # type: ignore[attr-defined]
        now = self._clock()
        if ok:
            self._last_good = now
            return frame
        # A failed read is a dropped frame -- until it is not. OpenCV reports an
        # unplugged camera, a device another program has taken and a stream that never
        # started all as the same `(False, None)`, forever, and the source would sit
        # RUNNING and silent. Two checks turn that into the one thing the contract allows
        # a capture to raise for: "the device itself has gone".
        if not capture.isOpened():  # type: ignore[attr-defined]
            raise OSError(
                f"camera {self._index} disconnected — "
                f"{self._why('it was unplugged or taken by another application')}"
            )
        if now - self._last_good > self._stall_s:
            raise OSError(
                f"camera {self._index} delivered no frame for {self._stall_s:g}s — "
                f"{self._why('it was unplugged or taken by another application')}"
            )
        return None

    def close(self) -> None:
        """Release the device. Idempotent, and never raises into the source."""
        capture, self._capture = self._capture, None
        self._last_good = 0.0
        if capture is not None:
            _release(capture)


def opencv_capture_factory(index: int) -> OpenCVFrameCapture:
    """A ``CaptureFactory``: camera index in, an **unopened** capture out."""
    return OpenCVFrameCapture(index)


def _release(capture: object) -> None:
    """Hand the device back, without letting that failure hide the one that caused it."""
    try:
        capture.release()  # type: ignore[attr-defined]
    except Exception as exc:
        log.debug("perception: %s releasing the camera", type(exc).__name__)
