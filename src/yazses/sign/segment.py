"""Sign-burst presence + boundary detection (pure) — ADR-v2-054.

Decide when a sign burst starts and ends from per-frame hand presence + motion magnitude, so the
heavy SLR model runs on complete signing segments. Pure state machine; no camera or model here.
"""
from __future__ import annotations


def hands_present(num_hands: int) -> bool:
    """Whether any hands are detected this frame. Pure."""
    return num_hands > 0


class SignSegmenter:
    """Detect sign-burst ``start``/``end`` from per-frame hand motion. Pure state machine.

    Call :meth:`update` once per frame with the motion magnitude and hand count; it returns
    ``"start"`` on the frame a burst begins, ``"end"`` when it ends (sustained stillness or hands
    leaving the frame), else ``None``.
    """

    def __init__(self, start_threshold: float = 0.02, pause_frames: int = 8) -> None:
        self._start = start_threshold
        self._pause = pause_frames
        self._active = False
        self._still = 0

    def update(self, motion: float, num_hands: int):
        """Advance one frame; return ``"start"`` / ``"end"`` / ``None``. Pure state."""
        if not hands_present(num_hands):
            if self._active:
                self._active = False
                self._still = 0
                return "end"
            return None
        if not self._active:
            if motion >= self._start:
                self._active = True
                self._still = 0
                return "start"
            return None
        # active burst: count sustained stillness to detect the end
        if motion < self._start:
            self._still += 1
            if self._still >= self._pause:
                self._active = False
                self._still = 0
                return "end"
        else:
            self._still = 0
        return None
