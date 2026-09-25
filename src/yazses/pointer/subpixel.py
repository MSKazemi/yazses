"""Sub-pixel accumulation for backends whose native API only takes whole steps.

The pointer boundary in `src/yazses/pointer/base.py` speaks floats, because the thing
producing the intent is a head pose or a gaze estimate and its natural output is a
fraction of a pixel per frame. Two of the platform APIs behind that boundary do not:
Windows `SendInput` carries a `LONG` pixel delta, and CoreGraphics' scroll-wheel event
carries an `int32` line count. Rounding each call on its own would silently delete every
delta smaller than half a step — which is precisely the slow, careful motion a
motor-impaired user makes, so the pointer would move for a fast head turn and sit still
for a deliberate one.

This carries the remainder instead. ``take(0.4, 0.0)`` returns ``(0, 0)`` and keeps the
0.4; the next ``take(0.4, 0.0)`` returns ``(1, 0)`` and keeps -0.2. Nothing is dropped,
the residual never exceeds half a step in absolute value, and a stream of small deltas
comes out as the same total motion a stream of large ones would.

It is pure: no platform, no state beyond two floats, no clock. That is the point — the
numeric rule is identical on every backend and is tested directly rather than through a
native API fake.

**A taken step is spent.** :meth:`SubPixelAccumulator.take` subtracts before the caller
has emitted anything, so a platform call that then fails loses that motion rather than
folding it into the next one. That is ADR-v2-146's rule 4 ("a stale command is never
repeated after backend failure") expressed in arithmetic: re-offering the delta later
would be exactly the catch-up glide the rule exists to prevent.
"""

from __future__ import annotations

import math


class SubPixelAccumulator:
    """Turn a stream of float deltas into whole steps, carrying the remainder.

    One instance per axis pair and per purpose: motion and scroll must not share one,
    because their units are unrelated and a leftover half-pixel is not a leftover half
    notch.
    """

    __slots__ = ("_x", "_y")

    def __init__(self) -> None:
        self._x = 0.0
        self._y = 0.0

    @property
    def residual(self) -> tuple[float, float]:
        """The un-emitted remainder on each axis. Always within half a step of zero."""
        return self._x, self._y

    def take(self, dx: float, dy: float) -> tuple[int, int]:
        """Add ``(dx, dy)`` and return the whole steps now owed, keeping the rest.

        Raises :class:`ValueError` on a non-finite input. Every sink already validates
        with ``check_finite`` at its edge, but a NaN that reached here would poison the
        residual permanently — every later call would return ``(0, 0)`` and the pointer
        would stop for the rest of the session, with nothing in the logs. Refusing twice
        is cheaper than debugging that once.
        """
        if not math.isfinite(dx) or not math.isfinite(dy):
            raise ValueError(f"sub-pixel deltas must be finite, got ({dx!r}, {dy!r})")
        self._x += dx
        self._y += dy
        steps_x = int(round(self._x))
        steps_y = int(round(self._y))
        self._x -= steps_x
        self._y -= steps_y
        return steps_x, steps_y

    def reset(self) -> None:
        """Forget the remainder.

        Called when a sink closes: a residual kept across a close would apply a stale
        fraction of the last session's motion to the first call of the next one.
        """
        self._x = 0.0
        self._y = 0.0
