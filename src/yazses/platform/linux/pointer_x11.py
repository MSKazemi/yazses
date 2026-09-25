"""The X11 ``PointerSink`` backend, over the XTEST extension (ADR-v2-146).

`design/adr/adr-v2-146-pointer-output-boundary.md` puts pointer output behind one
protocol so that Head-Pointer, the voice mouse grid and any future gaze-assisted warp
contain no platform commands. This module is the X11 half of that: it turns the six
`src/yazses/pointer/base.py` operations into XTEST requests and nothing else. It holds no
camera, gaze, head-pose or dwell concept, decides nothing about whether a click is
wanted, and runs no motion loop — one call, one effect.

**Why XTEST and not `xdotool`.** `xdotool` is already used for window control in
`src/yazses/gaze/desktop.py`, and the obvious move would be `xdotool mousemove_relative`.
It is the wrong seam for a pointer: Head-Pointer emits a delta per camera frame, so every
motion would fork a process — tens of milliseconds and a PID each, on the latency path a
user feels directly. python-xlib is already a base dependency of this project on Linux
and the BSDs (see `pyproject.toml`) and is already how the snap-confined global hotkey
works (`src/yazses/platform/linux/hotkey_xgrab.py`), so XTEST costs one long-lived socket
and no subprocess at all. The spec's requirement is only that the external API is
injectable and fakeable, which it is, below.

**The injected seam.** :class:`X11PointerSink` never imports Xlib; it talks to an
:class:`X11PointerConnection`, and :class:`XTestPointerConnection` is the one real
implementation. Tests pass a recorder instead, which is what lets the shared contract
suite run in CI with no display server. The split is drawn so that the X11 *vocabulary*
— button 1 is left, button 5 is a downward wheel notch, an event is only real once the
connection is flushed — lives here in the sink where it can be asserted on, and only the
last untestable step (the actual `xtest_fake_input` call) lives behind the seam.

**Quantisation, because X11 is integer.** XTEST device coordinates are integers and the
wheel has no sub-notch event, so a fractional request is rounded half-away-from-zero at
the connection boundary and the remainder is **not** carried into the next call. A
consumer that produces sub-unit deltas — a slow, deliberate head movement is exactly
that — must accumulate them itself before calling. Accumulating here would hide this
backend's quantum from the caller and make "too small to move the pointer" impossible to
tell from "the X server refused". Neither ADR-v2-146 nor
`design/specs/eye-pointer-output.md` rules on sub-unit deltas; this is the stateless
reading, chosen because it adds no hidden state to a sink the ADR calls deliberately
dumb.

**Signs.** The boundary's convention is fixed by ADR-v2-146: ``+dy`` scrolls down and
``+dx`` scrolls right, unchanged through the boundary. X11 spells the wheel as buttons
rather than an axis — 4 is up, 5 is down, 6 is left, 7 is right — so the mapping from
sign to button happens here, inside the backend, exactly as the protocol requires.

**Availability is reported, never guessed.** :func:`build_x11_pointer_sink` raises
:class:`~yazses.pointer.base.PointerUnsupportedError` when there can be no X11 pointer at
all in this process (python-xlib absent, no ``DISPLAY``, a server without XTEST) and
:class:`~yazses.pointer.base.PointerBackendError` when a reachable-looking display
refused the connection, which may well work on the next attempt. That is the distinction
`src/yazses/pointer/base.py` draws between permanently unsupported and transiently
failed, and a caller picking a backend needs it: the first means try another backend, the
second means tell the user.
"""

from __future__ import annotations

import logging
import math
import os
from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable

from yazses.pointer.base import (
    PointerBackendError,
    PointerButton,
    PointerCapabilities,
    PointerError,
    PointerUnsupportedError,
    check_finite,
    require_absolute,
    require_button,
    require_relative,
    require_scroll,
)

log = logging.getLogger(__name__)

#: The stable identifier this backend reports in ``capabilities().backend``, in logs and
#: in status output. Tests and `yazses doctor` compare against this name, not a literal.
X11_BACKEND_NAME = "x11"

#: X11 core-protocol button numbers. Left/middle/right are 1/2/3 on every X server; the
#: numbering is part of the core protocol, not a driver detail, which is why all three
#: can be promised honestly.
BUTTON_CODES: dict[PointerButton, int] = {
    PointerButton.LEFT: 1,
    PointerButton.MIDDLE: 2,
    PointerButton.RIGHT: 3,
}

#: The wheel, as X11 spells it: four buttons, one per direction, one press-release pair
#: per notch. ``+dy`` is down and ``+dx`` is right at the pointer boundary, so positive
#: deltas map to 5 and 7 and negative ones to 4 and 6.
SCROLL_UP_BUTTON = 4
SCROLL_DOWN_BUTTON = 5
SCROLL_LEFT_BUTTON = 6
SCROLL_RIGHT_BUTTON = 7

#: What XTEST can do, which is all six operations. Absolute motion is included because
#: X11 root-window coordinates *are* the canonical desktop space — one root window spans
#: every monitor of a screen, already in logical pixels — so no conversion is needed and
#: nothing has to be guessed. A sink answers this identically for its whole lifetime.
X11_CAPABILITIES = PointerCapabilities(
    backend=X11_BACKEND_NAME,
    relative_motion=True,
    absolute_motion=True,
    buttons=frozenset(BUTTON_CODES),
    scroll_vertical=True,
    scroll_horizontal=True,
)


@runtime_checkable
class X11PointerConnection(Protocol):
    """The four XTEST requests this backend needs, plus flush and teardown.

    Deliberately thinner than python-xlib and deliberately *not* pure X11: motion takes
    floats, because the boundary above speaks floats and rounding is this layer's job, so
    a recorder standing in for a real display sees exactly what the caller asked for. The
    X11-specific knowledge that survives above it — which button number a click is, how
    many notches a scroll delta is — is the part worth asserting on in a test.
    """

    def motion_relative(self, dx: float, dy: float) -> None:
        """Move the pointer by ``(dx, dy)``; ``+dy`` is toward the bottom of the screen."""
        ...

    def motion_absolute(self, x: float, y: float) -> None:
        """Move the pointer to root-window coordinates ``(x, y)``."""
        ...

    def button(self, code: int, press: bool) -> None:
        """Press (``press=True``) or release an X11 button by its core-protocol number."""
        ...

    def sync(self) -> None:
        """Flush the request queue and wait for the server. Until this runs, nothing moved."""
        ...

    def close(self) -> None:
        """Drop the connection to the display."""
        ...


def notches(value: float) -> int:
    """Whole wheel notches in *value*, rounded half away from zero.

    X11 has no sub-notch wheel event, so ``0.4`` is zero notches and ``0.5`` is one.
    Magnitude only — the direction is already encoded in which button is used.
    """
    return int(math.floor(abs(value) + 0.5))


def device_units(value: float) -> int:
    """Round a logical-pixel delta or position to the integer XTEST wants.

    Half away from zero, so a ``0.5`` request moves rather than vanishing, and symmetric
    about zero, so ``-0.5`` moves the other way by the same amount. ``round()`` is not
    used on purpose: it rounds halves to *even*, so ``round(0.5)`` is 0 while
    ``round(1.5)`` is 2 — the smallest request the caller can make is the one that
    silently does nothing, which is the worst possible place for a surprise.
    """
    return int(math.copysign(math.floor(abs(value) + 0.5), value))


class X11PointerSink:
    """A ``PointerSink`` that drives an X11 display through XTEST.

    Construct it with a connection — :func:`build_x11_pointer_sink` makes the real one,
    a test passes a recorder. Every operation validates at this edge using the shared
    helpers in `src/yazses/pointer/base.py`, so a NaN delta or a button this backend does
    not have never becomes an X request.
    """

    def __init__(self, connection: X11PointerConnection) -> None:
        self._conn = connection
        self._closed = False

    # -- the protocol ------------------------------------------------------ #

    def capabilities(self) -> PointerCapabilities:
        return X11_CAPABILITIES

    def move_relative(self, dx: float, dy: float) -> None:
        check_finite(dx=dx, dy=dy)
        require_relative(X11_CAPABILITIES)
        self._require_open()
        self._perform(lambda: self._conn.motion_relative(dx, dy))

    def move_absolute(self, x: float, y: float) -> None:
        check_finite(x=x, y=y)
        require_absolute(X11_CAPABILITIES)
        self._require_open()
        self._perform(lambda: self._conn.motion_absolute(x, y))

    def click(self, button: PointerButton = PointerButton.LEFT) -> None:
        """Press and release *button* once.

        A failure between the two leaves the button held down, and this backend does not
        try to paper over that: a retry on a connection that just died fails the same
        way, and ADR-v2-146 rule 4 says a failed action is not replayed. The error names
        the button so the layer above — which owns recovery, as the ADR puts safety above
        the sink — can decide what to do.
        """
        require_button(X11_CAPABILITIES, button)
        self._require_open()
        code = BUTTON_CODES[button]

        def emit() -> None:
            self._conn.button(code, True)
            self._conn.button(code, False)

        self._perform(emit, what=f"{button.value} click")

    def scroll(self, dx: float, dy: float) -> None:
        """Scroll by ``(dx, dy)`` in wheel notches; ``+dy`` is down, ``+dx`` is right."""
        check_finite(dx=dx, dy=dy)
        require_scroll(X11_CAPABILITIES, dx, dy)
        self._require_open()
        vertical = SCROLL_DOWN_BUTTON if dy > 0 else SCROLL_UP_BUTTON
        horizontal = SCROLL_RIGHT_BUTTON if dx > 0 else SCROLL_LEFT_BUTTON
        wheel = ((vertical, notches(dy)), (horizontal, notches(dx)))

        def emit() -> None:
            for code, count in wheel:
                for _ in range(count):
                    self._conn.button(code, True)
                    self._conn.button(code, False)

        self._perform(emit, what="scroll")

    def close(self) -> None:
        """Drop the display connection. Idempotent, and it never raises.

        Cleanup runs on the error path too — often *because* the display went away — so a
        second failure here would bury the first. A close that fails is logged and the
        sink is closed regardless: every later operation raises either way.
        """
        if self._closed:
            return
        self._closed = True
        try:
            self._conn.close()
        except Exception as exc:
            log.debug("X11 pointer connection did not close cleanly: %s", exc)

    # -- internals --------------------------------------------------------- #

    def _require_open(self) -> None:
        if self._closed:
            raise PointerBackendError("the X11 pointer sink is closed")

    def _perform(self, emit: Callable[[], None], what: str = "pointer request") -> None:
        """Emit, then flush, translating any platform failure into a backend error.

        The flush is the operation, not an optimisation: XTEST requests sit in
        python-xlib's output buffer until something syncs, so a sink that forgot this
        would pass every recorded-call assertion and move no pointer at all.

        On failure the queue is flushed anyway, best effort. A press that reached the
        buffer before the error must not be left there to ride out on the *next*
        operation's flush — that is precisely the stale command ADR-v2-146 rule 4
        forbids, and it would arrive attached to an action the user asked for later.
        """
        try:
            emit()
        except PointerError:
            raise
        except Exception as exc:
            self._flush_quietly()
            raise PointerBackendError(f"X11 {what} failed: {exc}") from exc
        try:
            self._conn.sync()
        except Exception as exc:
            raise PointerBackendError(f"X11 {what} was not delivered: {exc}") from exc

    def _flush_quietly(self) -> None:
        try:
            self._conn.sync()
        except Exception as exc:
            log.debug("X11 pointer flush after a failed request also failed: %s", exc)


class XTestPointerConnection:
    """:class:`X11PointerConnection` over python-xlib's XTEST extension.

    Holds the display and the ``Xlib.X`` constants it was opened with, so the import
    itself stays in :func:`open_xtest_connection` and this class is constructible from a
    test with two stand-ins.
    """

    def __init__(self, display: Any, x: Any) -> None:
        self._display = display
        self._x = x

    def motion_relative(self, dx: float, dy: float) -> None:
        # `detail` is the X Test protocol's relative flag for MotionNotify: non-zero
        # means x/y are a distance from where the pointer is, not a position.
        self._display.xtest_fake_input(
            self._x.MotionNotify, detail=1, x=device_units(dx), y=device_units(dy)
        )

    def motion_absolute(self, x: float, y: float) -> None:
        # detail=0 makes x/y a position rather than a delta. `root` is left at
        # python-xlib's default of X.NONE, which XTest reads as the pointer's current
        # root window — deliberately not a hardcoded screen 0, which on a multi-screen X
        # display would teleport the pointer off whichever screen the user is on.
        self._display.xtest_fake_input(
            self._x.MotionNotify, detail=0, x=device_units(x), y=device_units(y)
        )

    def button(self, code: int, press: bool) -> None:
        event = self._x.ButtonPress if press else self._x.ButtonRelease
        self._display.xtest_fake_input(event, detail=code)

    def sync(self) -> None:
        self._display.sync()

    def close(self) -> None:
        self._display.close()


def _load_xlib() -> tuple[Any, Any]:
    """Import python-xlib lazily and return ``(Xlib.X, Xlib.display)``.

    Inside the function per the project's third non-negotiable rule: python-xlib is a
    Linux/BSD-only dependency, so a module-level import would make this file unimportable
    on macOS and Windows — where the sibling backends live and where the shared contract
    suite still has to run.
    """
    try:
        from Xlib import X
        from Xlib import display as xdisplay
    except ImportError as exc:
        raise PointerUnsupportedError(
            "python-xlib is not installed, so there is no X11 pointer backend here"
        ) from exc
    return X, xdisplay


def open_xtest_connection() -> XTestPointerConnection:
    """Open a real XTEST connection, or say precisely why there is none.

    ``PointerUnsupportedError`` for the three permanent answers — no python-xlib, no
    ``DISPLAY``, a server without XTEST — and ``PointerBackendError`` for a display that
    exists and refused us, which is the one worth retrying or showing the user.
    """
    x, xdisplay = _load_xlib()
    name = os.environ.get("DISPLAY", "")
    if not name:
        raise PointerUnsupportedError(
            "DISPLAY is not set, so there is no X11 server to send pointer events to "
            "(a Wayland session needs the RemoteDesktop portal path, not XTEST)"
        )
    try:
        display = xdisplay.Display()
    except Exception as exc:
        raise PointerBackendError(f"cannot reach the X11 display {name!r}: {exc}") from exc
    if not display.has_extension("XTEST"):
        try:
            display.close()
        except Exception as exc:
            log.debug("closing the XTEST-less display failed: %s", exc)
        raise PointerUnsupportedError(
            f"the X11 server on {name!r} has no XTEST extension, so synthetic pointer "
            "events cannot be sent to it"
        )
    return XTestPointerConnection(display=display, x=x)


def build_x11_pointer_sink() -> X11PointerSink:
    """Build the X11 pointer sink, opening the display now rather than on first move.

    Failing at construction is the point: a caller choosing a backend learns immediately
    that X11 is unavailable and can fall back, instead of discovering it from the first
    head movement a user makes.
    """
    return X11PointerSink(open_xtest_connection())
