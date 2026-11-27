"""Is the camera covered? The frame-based judgement, pure (#923).

A mechanical privacy shutter has no electronic signal on most laptops, so the only
evidence is the picture: almost black, and almost perfectly even. Both conditions are
needed. A dim room with a face lit by the screen is dark but not even, a blank wall is
even but not dark, and "no face in view" is neither -- none of them is a cover. And one
such frame proves nothing (a webcam warming up is black for a second or two), so the
picture has to stay that way, without a break, for :data:`COVER_AFTER_S`.

**Every threshold here is PROVISIONAL: chosen, not measured.** How dark and how even a
covered sensor reads depends on its gain and noise, and no set of webcams has been
measured. That is why ``[camera] cover_detection`` ships off, why the numbers err towards
*not* covered (a missed cover costs what it costs today; a false one pauses a hands-free
input), and why the daemon logs the two figures when it decides. A completely unlit room
with a dark screen looks the same as a cover to any camera, and is treated as one until
there is light again.

Pure: numbers and numpy arrays in, a verdict out. No camera, no thread, no clock of its
own, and nothing keeps a frame (ADR-011) -- only the two figures derived from it. numpy
is imported inside :func:`frame_stats`: every config load imports this package.
"""
from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "BLANK_MEAN_MAX",
    "BLANK_SPREAD_MAX",
    "CLEAR_FRAMES",
    "CLEAR_MEAN_MIN",
    "CLEAR_SPREAD_MIN",
    "COVER_AFTER_S",
    "MAX_GAP_S",
    "MIN_BLANK_FRAMES",
    "PROBE_BLANK",
    "PROBE_CLEAR",
    "PROBE_DELAY_S",
    "PROBE_MAX_DELAY_S",
    "PROBE_UNKNOWN",
    "PROBE_WINDOW_S",
    "CoverDetector",
    "FrameStats",
    "ProbeJudge",
    "frame_stats",
    "is_blank",
    "is_clear",
    "probe_delay",
]

#: A frame is blank when its mean luminance (0..255) is at most this ...
BLANK_MEAN_MAX = 16.0
#: ... and the standard deviation of its luminance is at most this.
BLANK_SPREAD_MAX = 5.0
#: A frame is clearly *not* blank above either of these. Higher than the pair above on
#: purpose: a picture sitting on one boundary must not cover and uncover for ever.
CLEAR_MEAN_MIN = 24.0
CLEAR_SPREAD_MIN = 8.0

#: Seconds of unbroken blank frames before the camera counts as covered.
COVER_AFTER_S = 5.0
#: And at least this many of them, so two stray readings cannot span the window.
MIN_BLANK_FRAMES = 5
#: A longer silence between frames restarts the run: a gap is not evidence.
MAX_GAP_S = 2.0

#: Consecutive clear frames a probe needs before the camera counts as uncovered, so one
#: garbage frame from a camera that has just been opened does not resume it.
CLEAR_FRAMES = 3
#: Longest a probe holds the camera. It has to outlast the auto-exposure warm-up.
PROBE_WINDOW_S = 3.0
#: Wait before the first probe of a covered camera; each blank one doubles it ...
PROBE_DELAY_S = 5.0
#: ... up to this, so a camera left covered all day is opened rarely.
PROBE_MAX_DELAY_S = 30.0

PROBE_CLEAR = "clear"
PROBE_BLANK = "blank"
#: The probe got no frame at all (another app has the camera). Not evidence either way.
PROBE_UNKNOWN = "unknown"

#: Every Nth row and column is read: the two figures do not need every pixel.
_STRIDE = 4


@dataclass(frozen=True)
class FrameStats:
    """The two figures a frame is reduced to. Nothing of the picture survives them."""

    mean: float
    #: Standard deviation of the luminance.
    spread: float


def frame_stats(frame: object) -> FrameStats | None:
    """*frame* (an 8-bit grayscale or BGR array) as :class:`FrameStats`, or ``None``.

    ``None`` for anything that is not such a picture: the thresholds are on a 0..255
    scale, and a verdict on numbers of unknown scale would be a guess.
    """
    import numpy as np  # noqa: PLC0415 - see the module docstring

    if not isinstance(frame, np.ndarray) or frame.dtype != np.uint8:
        return None
    if frame.ndim not in (2, 3) or frame.size == 0:
        return None
    sample = frame[::_STRIDE, ::_STRIDE]
    if sample.ndim == 2:
        luma = sample.astype(np.float32)
    elif sample.shape[2] >= 3:
        luma = (
            sample[..., 0] * np.float32(0.114)
            + sample[..., 1] * np.float32(0.587)
            + sample[..., 2] * np.float32(0.299)
        )
    else:
        luma = sample[..., 0].astype(np.float32)
    return FrameStats(float(luma.mean()), float(luma.std()))


def is_blank(stats: FrameStats) -> bool:
    """Dark **and** even: what a covered sensor reads."""
    return stats.mean <= BLANK_MEAN_MAX and stats.spread <= BLANK_SPREAD_MAX


def is_clear(stats: FrameStats) -> bool:
    """Bright enough or varied enough that the sensor is certainly seeing something."""
    return stats.mean > CLEAR_MEAN_MIN or stats.spread > CLEAR_SPREAD_MIN


class CoverDetector:
    """One camera's run of blank frames. Feed it frames with a monotonic time."""

    def __init__(
        self,
        *,
        after_s: float = COVER_AFTER_S,
        min_frames: int = MIN_BLANK_FRAMES,
        max_gap_s: float = MAX_GAP_S,
    ) -> None:
        self._after_s = float(after_s)
        self._min_frames = int(min_frames)
        self._max_gap_s = float(max_gap_s)
        self.reset()

    def reset(self) -> None:
        self._since: float | None = None
        self._last: float | None = None
        self._count = 0

    def observe(self, stats: FrameStats, now_s: float) -> bool:
        """Count one frame; ``True`` once the camera has been blank long enough."""
        gap = self._last is not None and now_s - self._last > self._max_gap_s
        self._last = now_s
        if not is_blank(stats):
            self._since = None
            self._count = 0
            return False
        if gap or self._since is None:
            self._since = now_s
            self._count = 0
        self._count += 1
        return self._count >= self._min_frames and now_s - self._since >= self._after_s


class ProbeJudge:
    """The verdict on a short look at a covered camera."""

    def __init__(self, *, clear_frames: int = CLEAR_FRAMES) -> None:
        self._needed = int(clear_frames)
        self._run = 0
        self._seen = 0

    def feed(self, stats: FrameStats | None) -> bool:
        """Count one frame; ``True`` when the answer is settled as clear."""
        if stats is not None:
            self._seen += 1
            self._run = self._run + 1 if is_clear(stats) else 0
        return self._run >= self._needed

    @property
    def verdict(self) -> str:
        if self._run >= self._needed:
            return PROBE_CLEAR
        return PROBE_BLANK if self._seen else PROBE_UNKNOWN


def probe_delay(attempts: int) -> float:
    """Seconds to wait before the next probe after *attempts* that found no picture."""
    return min(PROBE_MAX_DELAY_S, PROBE_DELAY_S * 2 ** min(max(0, int(attempts)), 16))
