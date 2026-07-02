"""Head-pose → cursor mapping + dwell click (pure) — ADR-v2-052.

Map head yaw/pitch to a cursor delta (with a deadzone) and fire a click when the pointer dwells.
Pure math; the webcam/face-landmark capture lives behind the ``headpointer`` extra.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PointerCalib:
    """Gains + deadzone mapping head angles (radians, centered) to pixels/frame."""
    x_gain: float = 800.0
    y_gain: float = 600.0
    deadzone: float = 0.02


def pose_to_cursor(yaw: float, pitch: float, calib: PointerCalib = PointerCalib()):
    """Map centered head ``yaw``/``pitch`` to a ``(dx, dy)`` cursor delta. Pure.

    Angles within ``deadzone`` produce no motion (kills jitter around center).
    """
    def g(v: float, gain: float) -> float:
        return 0.0 if abs(v) < calib.deadzone else v * gain

    return (g(yaw, calib.x_gain), g(pitch, calib.y_gain))


class DwellClicker:
    """Fire a click when the pointer stays within ``radius`` px for ``hold_frames`` frames.

    Pure state machine (no I/O): call :meth:`update` once per frame; it returns True on the frame
    the dwell completes, then re-arms.
    """

    def __init__(self, radius: float = 15.0, hold_frames: int = 20) -> None:
        self._radius2 = radius * radius
        self._hold = hold_frames
        self._anchor = None
        self._count = 0

    def update(self, x: float, y: float) -> bool:
        """Advance one frame at pointer ``(x, y)``; return True iff a click fires. Pure state."""
        if self._anchor is None:
            self._anchor = (x, y)
            self._count = 1
            return False
        ax, ay = self._anchor
        if (x - ax) ** 2 + (y - ay) ** 2 <= self._radius2:
            self._count += 1
            if self._count >= self._hold:
                self._anchor = None
                self._count = 0
                return True
        else:
            self._anchor = (x, y)
            self._count = 1
        return False
