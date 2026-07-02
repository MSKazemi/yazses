"""Vocal-joystick mapping + velocity integrator (pure) — ADR-v2-095.

Map (F1, F2) formants to a direction, direction+loudness to a velocity, and integrate frames into a
position with click-on-pitch-jump. Pure and deterministic; the formant/pitch tracker is the lazy
extra.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

# Speaker-general formant midpoints (Hz): F1 close↔open, F2 back↔front.
F1_MID = 550.0
F2_MID = 1500.0

_DIR = {
    (0, 0): None,
    (0, 1): "up", (0, -1): "down", (1, 0): "right", (-1, 0): "left",
    (1, 1): "ne", (-1, 1): "nw", (1, -1): "se", (-1, -1): "sw",
}
_S = 1.0 / math.sqrt(2.0)
_UNIT = {
    "up": (0.0, -1.0), "down": (0.0, 1.0), "left": (-1.0, 0.0), "right": (1.0, 0.0),
    "ne": (_S, -_S), "nw": (-_S, -_S), "se": (_S, _S), "sw": (-_S, _S),
}


def vowel_to_direction(formants, deadzone=(60.0, 200.0)):
    """Map an (F1, F2) formant pair to an 8-way direction, or ``None`` near centre. Pure.

    Low F1 (close vowel) → up, high F1 (open) → down; high F2 (front) → left, low F2 (back) → right.
    """
    f1, f2 = formants
    dz1, dz2 = deadzone
    v = 1 if f1 < F1_MID - dz1 else (-1 if f1 > F1_MID + dz1 else 0)
    h = -1 if f2 > F2_MID + dz2 else (1 if f2 < F2_MID - dz2 else 0)
    return _DIR[(h, v)]


def vocal_control_vector(vowel_dir, loudness, pitch=0.0, max_speed=20.0):
    """Return the ``(vx, vy)`` velocity for a direction scaled by loudness. Pure.

    ``pitch`` is accepted for signature symmetry; click detection lives in :class:`VocalJoystick`.
    """
    unit = _UNIT.get(vowel_dir)
    if unit is None:
        return (0.0, 0.0)
    speed = max(0.0, min(1.0, loudness)) * max_speed
    return (unit[0] * speed, unit[1] * speed)


@dataclass(frozen=True)
class ControlEvent:
    """An emitted control action: ``kind`` in ``move|click|idle`` with a delta."""
    kind: str
    dx: float
    dy: float


class VocalJoystick:
    """Integrates per-frame (direction, loudness, pitch) into a position. Pure state."""

    def __init__(self, max_speed: float = 20.0, click_pitch: float = 250.0,
                 click_jump: float = 30.0) -> None:
        self._x = 0.0
        self._y = 0.0
        self._max = max_speed
        self._click_pitch = click_pitch
        self._click_jump = click_jump
        self._prev_pitch = None

    def position(self):
        return (self._x, self._y)

    def feed(self, vowel_dir, loudness, pitch=0.0) -> ControlEvent:
        """Consume one frame and emit a :class:`ControlEvent`. Pure state."""
        prev = self._prev_pitch
        self._prev_pitch = pitch
        if prev is not None and pitch >= self._click_pitch and pitch - prev > self._click_jump:
            return ControlEvent("click", 0.0, 0.0)
        vx, vy = vocal_control_vector(vowel_dir, loudness, pitch, self._max)
        if vx == 0.0 and vy == 0.0:
            return ControlEvent("idle", 0.0, 0.0)
        self._x += vx
        self._y += vy
        return ControlEvent("move", vx, vy)
