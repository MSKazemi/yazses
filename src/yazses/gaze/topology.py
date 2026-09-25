"""Display topology as a value, and the rule that invalidates a calibration (ADR-v2-149).

A gaze calibration is an affine map from where the eyes point to a *desktop coordinate*.
Nothing in that 2x3 matrix records which desktop it was measured against, so plugging in a
second monitor, changing resolution, changing HiDPI scale or swapping which screen is
primary silently turns a good map into a confidently wrong one. It still returns plausible
numbers; it just points at the wrong window. That is the failure ADR-v2-149 exists to stop.

So a calibration is stored together with a **context**: the display topology it was made
on, the camera it was made with, and the name of the coordinate space. Before the map is
used, the stored context is compared with the current one, and a material difference marks
the calibration *stale* rather than rescaling it into a guess.

## The canonical coordinate space

One space, named :data:`CANONICAL_SPACE`, is used for calibration targets, gaze points and
window rectangles alike:

    **Logical (device-independent) pixels in the virtual-desktop coordinate system,
    with the origin at the top-left of the primary display.**

Two consequences, both of which the fixtures exercise:

* a monitor placed to the left of or above the primary one has a **negative** origin, and
  every comparison here is written to allow it -- `min()` over origins, never `abs()`;
* **HiDPI is explicit.** A display carries a ``scale`` (1.0, 1.25, 2.0 ...). Canonical
  coordinates are logical, so a 2.0-scale 3840x2160 panel occupies a 1920x1080 canonical
  rectangle. :meth:`Display.to_physical` and :meth:`Display.from_physical` are the only
  place the multiplication happens, so a physical/logical mix-up has one site to check
  rather than being smeared across the routing code.

## What counts as material

Deliberately, **any** determinable difference. The ADR rejects "auto-scale the coefficients
to the new resolution" as a general rule precisely because a monitor arrangement is not a
scale factor, and there is no cheap way to tell the transformable cases from the rest. So
the comparison is exact-fingerprint equality, and everything else is stale with a reason
the user can read.

The one thing that is *not* stale is the unknown: a calibration saved before this module
existed carries no context, and a machine whose display server cannot be queried yields no
topology. Neither is evidence of a change, and refusing there would delete working setups
to prove a point -- so both report :data:`Validity.UNVERIFIED`, which keeps routing alive
and says out loud that the binding could not be checked.

Pure: stdlib only, no numpy, no display server, no camera. Fabricate a topology and the
whole decision is testable.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

#: Name of the one coordinate space calibration and window geometry both live in.
#: Persisted so a future space change is a *detectable* change, not a silent one.
CANONICAL_SPACE = "desktop-logical-px"

#: Schema version of the persisted calibration context.
CONTEXT_VERSION = 1

#: Identifier of the calibration model the context belongs to (gaze/calibrate.py's
#: 2x3 affine map). A different model is a different meaning for the coefficients.
CALIBRATION_MODEL = "affine-2x3-v1"


class Validity(Enum):
    """Whether a stored calibration may be applied to the current desktop."""

    #: Stored context matches the current one exactly -- use the map.
    VALID = "valid"
    #: The binding could not be checked (legacy file, or no readable topology).
    #: Not evidence of a change; routing continues and the state is reported.
    UNVERIFIED = "unverified"
    #: The desktop or camera materially changed. Do not route with this map.
    STALE = "stale"


@dataclass(frozen=True)
class Display:
    """One display in canonical desktop coordinates.

    ``x``/``y`` may be negative (a monitor to the left of or above the primary one).
    ``width``/``height`` are **logical** pixels; ``scale`` is the HiDPI factor that
    converts them to the panel's physical pixels.
    """

    identifier: str
    x: int
    y: int
    width: int
    height: int
    scale: float = 1.0
    primary: bool = False

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError(f"display {self.identifier!r} has non-positive size")
        if self.scale <= 0:
            raise ValueError(f"display {self.identifier!r} has non-positive scale")

    # ---- geometry ------------------------------------------------------

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    def contains(self, x: float, y: float) -> bool:
        """True when the canonical point ``(x, y)`` lands on this display."""
        return self.x <= x < self.right and self.y <= y < self.bottom

    def to_physical(self, x: float, y: float) -> tuple[float, float]:
        """Canonical desktop point -> physical pixels *within this display*.

        The origin shift comes first, then the scale: a point on a 2.0-scale panel
        whose canonical origin is (1920, 0) is (0, 0) physical at canonical (1920, 0).
        """
        return ((x - self.x) * self.scale, (y - self.y) * self.scale)

    def from_physical(self, px: float, py: float) -> tuple[float, float]:
        """Physical pixels within this display -> canonical desktop point."""
        return (px / self.scale + self.x, py / self.scale + self.y)

    # ---- serialisation -------------------------------------------------

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.identifier,
            "x": self.x,
            "y": self.y,
            "w": self.width,
            "h": self.height,
            "scale": round(float(self.scale), 6),
            "primary": bool(self.primary),
        }

    @classmethod
    def from_dict(cls, raw: Any) -> Display:
        """Rebuild from :meth:`as_dict`. Raises on anything malformed."""
        if not isinstance(raw, dict):
            raise ValueError("display entry is not an object")
        return cls(
            identifier=str(raw["id"]),
            x=int(raw["x"]),
            y=int(raw["y"]),
            width=int(raw["w"]),
            height=int(raw["h"]),
            scale=float(raw.get("scale", 1.0)),
            primary=bool(raw.get("primary", False)),
        )

    def describe(self) -> str:
        """One-line human description, e.g. ``HDMI-1 1920x1080+0+0 @2.0x``."""
        scale = "" if self.scale == 1.0 else f" @{self.scale:g}x"
        return f"{self.identifier} {self.width}x{self.height}{self.x:+d}{self.y:+d}{scale}"


@dataclass(frozen=True)
class DisplayTopology:
    """The whole desktop: every display, in a canonical order.

    Constructed from any iterable of :class:`Display`; the tuple is re-sorted by
    position so that two queries returning the same monitors in a different order
    produce the same fingerprint. An empty topology means *unknown* -- the display
    server could not be asked -- and is never treated as "the monitors went away".
    """

    displays: tuple[Display, ...] = ()

    def __post_init__(self) -> None:
        ordered = tuple(sorted(self.displays, key=lambda d: (d.x, d.y, d.identifier)))
        object.__setattr__(self, "displays", ordered)

    @property
    def known(self) -> bool:
        """False when the topology could not be determined."""
        return bool(self.displays)

    @property
    def primary(self) -> Display | None:
        """The display flagged primary, else the first one, else None."""
        for d in self.displays:
            if d.primary:
                return d
        return self.displays[0] if self.displays else None

    def bounds(self) -> tuple[int, int, int, int] | None:
        """Union rectangle ``(x, y, width, height)`` over every display.

        ``x``/``y`` are negative when a monitor sits left of or above the primary
        one -- the whole point of using ``min()`` rather than assuming an origin.
        """
        if not self.displays:
            return None
        left = min(d.x for d in self.displays)
        top = min(d.y for d in self.displays)
        right = max(d.right for d in self.displays)
        bottom = max(d.bottom for d in self.displays)
        return (left, top, right - left, bottom - top)

    def display_at(self, x: float, y: float) -> Display | None:
        """The display a canonical point lands on, or None (gaps are possible)."""
        for d in self.displays:
            if d.contains(x, y):
                return d
        return None

    def as_dict(self) -> dict[str, Any]:
        return {"space": CANONICAL_SPACE, "displays": [d.as_dict() for d in self.displays]}

    @classmethod
    def from_dict(cls, raw: Any) -> DisplayTopology:
        """Rebuild from :meth:`as_dict`. Raises on anything malformed."""
        if not isinstance(raw, dict):
            raise ValueError("topology is not an object")
        entries = raw.get("displays", [])
        if not isinstance(entries, list):
            raise ValueError("topology 'displays' is not a list")
        return cls(displays=tuple(Display.from_dict(e) for e in entries))


#: A topology nobody could read. Distinct from "no monitors", which cannot happen.
UNKNOWN_TOPOLOGY = DisplayTopology()


@dataclass(frozen=True)
class CalibrationContext:
    """Everything a stored calibration must match to still be meaningful.

    Carries no frames, no landmarks and no biometric data -- just the desktop
    geometry, which camera produced the samples and at what capture size, and the
    names/versions of the model and coordinate space. ADR-v2-149 is explicit that
    raw frames must not be persisted for this purpose.
    """

    topology: DisplayTopology = field(default_factory=DisplayTopology)
    camera_id: str = ""
    camera_width: int = 0
    camera_height: int = 0
    model: str = CALIBRATION_MODEL
    space: str = CANONICAL_SPACE
    version: int = CONTEXT_VERSION

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "space": self.space,
            "model": self.model,
            "camera": {
                "id": self.camera_id,
                "w": self.camera_width,
                "h": self.camera_height,
            },
            "topology": self.topology.as_dict(),
        }

    @classmethod
    def from_dict(cls, raw: Any) -> CalibrationContext:
        """Rebuild from :meth:`as_dict`. Raises on anything malformed."""
        if not isinstance(raw, dict):
            raise ValueError("calibration context is not an object")
        camera = raw.get("camera", {})
        if not isinstance(camera, dict):
            raise ValueError("calibration context 'camera' is not an object")
        return cls(
            topology=DisplayTopology.from_dict(raw.get("topology", {})),
            camera_id=str(camera.get("id", "")),
            camera_width=int(camera.get("w", 0)),
            camera_height=int(camera.get("h", 0)),
            model=str(raw.get("model", CALIBRATION_MODEL)),
            space=str(raw.get("space", CANONICAL_SPACE)),
            version=int(raw.get("version", CONTEXT_VERSION)),
        )

    def fingerprint(self) -> str:
        """Stable short hash of the whole context.

        Equality of fingerprints is the *only* thing that makes a calibration valid,
        so it is computed from a canonical JSON rendering with sorted keys rather
        than from `hash()`, which is salted per process and would differ between the
        run that saved and the run that loads.
        """
        blob = json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class ContextCheck:
    """The verdict on a stored calibration, with the reason a user can be shown."""

    validity: Validity
    reason: str
    changes: tuple[str, ...] = ()

    @property
    def usable(self) -> bool:
        """True unless the calibration is stale. Unverified still routes."""
        return self.validity is not Validity.STALE

    @property
    def stale(self) -> bool:
        return self.validity is Validity.STALE


def describe_changes(stored: CalibrationContext, current: CalibrationContext) -> tuple[str, ...]:
    """Human phrases for every way *current* differs from *stored*.

    Displays are matched by identifier, because that is what survives a resolution
    change; an identifier present on one side only is an add or a remove. The
    phrases are what the status line and the daemon log print, so they name the
    monitor and both values -- "a monitor changed" tells the user nothing they can
    act on.
    """
    changes: list[str] = []

    was = {d.identifier: d for d in stored.topology.displays}
    now = {d.identifier: d for d in current.topology.displays}

    for ident in sorted(now.keys() - was.keys()):
        changes.append(f"monitor {now[ident].describe()} was added")
    for ident in sorted(was.keys() - now.keys()):
        changes.append(f"monitor {was[ident].describe()} was removed")

    for ident in sorted(was.keys() & now.keys()):
        old, new = was[ident], now[ident]
        if (old.width, old.height) != (new.width, new.height):
            changes.append(
                f"monitor {ident} changed resolution "
                f"{old.width}x{old.height} -> {new.width}x{new.height}"
            )
        if (old.x, old.y) != (new.x, new.y):
            changes.append(
                f"monitor {ident} moved {old.x:+d}{old.y:+d} -> {new.x:+d}{new.y:+d}"
            )
        if old.scale != new.scale:
            changes.append(f"monitor {ident} changed scale {old.scale:g}x -> {new.scale:g}x")

    old_primary = stored.topology.primary
    new_primary = current.topology.primary
    old_name = old_primary.identifier if old_primary else "?"
    new_name = new_primary.identifier if new_primary else "?"
    if old_name != new_name:
        changes.append(f"the primary monitor changed {old_name} -> {new_name}")

    if stored.camera_id != current.camera_id:
        changes.append(f"the camera changed {stored.camera_id or '?'} -> {current.camera_id or '?'}")
    if (stored.camera_width, stored.camera_height) != (current.camera_width, current.camera_height):
        changes.append(
            "the camera capture size changed "
            f"{stored.camera_width}x{stored.camera_height} -> "
            f"{current.camera_width}x{current.camera_height}"
        )

    if stored.model != current.model:
        changes.append(f"the calibration model changed {stored.model} -> {current.model}")
    if stored.space != current.space:
        changes.append(f"the coordinate space changed {stored.space} -> {current.space}")
    if stored.version != current.version:
        changes.append(
            f"the calibration context schema changed v{stored.version} -> v{current.version}"
        )

    return tuple(changes)


def check_context(
    stored: CalibrationContext | None,
    current: CalibrationContext | None,
) -> ContextCheck:
    """Decide whether a stored calibration may still be applied. Pure.

    Three outcomes, and the middle one is the reason this returns a verdict object
    rather than a bool:

    * **VALID** -- the fingerprints match, so the map means what it meant.
    * **UNVERIFIED** -- either side is unknown (a calibration file written before
      contexts existed, or a session whose display server could not be queried).
      Nothing here is evidence of a change, so the map is still used; the caller
      reports the state instead of pretending it verified something.
    * **STALE** -- both sides are known and differ. The map is refused, and
      ``changes`` says exactly what moved.
    """
    if stored is None:
        return ContextCheck(
            Validity.UNVERIFIED,
            "this calibration was saved before YazSes recorded which screens it was made on, "
            "so it cannot be checked against this desktop; recalibrate to bind it",
        )
    if current is None or not current.topology.known:
        return ContextCheck(
            Validity.UNVERIFIED,
            "the current display layout could not be read, so the calibration could not be "
            "checked against it",
        )
    if not stored.topology.known:
        return ContextCheck(
            Validity.UNVERIFIED,
            "this calibration recorded no display layout, so it cannot be checked against "
            "this desktop; recalibrate to bind it",
        )
    if stored.fingerprint() == current.fingerprint():
        return ContextCheck(Validity.VALID, "the screen layout and camera are unchanged")

    changes = describe_changes(stored, current)
    if not changes:
        # Fingerprints differ but no phrase explains it -- a field this function does
        # not describe yet. Say so honestly rather than printing an empty reason.
        changes = ("the recorded setup no longer matches this one",)
    return ContextCheck(
        Validity.STALE,
        "the calibration was made on a different setup: " + "; ".join(changes),
        changes,
    )


class SessionTopologyGuard:
    """Suspend gaze routing when the desktop changes *while* a session is running.

    ADR-v2-149: "if display topology changes while a camera control is active, stop
    gaze routing until geometry is refreshed; do not use cached window rectangles
    from the old topology". Dragging a monitor's position in display settings does
    not touch the calibration file, so the startup check cannot see it.

    The guard holds the context the running calibration was accepted against and
    re-reads the live one through an injected ``read`` callable. Once it has seen a
    material change it stays suspended -- a recalibration (:meth:`accept`) is what
    clears it, not the layout happening to be re-read a second time. That is the
    conservative direction: the alternative resumes routing with coefficients that
    were never revalidated.

    Polling is rate-limited because the caller asks once per dictation hold and the
    real reader spawns a subprocess. ``clock`` is injected so tests do not sleep.
    """

    def __init__(self, accepted, read, *, min_interval: float = 5.0, clock=None) -> None:
        self._accepted: CalibrationContext | None = accepted
        self._read = read
        self._min_interval = min_interval
        self._clock = clock or time.monotonic
        self._last_poll: float | None = None
        self._check: ContextCheck | None = None

    @property
    def last_check(self) -> ContextCheck | None:
        """The most recent verdict, or None if nothing has been polled yet."""
        return self._check

    def accept(self, context: CalibrationContext | None) -> None:
        """Adopt *context* as the new baseline and clear any suspension."""
        self._accepted = context
        self._check = None
        self._last_poll = None

    def suspended(self) -> bool:
        """True when routing must stop. Polls at most every ``min_interval`` seconds."""
        if self._check is not None and self._check.stale:
            return True  # sticky until accept()
        now = self._clock()
        if self._last_poll is not None and (now - self._last_poll) < self._min_interval:
            return False
        self._last_poll = now
        try:
            current = self._read()
        except Exception:
            # A failed read is not evidence of a change; never invent one.
            return False
        self._check = check_context(self._accepted, current)
        return self._check.stale
