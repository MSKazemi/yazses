"""The X11 ``ClickObserver`` backend, over XInput2 raw button events (#607, EYE-GAZE-003).

Implicit gaze calibration (`design/specs/eye-implicit-calibration.md`) needs one thing from
the desktop: *when* the user clicked and *where the pointer was*. `src/yazses/gaze/clicks.py`
is the boundary — a ``ClickEvent`` has exactly a timestamp and two coordinates — and this
module is the X11 producer behind it. It is the first real backend; #397 shipped the seam
with a CI fake and left ``Platform.click_observer_factory`` ``None`` everywhere.

**Why XInput2 raw events, and why on the root window.** A core-protocol ``ButtonPress``
selected on the root window never arrives for a click inside an application: X delivers a
button event to the clients that selected it on the window under the pointer and stops
there, so the only way to see every click with core events is a pointer grab, which would
steal the click from the application. XInput2's ``XI_RawButtonPress`` is the event made for
observers: it is delivered to every client that selected it on the root window, regardless
of which window the press lands in, takes no grab, and never routes the press away from its
real recipient. It also carries **no window** — a raw event has a device, a time, a button
number and the raw axis values, nothing else — which is a privacy property we get from the
protocol rather than from discipline. python-xlib (``>=0.33``, already a base dependency on
Linux and the BSDs) exposes ``XISelectEvents`` and the raw-event constants, so no new
dependency and no subprocess. ``XRecord`` was the alternative; it would deliver the same
press as a replayed core event and needs a second connection by design. Raw events are the
smaller mechanism, and they work on XWayland too — which is exactly why
`platform/linux/__init__.py` refuses to register this backend on a Wayland session:
there it would see only the X clients' clicks and silently feed the refiner a plausible,
partial sample stream.

**Position.** A raw event has no ``root_x``/``root_y``, so the pointer is queried at event
time with ``QueryPointer`` on the root window. Root-window coordinates are the canonical
space the gaze calibration is fitted in on X11 — `gaze/display.py` reads the same
framebuffer space from ``xrandr`` and reports ``scale=1.0`` for every output, and
`gaze/topology.py` names it ``desktop-logical-px`` — so the number goes into ``ClickEvent``
unchanged (ADR-v2-149: convert at the platform boundary, once; here the conversion is the
identity). The X server's millisecond ``time`` field is **not** used: the association in
`gaze/association.py` subtracts the click's time from a gaze sample's, and gaze samples are
stamped with ``time.monotonic``, so the click must be too.

**Which buttons.** 1, 2 and 3 — left, middle, right, fixed by the core protocol. The wheel
is buttons 4–7 on X11 and a notch over a page is the commonest "press" a desktop sees; it
is not an aim point and is dropped before the pointer is even queried. 8 and 9 (browser
back/forward on most mice) are dropped for the same reason.

**The thread, and how it stops.** Events are read on a daemon thread over a **separate**
display connection: the hotkey grab and the XTEST pointer each hold their own, and a
connection that blocks in ``next_event`` must never be one another feature is waiting to
write to. The loop does not block in ``next_event`` at all — it waits in ``select`` on the
display's socket for at most ``poll_interval_s`` and reads only what is pending — so
``stop()`` is a flag plus a short join, with no second connection or synthetic wake-up
event to keep correct. The display is closed by the loop thread on its way out, which is
the one thread that was using it.

**Containment.** ``start`` raises ``ClickObserverError`` with a plain sentence for every
refusal (no ``DISPLAY``, no python-xlib, no XInput, XInput 1, a display that refused the
connection); `gaze/refine_runtime.py` turns that into the dormant reason the daemon logs.
A consumer callback that raises is logged once and the loop continues; a connection that
dies mid-loop is logged once and the loop ends. Nothing here can reach dictation.

**The injected seam.** :class:`X11ClickObserver` never imports Xlib; it drives an
:class:`X11ClickConnection`, and :class:`XInputClickConnection` is the one real
implementation. Tests script the former and feed the latter a fake display whose
``fileno`` is a real pipe, so the ``select`` wait is the code that actually runs.
"""

from __future__ import annotations

import logging
import os
import select
import struct
import threading
import time
from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable

from yazses.gaze.clicks import ClickEvent, ClickObserverError

log = logging.getLogger(__name__)

__all__ = [
    "CLICK_BUTTONS",
    "POLL_INTERVAL_S",
    "X11_CLICK_BACKEND_NAME",
    "X11ClickConnection",
    "X11ClickObserver",
    "XInputClickConnection",
    "build_x11_click_observer",
    "open_xinput_connection",
]

#: The stable identifier this backend reports in logs and status output.
X11_CLICK_BACKEND_NAME = "x11-xinput2"

#: X11 core-protocol button numbers that are a click aimed at a point: left, middle, right.
#: 4–7 are the wheel and 8+ are extra buttons (back/forward); none of those is an aim point.
CLICK_BUTTONS: frozenset[int] = frozenset({1, 2, 3})

#: How long the loop waits for the display socket before re-checking the stop flag. The
#: only latency it adds is to ``stop()``, never to a click: a press wakes ``select`` at once.
POLL_INTERVAL_S = 0.25

#: The X protocol's extension name, as ``QueryExtension`` wants it.
_XINPUT_EXTENSION = "XInputExtension"

#: ``XIRawEvent`` on the wire: ``deviceid`` Card16, ``time`` Card32, then ``detail`` Card32 —
#: the button number — at byte offset 6. Used only when python-xlib hands the generic
#: event's payload back undecoded.
_RAW_DETAIL_OFFSET = 6
_RAW_DETAIL_FORMAT = "=I"
_RAW_HEADER_LENGTH = 16


@runtime_checkable
class X11ClickConnection(Protocol):
    """The three things the observer needs from a display, and nothing it should not.

    Deliberately narrower than python-xlib: there is no way to ask which window a press
    landed in, read a property or query a device, because the observer has no use for any
    of it and `gaze/clicks.py` wants that to be a structural fact.
    """

    def next_button(self, timeout_s: float) -> int | None:
        """Wait up to *timeout_s* for the next raw button press; its button number, or None."""
        ...

    def pointer_position(self) -> tuple[int, int]:
        """The pointer's current root-window position, in X11 framebuffer pixels."""
        ...

    def close(self) -> None:
        """Drop the display connection."""
        ...


class X11ClickObserver:
    """A ``ClickObserver`` that reads XInput2 raw presses on its own thread.

    *open_connection* is called once per ``start`` and may raise
    :class:`ClickObserverError`; the default opens a real XInput2 connection. *clock* is
    what stamps the event — ``time.monotonic`` unless a test says otherwise, because the
    association compares it with the shared perception source's stamps.
    """

    def __init__(
        self,
        open_connection: Callable[[], X11ClickConnection] | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        poll_interval_s: float = POLL_INTERVAL_S,
    ) -> None:
        self._open = open_connection or open_xinput_connection
        self._clock = clock
        self._poll = max(0.001, float(poll_interval_s))
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    # -- the protocol ------------------------------------------------------ #

    @property
    def is_running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def start(self, on_click: Callable[[ClickEvent], None]) -> None:
        """Open the display and begin delivering clicks; raise ``ClickObserverError`` if not.

        A second ``start`` while running is a no-op (the Protocol's contract). Opening
        happens before the thread exists, so a refusal leaves nothing to stop and nothing
        leaked — the caller gets a sentence, not a half-started observer.
        """
        with self._lock:
            if self.is_running:
                return
            connection = self._open()  # raises ClickObserverError with the reason
            stop = threading.Event()
            thread = threading.Thread(
                target=self._run,
                args=(connection, on_click, stop),
                name="yazses-click-observer-x11",
                daemon=True,
            )
            try:
                thread.start()
            except Exception as exc:
                _close_quietly(connection)
                raise ClickObserverError(
                    f"the X11 click observer thread could not start ({type(exc).__name__})"
                ) from exc
            self._stop = stop
            self._thread = thread

    def stop(self) -> None:
        """Stop the loop and release the display. Idempotent; never raises.

        The loop thread owns the connection and closes it on its way out, so this only has
        to raise the flag and wait: at most one poll interval plus whatever a pending
        callback takes. A thread that is somehow still alive after that is left to die
        with the process (it is a daemon thread) and noted at debug level.
        """
        with self._lock:
            thread = self._thread
            self._stop.set()
            self._thread = None
        if thread is None or not thread.is_alive():
            return
        try:
            thread.join(timeout=self._poll * 4 + 1.0)
        except Exception as exc:  # pragma: no cover - join raises only on misuse
            log.debug("joining the X11 click observer thread failed: %s", exc)
        if thread.is_alive():
            log.debug("the X11 click observer thread did not stop within its timeout")

    # -- the loop ---------------------------------------------------------- #

    def _run(
        self,
        connection: X11ClickConnection,
        on_click: Callable[[ClickEvent], None],
        stop: threading.Event,
    ) -> None:
        callback_failures = 0
        try:
            while not stop.is_set():
                try:
                    button = connection.next_button(self._poll)
                except Exception as exc:
                    log.warning(
                        "X11 click observer lost its display connection (%s: %s); implicit "
                        "refinement stops collecting until the daemon restarts",
                        type(exc).__name__, exc,
                    )
                    return
                if button is None or button not in CLICK_BUTTONS:
                    continue
                try:
                    x, y = connection.pointer_position()
                    event = ClickEvent(self._clock(), float(x), float(y))
                except Exception as exc:
                    # A failed QueryPointer (the display went away between the event and
                    # the query) is the same loss as above, reported the same way.
                    log.warning(
                        "X11 click observer could not read the pointer position (%s: %s); "
                        "implicit refinement stops collecting until the daemon restarts",
                        type(exc).__name__, exc,
                    )
                    return
                try:
                    on_click(event)
                except Exception:
                    callback_failures += 1
                    if callback_failures == 1:
                        log.warning(
                            "the click consumer raised; later failures are logged at debug",
                            exc_info=True,
                        )
                    else:
                        log.debug("the click consumer raised again (%d so far)", callback_failures)
        finally:
            _close_quietly(connection)


def _close_quietly(connection: X11ClickConnection) -> None:
    try:
        connection.close()
    except Exception as exc:
        log.debug("X11 click connection did not close cleanly: %s", exc)


class XInputClickConnection:
    """:class:`X11ClickConnection` over python-xlib's XInput2 extension.

    Holds the open display, its root window, the ``Xlib.X`` constants module, the
    ``Xlib.ext.xinput`` module and XInput's major opcode, so every import stays in
    :func:`open_xinput_connection` and this class is constructible from a test with
    stand-ins — including a display whose ``fileno`` is a pipe.
    """

    def __init__(self, display: Any, root: Any, x: Any, xinput: Any, opcode: int) -> None:
        self._display = display
        self._root = root
        self._x = x
        self._xinput = xinput
        self._opcode = int(opcode)

    def next_button(self, timeout_s: float) -> int | None:
        """One raw press's button number, or None when nothing arrived within *timeout_s*.

        ``select`` on the display socket is the wait; ``pending_events`` then reads what is
        there without blocking, and ``next_event`` is only called for an event that is
        already queued. A readable socket that turns out to hold a reply rather than an
        event simply yields None this round. Only the first queued event is examined per
        call, so a burst is drained one call at a time and the stop flag is honoured
        between presses.
        """
        if self._display.pending_events() == 0:
            readable, _, _ = select.select([self._display.fileno()], [], [], max(0.0, timeout_s))
            if not readable or self._display.pending_events() == 0:
                return None
        event = self._display.next_event()
        if (
            getattr(event, "type", None) != self._x.GenericEvent
            or getattr(event, "extension", None) != self._opcode
            or getattr(event, "evtype", None) != self._xinput.RawButtonPress
        ):
            return None
        return _button_of(getattr(event, "data", None))

    def pointer_position(self) -> tuple[int, int]:
        reply = self._root.query_pointer()
        return int(reply.root_x), int(reply.root_y)

    def close(self) -> None:
        self._display.close()


def _button_of(data: Any) -> int | None:
    """The ``detail`` of an ``XIRawEvent`` payload, parsed or still on the wire."""
    detail = getattr(data, "detail", None)
    if detail is not None:
        return int(detail)
    if isinstance(data, (bytes, bytearray)) and len(data) >= _RAW_HEADER_LENGTH:
        return int(struct.unpack_from(_RAW_DETAIL_FORMAT, data, _RAW_DETAIL_OFFSET)[0])
    return None


def _load_xlib() -> tuple[Any, Any, Any, Any]:
    """Import python-xlib lazily: ``(Xlib.X, Xlib.display, Xlib.ext.xinput, Xlib.protocol.rq)``.

    Inside the function per the project's third non-negotiable rule: python-xlib is a
    Linux/BSD-only dependency, and the sibling backends' test modules import this
    package on macOS and Windows.
    """
    try:
        from Xlib import X
        from Xlib import display as xdisplay
        from Xlib.ext import xinput
        from Xlib.protocol import rq
    except ImportError as exc:
        raise ClickObserverError(
            "python-xlib is not installed, so there is no X11 click observer here"
        ) from exc
    return X, xdisplay, xinput, rq


def open_xinput_connection() -> XInputClickConnection:
    """Open a display, select raw button presses on its root, or say precisely why not.

    Every refusal is a :class:`ClickObserverError` whose message is a sentence a user can
    act on. A display that was opened and then found wanting is closed before raising.
    """
    x, xdisplay, xinput, rq = _load_xlib()
    name = os.environ.get("DISPLAY", "")
    if not name:
        raise ClickObserverError(
            "DISPLAY is not set, so there is no X11 server whose clicks could be observed "
            "(a Wayland session has no global click stream; see `yazses doctor`)"
        )
    try:
        display = xdisplay.Display()
    except Exception as exc:
        raise ClickObserverError(f"cannot reach the X11 display {name!r}: {exc}") from exc

    def refuse(message: str) -> ClickObserverError:
        try:
            display.close()
        except Exception as exc:
            log.debug("closing the refused display failed: %s", exc)
        return ClickObserverError(message)

    if not display.has_extension(_XINPUT_EXTENSION):
        raise refuse(
            f"the X11 server on {name!r} has no {_XINPUT_EXTENSION}, so clicks cannot be "
            "observed without grabbing the pointer, which this backend will not do"
        )
    try:
        version = display.xinput_query_version()
        major = int(getattr(version, "major_version", 0))
    except Exception as exc:
        raise refuse(f"the X11 server on {name!r} did not answer an XInput version query: {exc}")
    if major < 2:
        raise refuse(
            f"the X11 server on {name!r} speaks XInput {major}, and raw button events need "
            "XInput 2"
        )
    try:
        opcode = int(display.get_extension_major(_XINPUT_EXTENSION))
        root = display.screen().root
        # python-xlib decodes XI2 *device* events but registers no struct for raw ones, so
        # register the XIRawEvent header ourselves: ``detail`` is then a parsed field. The
        # wire layout is fixed by the XI2 protocol; `_button_of` also reads the bytes
        # directly if a python-xlib without this hook hands them back undecoded.
        add_event_data = getattr(display, "ge_add_event_data", None)
        if add_event_data is not None:
            raw_header = rq.Struct(
                xinput.DEVICEID("deviceid"),
                rq.Card32("time"),
                rq.Card32("detail"),
                xinput.DEVICEID("sourceid"),
                rq.Card16("valuators_len"),
                rq.Card32("flags"),
                rq.Pad(4),
            )
            add_event_data(opcode, xinput.RawButtonPress, raw_header)
        # AllDevices, because raw events are generated by the physical (slave) devices and
        # XI_RawButtonPress is only ever delivered for a selection on the root window. No
        # grab is taken anywhere: the press still reaches the window it was aimed at.
        root.xinput_select_events([(xinput.AllDevices, xinput.RawButtonPressMask)])
        display.sync()
    except Exception as exc:
        raise refuse(
            f"the X11 server on {name!r} refused the raw-button selection: {exc}"
        ) from exc
    return XInputClickConnection(display=display, root=root, x=x, xinput=xinput, opcode=opcode)


def build_x11_click_observer() -> X11ClickObserver:
    """The Linux bundle's ``click_observer_factory``: constructs, opens nothing.

    The display is opened by ``start``, which only the refinement runtime calls, and only
    when ``[gaze_refine] enabled = true`` — so an ordinary dictation start-up takes no
    extra connection and selects no event.
    """
    return X11ClickObserver()
