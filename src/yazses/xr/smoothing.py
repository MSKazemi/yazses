"""Ray stabiliser — a One-Euro filter for jittery eye and hand rays (pure).

Eye trackers and hand-tracking rays tremble: the signal is noisy while the user is
holding still and fast while they are really moving. A fixed low-pass cannot serve
both — smooth enough to hold still and it lags every real movement. The One-Euro
filter (Casiez, Roussel & Vogel, "1 € Filter: A Simple Speed-based Low-pass Filter
for Noisy Input in Interactive Systems", CHI 2012) adapts instead: the cutoff
frequency rises with the (itself low-passed) speed of the signal, so a still ray is
heavily smoothed and a fast sweep is barely delayed.

:class:`RayFilter` applies it to a ray's direction and origin. The filter is
stateful but fully deterministic: the clock is the sample's own ``timestamp_s``,
there is no I/O and no global state. :func:`dwell_progress` is the companion
read-out for dwell-select — how long the (smoothed) ray has stayed on a target.
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import replace

from yazses.xr.geometry import angle_between, normalize
from yazses.xr.types import Ray, Vec3, XrSample

# A speed estimate is clamped here. A pathological timestamp pair (dt of 1e-300) would
# otherwise yield an infinite derivative that the low-pass then remembers forever.
_MAX_SPEED = 1e12

# A smoothed direction shorter than this is treated as zero-length and refused.
_MIN_NORM = 1e-9

_Triple = tuple[float, float, float]


def _alpha(cutoff_hz: float, dt: float) -> float:
    """Smoothing factor in (0, 1] of a first-order low-pass with this cutoff."""
    if not math.isfinite(cutoff_hz):
        return 1.0
    tau = 1.0 / (2.0 * math.pi * cutoff_hz)
    return dt / (dt + tau)


def _triple(v: Vec3) -> _Triple:
    return (v.x, v.y, v.z)


def _clamp(value: float) -> float:
    return max(-_MAX_SPEED, min(_MAX_SPEED, value))


class _OneEuro3:
    """One-Euro filter over a 3-vector, with one shared cutoff for all components.

    The cutoff follows the *vector* speed, so a movement along one axis does not leave
    the other axes heavily smoothed (which would bend the path of a diagonal sweep).
    """

    def __init__(self, min_cutoff_hz: float, beta: float, d_cutoff_hz: float) -> None:
        self._min_cutoff = min_cutoff_hz
        self._beta = beta
        self._d_cutoff = d_cutoff_hz
        self._prev_raw: _Triple | None = None
        self._x_hat: _Triple = (0.0, 0.0, 0.0)
        self._dx_hat: _Triple = (0.0, 0.0, 0.0)

    @property
    def value(self) -> _Triple:
        return self._x_hat

    def seed(self, x: _Triple) -> _Triple:
        """Start from ``x``: the first sample of a stream passes through unchanged."""
        self._prev_raw = x
        self._x_hat = x
        self._dx_hat = (0.0, 0.0, 0.0)
        return x

    def step(self, x: _Triple, dt: float) -> _Triple:
        """Filter one sample ``dt`` seconds (> 0) after the previous one."""
        prev = self._prev_raw
        if prev is None:
            return self.seed(x)
        a_d = _alpha(self._d_cutoff, dt)
        dx = tuple(_clamp((x[i] - prev[i]) / dt) for i in range(3))
        dx_hat = tuple(a_d * dx[i] + (1.0 - a_d) * self._dx_hat[i] for i in range(3))
        speed = math.sqrt(sum(c * c for c in dx_hat))
        a = _alpha(self._min_cutoff + self._beta * speed, dt)
        x_hat = tuple(a * x[i] + (1.0 - a) * self._x_hat[i] for i in range(3))
        self._prev_raw = x
        self._x_hat = (x_hat[0], x_hat[1], x_hat[2])
        self._dx_hat = (dx_hat[0], dx_hat[1], dx_hat[2])
        return self._x_hat

    def restore(self, x_hat: _Triple) -> None:
        """Pin the smoothed value (used when a degenerate result was refused)."""
        self._x_hat = x_hat


class RayFilter:
    """Deterministic One-Euro stabiliser for a stream of :class:`XrSample` rays.

    ``min_cutoff_hz`` is the cutoff when the ray is still (lower = steadier, laggier),
    ``beta`` how fast the cutoff grows with speed (higher = less lag on fast moves),
    ``d_cutoff_hz`` the cutoff of the speed estimate itself. Speed is measured in
    unit-vectors per second for the direction (about radians per second) and metres
    per second for the origin. The defaults are the paper's starting values; tune
    ``min_cutoff_hz`` first, then ``beta``.

    Behaviour at the edges, fixed so callers can rely on it:

    * **First sample** of a stream passes through unchanged.
    * **Out-of-order or duplicate timestamps** (``timestamp_s`` not strictly after the
      last accepted sample) are returned *unfiltered* (RAW, with the device's unsmoothed
      ray) and the filter state is left untouched, so a late packet can neither corrupt
      the estimate nor rewind time. **The output stream can therefore mix smoothed and
      raw samples.** A caller that must not do so should check :attr:`passed_through_count`
      before and after :meth:`update` and drop the sample if it grew; the filter never
      drops one itself, because a dropped sample is a silent loss the caller never chose.
    * **A gap longer than** ``reset_gap_s`` resets the state; the sample after the gap
      is the new first sample. Smoothing across a tracking dropout would drag the ray
      from wherever it was before the user looked away.
    * **A zero-length smoothed direction** (the raw direction flipped by ~180 degrees
      and the average cancelled out) is refused: the last good direction is returned
      instead, and the state keeps its last good value.

    The output always has the input's timestamp, source and confidence; only the ray
    changes, and its direction is always unit length.
    """

    def __init__(
        self,
        min_cutoff_hz: float = 1.0,
        beta: float = 0.007,
        d_cutoff_hz: float = 1.0,
        reset_gap_s: float = 0.5,
    ) -> None:
        for name, value in (
            ("min_cutoff_hz", min_cutoff_hz),
            ("d_cutoff_hz", d_cutoff_hz),
            ("reset_gap_s", reset_gap_s),
        ):
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be a finite number > 0, got {value!r}")
        if not math.isfinite(beta) or beta < 0:
            raise ValueError(f"beta must be a finite number >= 0, got {beta!r}")
        self.min_cutoff_hz = min_cutoff_hz
        self.beta = beta
        self.d_cutoff_hz = d_cutoff_hz
        self.reset_gap_s = reset_gap_s
        self._direction = _OneEuro3(min_cutoff_hz, beta, d_cutoff_hz)
        self._origin = _OneEuro3(min_cutoff_hz, beta, d_cutoff_hz)
        self._last_t: float | None = None
        self._last_good_dir: Vec3 | None = None
        self._filtered_count = 0
        self._passed_through_count = 0

    @property
    def filtered_count(self) -> int:
        """Samples that went through the filter (incl. the first of a stream)."""
        return self._filtered_count

    @property
    def passed_through_count(self) -> int:
        """Late or duplicate samples returned raw. Survives :meth:`reset`."""
        return self._passed_through_count

    def reset(self) -> None:
        """Forget all history; the next sample is treated as the first."""
        self._direction = _OneEuro3(self.min_cutoff_hz, self.beta, self.d_cutoff_hz)
        self._origin = _OneEuro3(self.min_cutoff_hz, self.beta, self.d_cutoff_hz)
        self._last_t = None
        self._last_good_dir = None

    def update(self, sample: XrSample) -> XrSample:
        """Return ``sample`` with a smoothed ray (see the class docstring for edges)."""
        t = sample.timestamp_s
        if self._last_t is not None:
            dt = t - self._last_t
            if dt <= 0.0:
                self._passed_through_count += 1
                return sample  # late or duplicate: pass through RAW, state untouched
            if dt > self.reset_gap_s:
                self.reset()
        return self._filter(sample)

    def _filter(self, sample: XrSample) -> XrSample:
        self._filtered_count += 1
        ray = sample.ray
        dt = None if self._last_t is None else sample.timestamp_s - self._last_t
        self._last_t = sample.timestamp_s

        if dt is None:
            self._direction.seed(_triple(ray.direction))
            self._origin.seed(_triple(ray.origin))
            self._last_good_dir = ray.direction
            return sample

        ox, oy, oz = self._origin.step(_triple(ray.origin), dt)
        dx, dy, dz = self._direction.step(_triple(ray.direction), dt)
        smoothed = Vec3(dx, dy, dz)
        if math.hypot(dx, dy, dz) < _MIN_NORM:
            # Refuse a zero-length result: keep (and re-pin) the last good direction.
            assert self._last_good_dir is not None  # set by the first sample
            good = self._last_good_dir
            self._direction.restore(_triple(good))
        else:
            good = normalize(smoothed)
            self._last_good_dir = good
        return replace(sample, ray=Ray(origin=Vec3(ox, oy, oz), direction=good))


def dwell_progress(
    samples: Sequence[XrSample],
    centre_dir: Vec3,
    radius_rad: float,
    now_s: float,
    window_s: float = 1.0,
) -> float:
    """Fraction of the trailing ``window_s`` that the ray stayed within ``radius_rad``.

    Time-weighted over ``[now_s - window_s, now_s]``: each sample holds its direction
    until the next one (the last until ``now_s``). A ray counts as "on target" when its
    direction is within ``radius_rad`` of ``centre_dir`` (inclusive). Samples after
    ``now_s`` are ignored; input order does not matter. Time with no sample covering
    it — the window opens before the first sample — counts as *off* target, so dwell
    can only be earned by observed attention, never assumed.

    Returns a value in ``[0, 1]``; 1.0 means a full window on target (dwell complete).
    Feed it smoothed samples (:class:`RayFilter`) and reset the caller's sample list
    across tracking dropouts, since a held sample is trusted until the next arrives.
    """
    for name, value in (("radius_rad", radius_rad), ("now_s", now_s), ("window_s", window_s)):
        if not math.isfinite(value):
            raise ValueError(f"{name} must be finite, got {value!r}")
    if radius_rad < 0:
        raise ValueError("radius_rad must be >= 0")
    if window_s <= 0:
        raise ValueError("window_s must be > 0")
    # ``normalize`` scales first, so a huge or tiny (but non-zero) ``centre_dir`` is
    # fine; only a true zero vector is refused.
    try:
        centre = normalize(centre_dir)
    except ValueError:
        raise ValueError("centre_dir must be a non-zero vector") from None

    start = now_s - window_s
    ordered = sorted(
        (s for s in samples if s.timestamp_s <= now_s), key=lambda s: s.timestamp_s
    )
    inside_s = 0.0
    for i, s in enumerate(ordered):
        seg_start = max(s.timestamp_s, start)
        seg_end = ordered[i + 1].timestamp_s if i + 1 < len(ordered) else now_s
        seg_end = min(seg_end, now_s)
        if seg_end <= seg_start:
            continue
        if angle_between(s.ray.direction, centre) <= radius_rad:
            inside_s += seg_end - seg_start
    return max(0.0, min(1.0, inside_s / window_s))
