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

    **The platform's own virtual-desktop coordinate system, in the units applications and
    the window manager report geometry in -- never converted, never re-origined.**

Which is a different thing on each platform, and the difference is the part that bites:

* **X11 (the only platform gaze routing runs on today):** the X root window. Its origin is
  the top-left of the *framebuffer*, so it is **not** the primary display and no coordinate
  is ever negative -- a monitor to the left of the primary one has the *smaller* x (often
  ``+0``) and the primary sits at ``+1920+0``. ``xrandr`` and ``xdotool`` both speak this
  space, which is exactly why a topology from one can be compared with window rectangles
  from the other. X11 has no HiDPI factor in its coordinates (``GDK_SCALE``/``Xft.dpi``
  change what applications draw, not what the server reports), so one unit is one
  framebuffer pixel and ``scale`` is 1.0 here.
* **macOS / Windows (no topology provider yet):** the main display's top-left is the
  origin, a monitor to its left or above has a negative origin, and the unit is the
  logical point / DPI-virtualised pixel the OS reports.

Inventing one primary-origin space and shifting X11 into it would make ``xrandr`` disagree
with every ``xdotool`` window rectangle, so it is deliberately not done. The space is
*named* so that a future change of meaning is a detectable change; do not rename it
without a migration -- the name is part of every stored fingerprint.

Consequences, all of which the fixtures exercise:

* where the OS origin is the main display, a monitor placed to the left of or above it has
  a **negative** origin, and every comparison here is written to allow it -- `min()` over
  origins, never `abs()`;
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

## Conversions, in one place

Three spaces meet here, and each conversion has exactly one function:

* **canonical desktop** -- the space above;
* **display-physical** -- pixels of one panel, origin at that panel's top-left
  (:meth:`Display.to_physical` / :meth:`Display.from_physical`, and
  :meth:`DisplayTopology.to_physical` / :meth:`DisplayTopology.from_physical` when the
  display has to be found first);
* **desktop-relative** -- canonical coordinates shifted so the union's top-left is
  ``(0, 0)`` (:meth:`DisplayTopology.to_desktop_relative`), for anything that indexes a
  buffer covering the whole desktop. Its offset is :attr:`DisplayTopology.origin`, which
  is negative where the OS puts a monitor left of or above the main one.

A point in a gap between monitors belongs to no display and converts to ``None``, never
to the nearest panel: snapping is a placement decision (``calibrate.targets_on_displays``),
not a unit conversion.

## A damaged record is never a valid one

Everything rebuilt from disk goes through the ``from_dict`` constructors, and those are
strict: a coordinate must be an integer (``1.5``, ``true`` and ``"12"`` are refused, not
truncated or coerced), a scale a finite positive number, a rotation one of the four words,
an identifier unique within its topology. A refused record raises ``ValueError``, which
``gaze/store.py`` reports as a damaged binding -- never as VALID.

Pure: stdlib only, no numpy, no display server, no camera. Fabricate a topology and the
whole decision is testable.
"""
from __future__ import annotations

import hashlib
import json
import math
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


#: The rotations a display may report. Anything else in a stored record is damage.
ROTATIONS = frozenset({"normal", "left", "right", "inverted"})


def _strict_int(value: Any, what: str) -> int:
    """An integer from a parsed JSON value, refusing anything that would have to be guessed.

    ``int()`` alone turns ``1.7`` into ``1``, ``True`` into ``1`` and ``"12"`` into ``12``,
    so a damaged record would quietly rebuild into a *different* desktop -- and a different
    desktop that happens to equal the current one makes a damaged map read as VALID. An
    integral float (``1920.0``) is accepted: it is the same number, not a guess.
    """
    if isinstance(value, bool):
        raise ValueError(f"{what} is a boolean, not an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return int(value)
    raise ValueError(f"{what} is not an integer: {value!r}")


def _strict_float(value: Any, what: str) -> float:
    """A finite number from a parsed JSON value (``bool`` and strings refused)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{what} is not a number: {value!r}")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{what} is not finite: {value!r}")
    return out


def digest(payload: Any) -> str:
    """Stable short hash of a JSON value: sha256 over sorted-key, space-free JSON.

    The one hashing rule, used both to fingerprint a context and to check that a stored
    context still hashes to the fingerprint saved beside it. Unsalted (``hash()`` is
    salted per process), so the run that saves and the run that loads agree. It detects
    accidental damage; it is not a signature -- anyone who can edit the file can
    recompute it. Raises ``ValueError`` on NaN/infinity, which no valid record contains.
    """
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


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
    #: ``normal`` | ``left`` | ``right`` | ``inverted``. Geometry cannot tell ``left`` from
    #: ``right`` (same width and height) or ``normal`` from ``inverted`` (same rectangle),
    #: yet each puts the physical screen somewhere else relative to the camera, so a
    #: calibration made in one is wrong in the other. The default is what a file that
    #: predates the field read as, so such a file keeps its fingerprint.
    rotation: str = "normal"

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError(f"display {self.identifier!r} has non-positive size")
        if not (math.isfinite(self.scale) and self.scale > 0):
            # NaN slips past `<= 0` (every comparison with NaN is False) and would make
            # every converted coordinate NaN; infinity would make them all infinite.
            raise ValueError(f"display {self.identifier!r} has a non-finite or non-positive scale")
        if self.rotation not in ROTATIONS:
            raise ValueError(f"display {self.identifier!r} has unknown rotation {self.rotation!r}")

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
            "rotation": self.rotation,
        }

    @classmethod
    def from_dict(cls, raw: Any) -> Display:
        """Rebuild from :meth:`as_dict`. Raises on anything malformed."""
        if not isinstance(raw, dict):
            raise ValueError("display entry is not an object")
        identifier = raw["id"]
        if not isinstance(identifier, str) or not identifier:
            raise ValueError("display id is not a non-empty string")
        primary = raw.get("primary", False)
        if not isinstance(primary, bool):
            raise ValueError(f"display {identifier!r} 'primary' is not a boolean")
        rotation = raw.get("rotation", "normal")
        if not isinstance(rotation, str):
            raise ValueError(f"display {identifier!r} 'rotation' is not a string")
        return cls(
            identifier=identifier,
            x=_strict_int(raw["x"], "display x"),
            y=_strict_int(raw["y"], "display y"),
            width=_strict_int(raw["w"], "display width"),
            height=_strict_int(raw["h"], "display height"),
            scale=_strict_float(raw.get("scale", 1.0), "display scale"),
            primary=primary,
            rotation=rotation,
        )

    def describe(self) -> str:
        """One-line human description, e.g. ``HDMI-1 1920x1080+0+0 @2.0x``."""
        scale = "" if self.scale == 1.0 else f" @{self.scale:g}x"
        turned = "" if self.rotation == "normal" else f" rotated {self.rotation}"
        return f"{self.identifier} {self.width}x{self.height}{self.x:+d}{self.y:+d}{scale}{turned}"


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

    # ---- conversions between spaces (see the module docstring) -------------

    @property
    def origin(self) -> tuple[int, int] | None:
        """Top-left of the union rectangle: the virtual desktop's origin. May be negative."""
        bounds = self.bounds()
        return None if bounds is None else (bounds[0], bounds[1])

    def to_physical(self, x: float, y: float) -> PhysicalPoint | None:
        """Canonical desktop point -> physical pixels on the display it lands on.

        ``None`` when the point is in a gap between monitors or off the desktop: it is on
        no panel, so it has no physical pixel, and inventing the nearest one would hide a
        routing error rather than report it.
        """
        display = self.display_at(x, y)
        if display is None:
            return None
        px, py = display.to_physical(x, y)
        return PhysicalPoint(display.identifier, px, py)

    def from_physical(self, identifier: str, px: float, py: float) -> tuple[float, float] | None:
        """Physical pixels on display *identifier* -> canonical desktop point.

        ``None`` for a display this topology does not have, or a pixel outside that panel's
        physical size. Either means the caller holds geometry from a different layout, which
        is exactly what must not be converted as if it were current.
        """
        for display in self.displays:
            if display.identifier != identifier:
                continue
            inside = (
                0 <= px < display.width * display.scale
                and 0 <= py < display.height * display.scale
            )
            return display.from_physical(px, py) if inside else None
        return None

    def to_desktop_relative(self, x: float, y: float) -> tuple[float, float] | None:
        """Canonical point -> offset from the virtual desktop's top-left.

        Never negative for a point on the desktop, whatever the OS origin. ``None`` for an
        unknown topology, which has no origin to subtract.
        """
        origin = self.origin
        if origin is None:
            return None
        return (x - origin[0], y - origin[1])

    def from_desktop_relative(self, rx: float, ry: float) -> tuple[float, float] | None:
        """Inverse of :meth:`to_desktop_relative`. ``None`` for an unknown topology."""
        origin = self.origin
        if origin is None:
            return None
        return (rx + origin[0], ry + origin[1])

    # ---- serialisation -------------------------------------------------

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
        displays = tuple(Display.from_dict(e) for e in entries)
        # Changes are described by matching identifiers, so two entries with one name
        # would collapse into one there while still counting twice in the fingerprint.
        # No reader produces that; in a stored record it is damage.
        names = [d.identifier for d in displays]
        if len(set(names)) != len(names):
            raise ValueError("topology lists the same display identifier twice")
        return cls(displays=displays)


@dataclass(frozen=True)
class PhysicalPoint:
    """A point in one display's physical pixels, origin at that display's top-left."""

    display: str
    x: float
    y: float


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
        camera_id = camera.get("id", "")
        model = raw.get("model", CALIBRATION_MODEL)
        space = raw.get("space", CANONICAL_SPACE)
        if not all(isinstance(v, str) for v in (camera_id, model, space)):
            raise ValueError("calibration context camera id, model and space must be strings")
        return cls(
            topology=DisplayTopology.from_dict(raw.get("topology", {})),
            camera_id=camera_id,
            camera_width=_strict_int(camera.get("w", 0), "camera width"),
            camera_height=_strict_int(camera.get("h", 0), "camera height"),
            model=model,
            space=space,
            version=_strict_int(raw.get("version", CONTEXT_VERSION), "context version"),
        )

    def fingerprint(self) -> str:
        """Stable short hash of the whole context.

        Equality of fingerprints is the *only* thing that makes a calibration valid,
        so it is computed from a canonical JSON rendering with sorted keys rather
        than from `hash()`, which is salted per process and would differ between the
        run that saved and the run that loads.
        """
        return digest(self.as_dict())


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
        # Rounded exactly as as_dict() rounds it, so a change this reports is one the
        # fingerprint saw, and a difference the fingerprint cannot see is never reported.
        if round(float(old.scale), 6) != round(float(new.scale), 6):
            changes.append(f"monitor {ident} changed scale {old.scale:g}x -> {new.scale:g}x")
        if old.rotation != new.rotation:
            changes.append(f"monitor {ident} was rotated {old.rotation} -> {new.rotation}")

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
        # "Unknown layout" is a state, not a guess: no monitor was invented or removed to
        # fill the gap. Which of the two reasons applies matters to the reader -- a map
        # bound to a known layout that can no longer be read is the one worth a second look.
        bound = (
            "this calibration is bound to a known layout but "
            if stored.topology.known
            else ""
        )
        return ContextCheck(
            Validity.UNVERIFIED,
            f"the current display layout is unknown (it could not be read on this system), "
            f"so {bound}the calibration could not be checked against it",
        )
    if not stored.topology.known:
        return ContextCheck(
            Validity.UNVERIFIED,
            "this calibration recorded no display layout, so it cannot be checked against "
            "this desktop; recalibrate to bind it",
        )
    if stored.fingerprint() == current.fingerprint():
        if stored.camera_width and stored.camera_height:
            return ContextCheck(Validity.VALID, "the screen layout and camera are unchanged")
        # Said plainly rather than implied: a capture size of 0x0 means nobody recorded
        # one, so "the camera is unchanged" would claim a comparison that never happened.
        return ContextCheck(
            Validity.VALID,
            "the screen layout is unchanged (the camera is identified by index only; "
            "its capture size was not recorded, so a swapped device on the same index "
            "is not detected)",
        )

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


def settle_context(
    started: CalibrationContext | None,
    finished: CalibrationContext | None,
) -> tuple[CalibrationContext | None, ContextCheck]:
    """Pick the context a freshly measured calibration may be bound to. Pure.

    A calibration wizard takes minutes. The desktop is read at its start and again at its
    end, because stamping the *end* state on samples taken during the *start* state (what
    reading only once, afterwards, does) turns a monitor plugged in mid-wizard into a
    perfectly VALID-looking map of a layout it never measured -- the one outcome the whole
    context exists to prevent, produced by the code that creates the context.

    Returns ``(context to store, verdict on the run)``:

    * the two reads agree -> the start context, VALID;
    * the two reads are both known and differ -> the start context and a STALE verdict;
      the caller must **not** save, because no single layout produced those samples;
    * either read is unknown -> UNVERIFIED, and the context is whichever read exists,
      preferring the start one (it is the layout the first samples were taken on).
    """
    check = check_context(started, finished)
    if check.stale:
        return started, check
    if started is not None and started.topology.known:
        return started, check
    return (finished if finished is not None else started), check


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

    def verify_now(self) -> ContextCheck:
        """Read the live layout *now*, ignoring the rate limit, and return the verdict.

        :meth:`suspended` is rate-limited because routing asks once per dictation hold; that
        also means a layout change is invisible for up to ``min_interval`` seconds. Anything
        that is about to make something *permanent* (a calibration written to disk, #398)
        must not accept that window, so it asks here instead. Same stickiness as
        :meth:`suspended` (a stale verdict stays until :meth:`accept`), and the same rule
        that a failed read is not evidence of a change -- but the verdict then is
        ``UNVERIFIED`` rather than a guess, so a caller that needs a *confirmed* layout can
        tell "unchanged" from "could not tell".
        """
        if self._check is not None and self._check.stale:
            return self._check
        try:
            current = self._read()
        except Exception:
            return ContextCheck(
                Validity.UNVERIFIED, "the current display layout could not be read just now"
            )
        self._last_poll = self._clock()
        self._check = check_context(self._accepted, current)
        return self._check

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
