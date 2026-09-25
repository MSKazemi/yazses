"""The pointer-output boundary: ``PointerSink`` and its vocabulary — ADR-v2-146.

YazSes has several ways to decide *where a pointer should go* — Head-Pointer's
yaw/pitch mapping, the voice mouse grid, a future gaze-assisted warp, a dwell or face
switch that needs a click. None of them should know what an X11 display, a Wayland
portal, a `CGEvent` or `SendInput` is. This module is the one seam between them: the
feature produces pointer intent, a backend under a different module turns it into
platform events.

It is deliberately dumb and deliberately pure. It holds **no** camera, gaze, head-pose
or gesture concept, imports nothing outside the standard library, runs no subprocess
and opens no connection. Safety lives *above* the sink: the dwell detector decides when
a click happens, the confirmation policy decides whether a destructive action proceeds,
and global pause stops intent before it ever reaches a sink. A sink that is asked to
click, clicks.

**Unsupported is a word, not a silence.** Every implementation defines every method —
including :meth:`PointerSink.move_absolute`, which many backends cannot offer — and a
backend that cannot perform an operation raises :class:`PointerUnsupportedError` and
reports the same fact ahead of time through :meth:`PointerSink.capabilities`. A silent
no-op would leave a user staring at a pointer that will not move with no way to find
out why, so it is a contract violation here, not an implementation choice.

Units and signs, because a pointer boundary that leaves them implicit is a boundary that
every backend interprets differently:

* ``move_relative(dx, dy)`` — a delta in **logical desktop pointer units** (the
  coordinate space the platform backend itself uses, already scaled for HiDPI by the
  compositor/server). Feature code does not convert DPI. ``+dx`` is toward the right
  edge of the desktop, ``+dy`` toward the bottom, which is the sign convention of every
  desktop coordinate space YazSes targets.
* ``move_absolute(x, y)`` — a position in the canonical desktop coordinate space, same
  axes. Optional: capabilities say whether it is safe to use, because multi-monitor and
  HiDPI make absolute coordinates easy to get wrong.
* ``scroll(dx, dy)`` — a scroll delta in the backend's notch/pixel units, **same signs
  as motion**: ``+dy`` scrolls toward the bottom of the document (what a user calls
  "scrolling down"), ``+dx`` toward its right. Backends whose native axis runs the other
  way negate at their own boundary, not here.

Failure semantics: a failed operation raises, stops there, and is never retried or
replayed by the sink. No sink runs an implicit motion loop — one call, one effect — so a
backend that dies leaves the pointer still rather than gliding off the screen.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, runtime_checkable


class PointerButton(str, Enum):
    """The buttons a sink may be asked for.

    ``LEFT`` and ``RIGHT`` are the minimum every backend must offer. ``MIDDLE`` is
    optional and feature code must not assume it: ask
    :meth:`PointerCapabilities.supports_button` first, or be ready for
    :class:`PointerUnsupportedError`.
    """

    LEFT = "left"
    RIGHT = "right"
    MIDDLE = "middle"


#: The buttons every backend must support. A backend offering less than this is not a
#: pointer sink; it is a partial one, and should fail to construct rather than pretend.
REQUIRED_BUTTONS = frozenset({PointerButton.LEFT, PointerButton.RIGHT})


class PointerError(RuntimeError):
    """Base class for every pointer-output failure.

    Callers that only need "did this work?" catch this one. It is a ``RuntimeError`` so
    that a feature which forgets to catch it fails loudly rather than typing into the
    void.
    """


class PointerUnsupportedError(PointerError):
    """The backend does not implement the requested operation, and says so.

    Raised for an operation the backend's :meth:`PointerSink.capabilities` already
    reported as unavailable — absolute motion on a relative-only backend, a middle click
    on a two-button one, horizontal scroll where there is no horizontal axis. This is
    the error that exists so an unsupported operation is never a silent no-op.
    """


class PointerBackendError(PointerError):
    """The operation is supported and the platform refused or failed it.

    A compositor that denied the RemoteDesktop session, an X server that went away, a
    sink used after :meth:`PointerSink.close`. The distinction from
    :class:`PointerUnsupportedError` matters to the caller: this one may be transient and
    worth surfacing to the user, the other is permanent for this backend.
    """


@dataclass(frozen=True)
class PointerCapabilities:
    """What one backend can actually do, asked before it is asked to do it.

    Immutable and cheap: a sink may be asked repeatedly and must answer identically for
    its lifetime, so a caller can read it once at start-up. ``backend`` is a short
    stable identifier (``"x11"``, ``"portal"``, ``"quartz"``, ``"sendinput"``,
    ``"fake"``) used in logs, status output and test assertions.
    """

    backend: str
    relative_motion: bool = False
    absolute_motion: bool = False
    buttons: frozenset[PointerButton] = field(default_factory=frozenset)
    scroll_vertical: bool = False
    scroll_horizontal: bool = False

    def supports_button(self, button: PointerButton) -> bool:
        """True if this backend can press and release *button*."""
        return button in self.buttons

    def supports_scroll(self, dx: float, dy: float) -> bool:
        """True if a ``scroll(dx, dy)`` uses only axes this backend has.

        A zero component needs no axis, so a vertical-only backend still accepts
        ``scroll(0.0, -3.0)``.
        """
        if dx and not self.scroll_horizontal:
            return False
        if dy and not self.scroll_vertical:
            return False
        return True


@runtime_checkable
class PointerSink(Protocol):
    """One platform's pointer output, behind six methods.

    Implementations live beside their platform (X11, the XDG RemoteDesktop portal,
    macOS, Windows) and are selected through the platform factory, so a feature can ask
    for a sink without importing any of them. ``tests/pointer_fake.py`` holds the
    deterministic in-memory one that keeps feature tests hermetic; it is test
    infrastructure and deliberately does not ship.

    Adding a method here breaks ``isinstance`` for every existing implementation — the
    protocol is ``runtime_checkable``, so a sink written against the old shape silently
    stops matching. Grow it only with the backends updated in the same change.
    """

    def capabilities(self) -> PointerCapabilities:
        """Report what this backend can do. Constant for the sink's lifetime."""
        ...

    def move_relative(self, dx: float, dy: float) -> None:
        """Move the pointer by ``(dx, dy)`` logical units; ``+dy`` is downward."""
        ...

    def move_absolute(self, x: float, y: float) -> None:
        """Move the pointer to ``(x, y)`` in the desktop coordinate space.

        Optional: raises :class:`PointerUnsupportedError` when
        ``capabilities().absolute_motion`` is False. It is still a method on every
        backend — an unsupported operation must be an error, not a missing attribute.
        """
        ...

    def click(self, button: PointerButton = PointerButton.LEFT) -> None:
        """Press and release *button* exactly once, in that order."""
        ...

    def scroll(self, dx: float, dy: float) -> None:
        """Scroll by ``(dx, dy)``; ``+dy`` scrolls down, ``+dx`` scrolls right."""
        ...

    def close(self) -> None:
        """Release the backend. Idempotent; later operations raise."""
        ...


def check_finite(**values: float) -> None:
    """Reject NaN and infinity before they reach a platform call.

    A NaN delta is not a small bug: X11 and the portal both take it as a number, and
    what the pointer does next is undefined. Every backend validates at its own edge —
    ``check_finite(dx=dx, dy=dy)`` — so the bad value never becomes a command.
    """
    for name, value in values.items():
        if not math.isfinite(value):
            raise ValueError(f"{name} must be a finite number, got {value!r}")


def require_relative(caps: PointerCapabilities) -> None:
    """Raise :class:`PointerUnsupportedError` unless *caps* offers relative motion."""
    if not caps.relative_motion:
        raise PointerUnsupportedError(
            f"backend {caps.backend!r} cannot move the pointer relatively"
        )


def require_absolute(caps: PointerCapabilities) -> None:
    """Raise :class:`PointerUnsupportedError` unless *caps* offers absolute motion."""
    if not caps.absolute_motion:
        raise PointerUnsupportedError(
            f"backend {caps.backend!r} cannot move the pointer to an absolute position"
        )


def require_button(caps: PointerCapabilities, button: PointerButton) -> None:
    """Raise :class:`PointerUnsupportedError` unless *caps* offers *button*."""
    if not caps.supports_button(button):
        have = ", ".join(sorted(b.value for b in caps.buttons)) or "no buttons"
        raise PointerUnsupportedError(
            f"backend {caps.backend!r} has no {button.value} button (has: {have})"
        )


def require_scroll(caps: PointerCapabilities, dx: float, dy: float) -> None:
    """Raise :class:`PointerUnsupportedError` unless *caps* has the axes used."""
    if not caps.supports_scroll(dx, dy):
        axis = "horizontal" if dx and not caps.scroll_horizontal else "vertical"
        raise PointerUnsupportedError(
            f"backend {caps.backend!r} cannot scroll {axis}ly"
        )
