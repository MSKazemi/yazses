"""Value contracts shared by every ``yazses.xr`` module (pure, immutable, validated).

Conventions, fixed here so no module has to guess:

* **Units** — metres and seconds. Angles are radians.
* **Handedness** — right-handed, +Y up, -Z forward (the OpenXR "local" convention).
  A device that reports another convention is converted at the seam
  (``xr.conventions``); nothing downstream ever sees it.
* **Time** — ``timestamp_s`` is monotonic seconds on the *desktop* clock; the wire
  layer maps the device clock onto it before a sample is built.
* **Validation** — every constructor refuses NaN/inf and out-of-range values. A bad
  number is a bug or hostile input at the seam, not something to clamp quietly.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum


def _finite(name: str, value: float) -> None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{name} must be a finite number, got {value!r}")
    try:
        finite = math.isfinite(value)
    except OverflowError:  # an int too large for a float
        finite = False
    if not finite:
        raise ValueError(f"{name} must be a finite number, got {value!r}"[:200])


def _unit_interval(name: str, value: float) -> None:
    _finite(name, value)
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be within [0, 1], got {value!r}")


def _identifier(name: str, value: str) -> None:
    if not isinstance(value, str) or not value or len(value) > 128 or not value.isprintable():
        raise ValueError(f"{name} must be a printable, non-empty string up to 128 characters")


@dataclass(frozen=True)
class Vec3:
    x: float
    y: float
    z: float

    def __post_init__(self) -> None:
        for n, v in (("x", self.x), ("y", self.y), ("z", self.z)):
            _finite(f"Vec3.{n}", v)


@dataclass(frozen=True)
class Ray:
    """A pointing ray. ``direction`` must already be unit length (tolerance 1e-6)."""

    origin: Vec3
    direction: Vec3

    def __post_init__(self) -> None:
        d = self.direction
        if abs(math.sqrt(d.x * d.x + d.y * d.y + d.z * d.z) - 1.0) > 1e-6:
            raise ValueError("Ray.direction must be unit length")


class RaySource(Enum):
    """Which body part or device produced a ray. Closed so provenance is never lost."""

    HEAD = "head"
    EYE = "eye"
    HAND = "hand"
    CONTROLLER = "controller"


@dataclass(frozen=True)
class XrSample:
    """One pointing observation: where a ray was aimed at one instant."""

    timestamp_s: float
    source: RaySource
    ray: Ray
    confidence: float

    def __post_init__(self) -> None:
        _finite("XrSample.timestamp_s", self.timestamp_s)
        if self.timestamp_s < 0:
            raise ValueError("XrSample.timestamp_s must be >= 0")
        _unit_interval("XrSample.confidence", self.confidence)


class GestureKind(Enum):
    """Discrete hand/controller events. Closed; a new gesture is a reviewed diff."""

    PINCH_START = "pinch_start"
    PINCH_END = "pinch_end"
    SQUEEZE_START = "squeeze_start"
    SQUEEZE_END = "squeeze_end"
    TAP = "tap"


@dataclass(frozen=True)
class GestureEvent:
    timestamp_s: float
    kind: GestureKind
    confidence: float = 1.0

    def __post_init__(self) -> None:
        _finite("GestureEvent.timestamp_s", self.timestamp_s)
        if self.timestamp_s < 0:
            raise ValueError("GestureEvent.timestamp_s must be >= 0")
        _unit_interval("GestureEvent.confidence", self.confidence)


@dataclass(frozen=True)
class Panel:
    """A flat rectangular surface in world space that can receive dictated text.

    ``normal`` and ``up`` are unit vectors and perpendicular; ``width``/``height`` are
    metres. ``panel_id`` is the companion's stable identifier for the surface.
    """

    panel_id: str
    center: Vec3
    normal: Vec3
    up: Vec3
    width: float
    height: float
    label: str = ""

    def __post_init__(self) -> None:
        _identifier("Panel.panel_id", self.panel_id)
        for n, axis in (("normal", self.normal), ("up", self.up)):
            if abs(math.sqrt(axis.x * axis.x + axis.y * axis.y + axis.z * axis.z) - 1.0) > 1e-6:
                raise ValueError(f"Panel.{n} must be unit length")
        if abs(self.normal.x * self.up.x + self.normal.y * self.up.y + self.normal.z * self.up.z) > 1e-6:
            raise ValueError("Panel.normal and Panel.up must be perpendicular")
        for n, size in (("width", self.width), ("height", self.height)):
            _finite(f"Panel.{n}", size)
            if size <= 0:
                raise ValueError(f"Panel.{n} must be > 0")
        if len(self.label) > 256:
            raise ValueError("Panel.label is limited to 256 characters")


@dataclass(frozen=True)
class PanelHit:
    """A ray striking a panel: ``u``/``v`` are 0..1 across width / up height (v=1 is top)."""

    panel_id: str
    u: float
    v: float
    distance_m: float

    def __post_init__(self) -> None:
        _identifier("PanelHit.panel_id", self.panel_id)
        _unit_interval("PanelHit.u", self.u)
        _unit_interval("PanelHit.v", self.v)
        _finite("PanelHit.distance_m", self.distance_m)
        if self.distance_m < 0:
            raise ValueError("PanelHit.distance_m must be >= 0")
