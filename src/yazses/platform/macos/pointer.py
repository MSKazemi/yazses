"""macOS pointer output — CoreGraphics synthetic mouse events (ADR-v2-146).

The macOS half of the `PointerSink` boundary defined in `src/yazses/pointer/base.py`.
Head-Pointer, the voice mouse grid and any future gaze-assisted warp produce pointer
intent; this turns it into `CGEvent` mouse events posted to the HID event tap, which is
the same mechanism `platform/macos/injector.py` already uses for keystrokes, so the
permission a user has granted for dictation (Accessibility / Input Monitoring) is the one
this needs too.

**Two layers, and the seam between them is why CI needs no Mac.**
:class:`MacosPointerSink` holds the whole contract — capability reporting, edge
validation, press-then-release ordering, close semantics, failure translation — and knows
nothing about Quartz. :class:`QuartzMouseApi` holds every CoreGraphics call and nothing
else. The sink takes its API object as a constructor argument, so the shared contract
suite runs against the real sink with a recording double, and the native layer is checked
separately against a fake Quartz module.

**What this backend reports, and why it is not everything.**

* Relative motion — CoreGraphics has no relative mouse event. The API reads the current
  cursor location and posts an absolute `kCGEventMouseMoved` to location + delta, which
  is how every synthetic-pointer library on this platform does it. Applications that read
  raw mouse deltas instead of the cursor (mouse-captured games) are therefore out of
  scope; the desktop cursor moves, which is what Head-Pointer needs.
* Absolute motion — **supported.** CoreGraphics global display coordinates are one
  well-defined space in points, origin at the top-left of the main display, already
  scaled for HiDPI. That is the "logical desktop pointer units" the protocol asks for.
* Left, right and middle buttons — all three exist as `CGEvent` types.
* Vertical scroll — supported, **negated here.** Apple's scroll-wheel axis 1 is
  up-positive; the boundary is down-positive, so ``scroll(0, +1)`` posts ``-1``.
* Horizontal scroll — **reported as unavailable, deliberately.** Apple documents neither
  sign for scroll axis 2, third-party implementations disagree about whether a positive
  value scrolls left or right, and some tie it to the user's "natural scrolling"
  preference. No Mac is available to settle it. A horizontal scroll whose sign is
  inverted makes a head-controlled pointer fight its user, and ADR-v2-146 is explicit
  that an honest "unsupported" beats a guess: the axis stays off until somebody with a
  Mac verifies the sign, at which point this is a one-line change plus its test.

**Never executed on macOS.** Everything in :class:`QuartzMouseApi` is written from
Apple's API documentation and checked against a fake Quartz module on Linux. No line of
it has run against a real `CGEventPost`. In particular, whether a synthetic click needs
``kCGMouseEventClickState`` set to be recognised by every application is unverified —
widely-used libraries omit it, so this omits it too, and if hardware testing shows clicks
landing as mere mouse-downs, that field is the first thing to add.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from yazses.pointer.base import (
    PointerBackendError,
    PointerButton,
    PointerCapabilities,
    PointerError,
    check_finite,
    require_absolute,
    require_button,
    require_relative,
    require_scroll,
)
from yazses.pointer.subpixel import SubPixelAccumulator

log = logging.getLogger(__name__)

#: What this backend honestly offers. See the module docstring for why horizontal scroll
#: is absent; `backend` is the short stable identifier the protocol asks for.
MACOS_POINTER_CAPABILITIES = PointerCapabilities(
    backend="quartz",
    relative_motion=True,
    absolute_motion=True,
    buttons=frozenset(PointerButton),
    scroll_vertical=True,
    scroll_horizontal=False,
)

#: ``PointerButton`` -> the Quartz attribute names for its down event, up event and
#: `CGMouseButton` constant. Held as *names* rather than values because the values only
#: exist once PyObjC has been imported, and this module must import on Linux.
#:
#: The middle button is `kCGEventOtherMouse*` with `kCGMouseButtonCenter`: macOS has no
#: "middle" event type, it has an "other" one that carries the button number.
_BUTTON_EVENTS: dict[PointerButton, tuple[str, str, str]] = {
    PointerButton.LEFT: ("kCGEventLeftMouseDown", "kCGEventLeftMouseUp", "kCGMouseButtonLeft"),
    PointerButton.RIGHT: ("kCGEventRightMouseDown", "kCGEventRightMouseUp", "kCGMouseButtonRight"),
    PointerButton.MIDDLE: (
        "kCGEventOtherMouseDown",
        "kCGEventOtherMouseUp",
        "kCGMouseButtonCenter",
    ),
}


class QuartzPointerApi(Protocol):
    """The CoreGraphics operations :class:`MacosPointerSink` needs, and no others.

    Deliberately six narrow methods rather than "the Quartz module": a test double
    implements this in twenty lines, and the sink cannot reach a CoreGraphics call the
    contract has not agreed to. Deltas and coordinates arrive in the protocol's own
    convention (``+y`` down, ``+dy`` scrolls down) and any native sign flip happens
    inside the implementation.

    Not ``runtime_checkable`` on purpose. Nothing needs an ``isinstance`` against it, and
    a runtime-checkable protocol that later grows a method silently stops matching every
    implementation written against the old shape.
    """

    def move_relative(self, dx: float, dy: float) -> None: ...

    def move_absolute(self, x: float, y: float) -> None: ...

    def press(self, button: PointerButton) -> None: ...

    def release(self, button: PointerButton) -> None: ...

    def scroll(self, dx: float, dy: float) -> None: ...

    def close(self) -> None: ...


def _load_quartz() -> Any:
    """Import the PyObjC Quartz bridge, at the moment it is first needed.

    Lazy and inside a function for the reason every other PyObjC import in this package
    is: a base install on Linux must import `yazses.platform.macos.pointer` without
    PyObjC present, and does — constructing the sink does not import Quartz either, only
    the first pointer operation does.
    """
    import Quartz  # type: ignore[import-not-found]

    return Quartz


class QuartzMouseApi:
    """Every CoreGraphics call this backend makes, in one small object.

    Motion passes through at full precision, because CoreGraphics coordinates are
    floats and need no rounding. Scroll does not: its native line count is an integer, so
    it goes through a :class:`~yazses.pointer.subpixel.SubPixelAccumulator` and a
    fraction of a line is carried rather than dropped.
    """

    def __init__(self, quartz: Any | None = None) -> None:
        self._quartz = quartz
        self._scroll_steps = SubPixelAccumulator()

    def _q(self) -> Any:
        if self._quartz is None:
            self._quartz = _load_quartz()
        return self._quartz

    # -- position ---------------------------------------------------------- #

    def cursor_location(self) -> tuple[float, float]:
        """Where the cursor is now, in global display coordinates.

        `CGEventCreate(None)` builds an event carrying the current pointer state; its
        location is the documented way to ask CoreGraphics where the cursor is without
        an `NSApplication`.
        """
        quartz = self._q()
        probe = quartz.CGEventCreate(None)
        if probe is None:
            raise PointerBackendError("CGEventCreate returned NULL; cannot read the cursor")
        point = quartz.CGEventGetLocation(probe)
        return float(point.x), float(point.y)

    # -- the API ----------------------------------------------------------- #

    def move_relative(self, dx: float, dy: float) -> None:
        x, y = self.cursor_location()
        self.move_absolute(x + dx, y + dy)

    def move_absolute(self, x: float, y: float) -> None:
        quartz = self._q()
        self._post_mouse(quartz.kCGEventMouseMoved, x, y, quartz.kCGMouseButtonLeft)

    def press(self, button: PointerButton) -> None:
        self._post_button(button, down=True)

    def release(self, button: PointerButton) -> None:
        self._post_button(button, down=False)

    def scroll(self, dx: float, dy: float) -> None:
        """Post a line-unit scroll event. ``dx`` is never non-zero — see capabilities.

        The vertical sign is flipped here: Apple's axis 1 is up-positive and this
        boundary is down-positive. A whole-line count of zero posts nothing and keeps the
        fraction, so a slow head-driven scroll accumulates instead of vanishing.
        """
        _, lines_down = self._scroll_steps.take(dx, dy)
        if not lines_down:
            return
        quartz = self._q()
        event = quartz.CGEventCreateScrollWheelEvent(
            None, quartz.kCGScrollEventUnitLine, 1, -lines_down
        )
        if event is None:
            raise PointerBackendError("CGEventCreateScrollWheelEvent returned NULL")
        quartz.CGEventPost(quartz.kCGHIDEventTap, event)

    def close(self) -> None:
        """Nothing to release: a posted `CGEvent` owns no session or connection."""
        self._scroll_steps.reset()

    # -- internals --------------------------------------------------------- #

    def _post_button(self, button: PointerButton, *, down: bool) -> None:
        quartz = self._q()
        down_name, up_name, button_name = _BUTTON_EVENTS[button]
        event_type = getattr(quartz, down_name if down else up_name)
        x, y = self.cursor_location()
        self._post_mouse(event_type, x, y, getattr(quartz, button_name))

    def _post_mouse(self, event_type: Any, x: float, y: float, cg_button: Any) -> None:
        quartz = self._q()
        event = quartz.CGEventCreateMouseEvent(None, event_type, (x, y), cg_button)
        if event is None:
            # The injector logs and returns here; a pointer sink must not, because a
            # silent no-op is the one failure mode ADR-v2-146 names as forbidden.
            raise PointerBackendError("CGEventCreateMouseEvent returned NULL")
        quartz.CGEventPost(quartz.kCGHIDEventTap, event)


class MacosPointerSink:
    """`PointerSink` for macOS, over an injectable CoreGraphics API.

    Pass *api* to test it; leave it out and the real :class:`QuartzMouseApi` is used,
    which imports PyObjC on its first call and not before.
    """

    def __init__(self, api: QuartzPointerApi | None = None) -> None:
        self._api: QuartzPointerApi = api if api is not None else QuartzMouseApi()
        self._closed = False

    def capabilities(self) -> PointerCapabilities:
        return MACOS_POINTER_CAPABILITIES

    def move_relative(self, dx: float, dy: float) -> None:
        check_finite(dx=dx, dy=dy)
        require_relative(MACOS_POINTER_CAPABILITIES)
        self._guard_open()
        self._attempt(lambda: self._api.move_relative(dx, dy), "move the pointer")

    def move_absolute(self, x: float, y: float) -> None:
        check_finite(x=x, y=y)
        require_absolute(MACOS_POINTER_CAPABILITIES)
        self._guard_open()
        self._attempt(lambda: self._api.move_absolute(x, y), "place the pointer")

    def click(self, button: PointerButton = PointerButton.LEFT) -> None:
        """Press then release *button* once.

        If the release fails after the press succeeded, the button is left down and this
        raises saying so. It does **not** retry: ADR-v2-146 forbids repeating a command
        after a backend failure, and a second attempt down the same dead path would fail
        the same way while costing the user another moment of a held button. The message
        and the log line name the button so the state is diagnosable rather than
        mysterious.
        """
        require_button(MACOS_POINTER_CAPABILITIES, button)
        self._guard_open()
        self._attempt(lambda: self._api.press(button), f"press the {button.value} button")
        try:
            self._attempt(lambda: self._api.release(button), f"release the {button.value} button")
        except PointerError:
            log.error(
                "macOS pointer: the %s button was pressed but its release failed; it may "
                "still be held down.",
                button.value,
            )
            raise

    def scroll(self, dx: float, dy: float) -> None:
        check_finite(dx=dx, dy=dy)
        require_scroll(MACOS_POINTER_CAPABILITIES, dx, dy)
        self._guard_open()
        self._attempt(lambda: self._api.scroll(dx, dy), "scroll")

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._api.close()

    # -- internals --------------------------------------------------------- #

    def _guard_open(self) -> None:
        if self._closed:
            raise PointerBackendError("macOS pointer sink is closed")

    def _attempt(self, action: Any, what: str) -> None:
        """Run one platform call, translating anything it raises into a pointer error.

        PyObjC raises whatever the bridge raises, and a caller holding a `PointerSink`
        can only be expected to catch `PointerError`. An untranslated `objc.error`
        escaping into the daemon's frame loop is how a pointer failure becomes a crash.
        """
        try:
            action()
        except PointerError:
            raise
        except Exception as exc:  # deliberately broad -- see the docstring
            raise PointerBackendError(f"macOS pointer could not {what}: {exc}") from exc
