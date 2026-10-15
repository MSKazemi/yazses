"""Head-pose → cursor mapping + dwell click (pure) — ADR-v2-052.

Map head yaw/pitch to a cursor velocity (deadzone, linear, speed-capped; pointer units per
second, integrated over real time by the controller) and fire a click when the pointer dwells.
Pure math; the webcam/face-landmark capture lives behind the ``headpointer`` extra.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

#: Longest time step (seconds) one sample may be integrated over. A gap longer than this -- a
#: stalled runner thread, a camera that hiccuped without ever going stale -- is treated as this
#: long, so the pointer takes **one bounded step** rather than one giant jump. 0.25 s is the
#: period of a 4 fps camera: below that rate the model deliberately runs slow instead of
#: letting a missed frame become a leap. **Provisional:** a first-principles safety bound, not
#: a measured value.
DEFAULT_MAX_DT_S = 0.25


@dataclass(frozen=True)
class PointerCalib:
    """Gains, dead zone and speed caps mapping head angles (radians, centred) to pointer motion.

    **Rate control, in real time.** The head's offset from neutral sets the pointer's
    *velocity*, and the unit is pointer units per **second** per radian -- not per frame. The
    displacement of a sample is that velocity times the real time since the previous accepted
    sample, so the same head motion moves the pointer the same distance on a 15, 30 or 60 fps
    camera. (Before this, ``x_gain`` meant "per sample", which made the pointer twice as fast
    on a 30 fps camera as on a 15 fps one.)

    The response is *dead zone -> linear -> capped*: nothing inside ``deadzone`` radians, a
    straight line outside it, and a hard ceiling on speed. Each ceiling is in pointer units per
    second and cannot be switched off -- a head that is turned far, or a pose estimate that
    glitches, can never ask for more than the cap.

    **Every default here is provisional and unmeasured.** The caps are first-principles safety
    limits (cross a 1920-unit screen in a few seconds, a 1080-unit one in under two); the gains
    are chosen so a 0.3 rad turn, a comfortable one, runs at about half the cap. None comes
    from measuring a person, and none is a recommendation until it is (``GOVERNANCE.md``).
    """
    #: Pointer units per second per radian of yaw. The sign is geometry: see ``[headpointer]``.
    x_gain: float = 1200.0
    #: Pointer units per second per radian of pitch.
    y_gain: float = 900.0
    deadzone: float = 0.02
    #: Ceiling on horizontal speed, pointer units per second. Provisional.
    max_speed_x: float = 800.0
    #: Ceiling on vertical speed, pointer units per second. Provisional.
    max_speed_y: float = 600.0
    #: Ceiling on the combined speed (the length of the velocity vector). Provisional.
    max_speed_overall: float = 800.0


def pose_to_cursor(
    yaw: float, pitch: float, calib: PointerCalib = PointerCalib()
) -> tuple[float, float]:
    """Map centered head ``yaw``/``pitch`` to an ``(vx, vy)`` pointer *velocity*. Pure.

    The result is in pointer units **per second** (the gains' unit), before any speed cap --
    see :func:`limit_velocity` -- and before it is multiplied by a time step.
    Angles within ``deadzone`` produce no motion (kills jitter around center).
    """
    def g(v: float, gain: float) -> float:
        return 0.0 if abs(v) < calib.deadzone else v * gain

    return (g(yaw, calib.x_gain), g(pitch, calib.y_gain))


def limit_velocity(
    vx: float, vy: float, calib: PointerCalib = PointerCalib()
) -> tuple[float, float]:
    """Clamp a velocity to the per-axis caps, then to the overall cap. Pure.

    Each axis is clamped on its own; if the result is still faster than ``max_speed_overall`` the whole
    vector is scaled down, which keeps its direction (a diagonal does not bend towards an axis).
    A non-finite component is returned untouched so the caller's finiteness guard sees it.
    Caps are expected positive and finite -- the controller enforces that.
    """
    if not (math.isfinite(vx) and math.isfinite(vy)):
        return (vx, vy)
    vx = max(-calib.max_speed_x, min(calib.max_speed_x, vx))
    vy = max(-calib.max_speed_y, min(calib.max_speed_y, vy))
    speed = math.hypot(vx, vy)
    if speed > calib.max_speed_overall:
        scale = calib.max_speed_overall / speed
        vx, vy = vx * scale, vy * scale
    return (vx, vy)


def elapsed_s(previous_ts: float, ts: float, max_dt: float = DEFAULT_MAX_DT_S) -> float:
    """Seconds to integrate over between two sample timestamps. Pure and total.

    The real gap, clamped to ``max_dt``. A zero, negative or non-finite gap (a repeated or
    backwards clock, a NaN, or no previous sample at all) is **0.0**: no time passed that the
    pointer may be moved for. Never raises.
    """
    dt = ts - previous_ts
    if not math.isfinite(dt) or dt <= 0.0:
        return 0.0
    return min(dt, max_dt) if math.isfinite(max_dt) and max_dt > 0.0 else 0.0


class DwellClicker:
    """Fire a click when the pointer stays within ``radius`` px for ``hold_s`` seconds.

    Pure state machine (no I/O, no clock of its own): call :meth:`update` once per accepted
    sample with that sample's timestamp; it returns True on the sample the dwell completes,
    then re-arms. **Time, not frames**: the hold is the sum of the real gaps between samples
    that stayed inside the radius, so it lasts the same on a 15 and a 30 fps camera.

    Stillness has to be *observed* to count. A gap longer than ``max_dt_s`` between two samples
    (a stalled thread, a camera hiccup that never went stale) is time during which nobody saw
    the pointer, so it restarts the dwell at the new sample instead of being credited -- a stall
    can never complete a dwell by itself. A gap that is zero, negative or not a number (a clock
    fault) restarts it too.
    """

    def __init__(
        self, radius: float = 15.0, hold_s: float = 0.7, max_dt_s: float = DEFAULT_MAX_DT_S
    ) -> None:
        self._radius2 = radius * radius
        self._hold = hold_s
        self._max_dt = max_dt_s
        self._anchor: tuple[float, float] | None = None
        self._last_ts = 0.0
        self._elapsed = 0.0

    @property
    def progress(self) -> float:
        """How far the dwell in progress has got, ``0.0`` (none) towards ``1.0``.

        Read-only and pure, so a caller can show the user that a click is coming *before* it
        fires (ADR-v2-052 / #405). The sample that would complete it is the one on which
        :meth:`update` fires and re-arms, so the value read between samples stays below ``1.0``.
        """
        if self._anchor is None or not self._hold > 0.0:
            return 0.0
        return min(self._elapsed / self._hold, 1.0)

    @property
    def radius(self) -> float:
        """The dwell radius in pixels."""
        return self._radius2 ** 0.5

    @property
    def hold_s(self) -> float:
        """The hold time in seconds."""
        return self._hold

    def reset(self) -> None:
        """Drop any dwell in progress, so the next sample starts a fresh one.

        The hands-free safety gate (``handsfree/safety.py``, ADR-v2-148) requires that entering
        PAUSED or FAULTED clears pending activation state: without this, a dwell that was
        nearly complete when the camera dropped out would finish on the first sample after
        recovery, as a click the user never asked for. Pure; no I/O.
        """
        self._anchor = None
        self._elapsed = 0.0

    def _restart(self, x: float, y: float, ts: float) -> None:
        self._anchor = (x, y)
        self._last_ts = ts
        self._elapsed = 0.0

    def update(self, x: float, y: float, ts: float) -> bool:
        """Advance to the sample at ``ts`` (seconds, monotonic) with the pointer at ``(x, y)``.

        Returns True iff a click fires. Pure state.
        """
        if not math.isfinite(ts):
            self.reset()
            return False
        if self._anchor is None:
            self._restart(x, y, ts)
            return False
        dt = ts - self._last_ts
        if not (0.0 < dt <= self._max_dt):
            self._restart(x, y, ts)
            return False
        ax, ay = self._anchor
        if (x - ax) ** 2 + (y - ay) ** 2 > self._radius2:
            self._restart(x, y, ts)
            return False
        self._last_ts = ts
        self._elapsed += dt
        if self._elapsed >= self._hold:
            self.reset()
            return True
        return False
