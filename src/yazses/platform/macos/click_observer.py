"""macOS click observer — a listen-only Quartz event tap for implicit gaze calibration (#607).

The macOS producer behind the ``ClickObserver`` seam in ``src/yazses/gaze/clicks.py``
(#397). Implicit refinement (``[gaze_refine]``) treats an ordinary click as "the user was
looking there a moment ago"; all it needs from the desktop is *where* and *when*, and this
module hands it exactly that: one :class:`~yazses.gaze.clicks.ClickEvent` per mouse-down,
``(time.monotonic(), x, y)``, from a ``CGEventTap`` that cannot do anything else.

**Listen-only, structurally.** The tap is created with ``kCGEventTapOptionListenOnly``.
CoreGraphics then delivers each matching event to the callback *after* the fact and
ignores the callback's return value, so this process can never swallow, delay, reorder
or alter a click — unlike the default (active-filter) option, where a slow or buggy
callback is a filter in front of every click on the Mac. The mask asks for the three
mouse-down types only (left, right, "other"), never mouse-up, motion, drag or scroll, and
the callback drops anything else regardless. ``tests/test_click_observer_macos.py``
asserts the exact option constant, because it is the privacy guarantee.

**What is emitted and what is not.** ``CGEventGetLocation`` and a monotonic timestamp.
Which button, which window, what was under the pointer, what was typed before or after:
none of it is read, and ``ClickEvent`` has no field that could carry it. Coordinates pass
through unchanged: CoreGraphics global display coordinates are points, origin at the main
display's top-left, y down, negative on a monitor left of or above it (``pointer.py``,
``gaze/topology.py``) — which is already the canonical ADR-v2-149 desktop space for
macOS. A Cocoa-style y-flip belongs to ``NSEvent``/``NSScreen``, which this never touches.

**Permission.** A ``CGEventTap`` over input events needs the same two grants the dictation
key's tap needs — **Input Monitoring** and **Accessibility** (``hotkey.py``,
``permissions.py``, #182). A missing grant does not raise; ``CGEventTapCreate`` returns
NULL, and NULL does not say which grant is absent. :meth:`MacClickObserver.start` turns
that into a :class:`~yazses.gaze.clicks.ClickObserverError` naming both panes and
``yazses doctor``, which reports them separately. Nothing is prompted for here: the hotkey
already requested Input Monitoring when the daemon started, the grant is per process, and a
denied observer must leave dictation exactly as it was — the refiner stays dormant with the
reason surfaced (``daemon.py``, ``yazses gaze status``).

**Threading.** The tap's run-loop source needs a ``CFRunLoop`` to be served from, and the
daemon's main thread is busy. ``start()`` creates the tap on the caller's thread (so a NULL
tap is reported synchronously) and then runs a dedicated daemon thread whose own run loop
hosts the source. The loop is driven with ``CFRunLoopRunInMode`` in one-second slices that
re-check a stop flag rather than a bare ``CFRunLoopRun``: ``CFRunLoopStop`` on a loop that
is not yet running is a no-op, and a stop that landed in that window would otherwise leave
the thread blocked forever. ``stop()`` is idempotent, never raises, and joins with a timeout.

**Never executed on macOS.** Everything here is written from Apple's API documentation and
the sibling hotkey tap, and checked against a fake ``Quartz`` on Linux. No line of it has
run against a real ``CGEventTapCreate``; whether a tap hosted on a secondary thread's run
loop stays enabled across a long session, and whether Input Monitoring plus Accessibility is
the whole set of grants, is hardware evidence this repository does not yet have. A CI
runner's TCC is permissive, so a runner reporting the permission as ``[OK]`` proves nothing.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from yazses.gaze.clicks import ClickEvent, ClickObserverError

log = logging.getLogger(__name__)

__all__ = ["MacClickObserver", "TAP_DENIED", "THREAD_NAME"]

#: The dedicated run-loop thread; named so tests and ``py-spy`` can find it.
THREAD_NAME = "yazses-mac-click-observer"

#: How long one ``CFRunLoopRunInMode`` slice lasts before the stop flag is re-read. The
#: tap is served the moment an event arrives regardless; this only bounds how long a
#: stop() that raced the loop's start can take to be noticed.
RUN_LOOP_SLICE_S = 1.0

#: ``stop()`` waits this long for the loop thread; a slice plus margin. It then logs and
#: returns rather than hang the daemon's shutdown.
JOIN_TIMEOUT_S = RUN_LOOP_SLICE_S + 1.0

#: The one refusal, mirroring ``hotkey.tap_failure_message``: a NULL tap cannot say which
#: of the two grants is missing, so neither is claimed to be fine.
TAP_DENIED = (
    "CGEventTapCreate returned NULL, so YazSes cannot observe clicks for implicit gaze "
    "calibration. A listen-only input tap needs BOTH Input Monitoring and Accessibility; "
    "dictation keeps working without it.\n"
    "  System Settings -> Privacy & Security -> Input Monitoring -> enable YazSes\n"
    "  System Settings -> Privacy & Security -> Accessibility -> enable YazSes\n"
    "Then quit and relaunch YazSes -- a grant is read when the tap is created. "
    "Run `yazses doctor` to see both permissions separately."
)

#: The attribute names of the three mouse-down event types. Names, not values, because the
#: values exist only once PyObjC is imported and this module must import on Linux.
_MOUSE_DOWN_TYPES = ("kCGEventLeftMouseDown", "kCGEventRightMouseDown", "kCGEventOtherMouseDown")


def _load_quartz() -> Any:
    """Import the PyObjC Quartz bridge, at the moment it is first needed.

    Lazy and inside a function for the reason every other PyObjC import in this package
    is: a base install on Linux must import this module without PyObjC present.
    """
    import Quartz  # type: ignore[import-not-found]

    return Quartz


class MacClickObserver:
    """``ClickObserver`` for macOS over a listen-only ``CGEventTap``.

    Pass *quartz* (a module-shaped object) to test it; leave it out and PyObjC's
    ``Quartz`` is imported on :meth:`start`, not on construction — this class is the
    platform bundle's ``click_observer_factory`` and ``get_platform()`` merely running
    must not touch Input Monitoring. *load_quartz* replaces that import.
    """

    def __init__(
        self,
        quartz: Any | None = None,
        *,
        load_quartz: Callable[[], Any] | None = None,
    ) -> None:
        # ``None`` until start() loads the bridge; typed Any because stop() only reads it
        # once a thread exists, and a thread exists only after a successful load.
        self._quartz: Any = quartz
        self._load_quartz = load_quartz if load_quartz is not None else _load_quartz
        self._lock = threading.Lock()
        self._on_click: Callable[[ClickEvent], None] | None = None
        self._tap: Any = None
        self._source: Any = None
        self._runloop: Any = None
        self._thread: threading.Thread | None = None
        self._stop_requested = False
        self._mouse_down_types: frozenset[int] = frozenset()
        self._disabled_types: frozenset[int] = frozenset()
        self._callback_failures = 0

    # -- the Protocol ------------------------------------------------------ #

    def start(self, on_click: Callable[[ClickEvent], None]) -> None:
        """Create the tap and begin delivering clicks to *on_click* from a daemon thread.

        Raises :class:`ClickObserverError` when the Quartz bridge is missing or
        ``CGEventTapCreate`` returns NULL (no Input Monitoring / Accessibility grant), in
        which case no thread is started and nothing is attached to any run loop. Starting
        an already-started observer is a no-op and keeps the first callback.
        """
        with self._lock:
            if self._thread is not None:
                return
            try:
                quartz = self._q()
            except ImportError as exc:
                raise ClickObserverError(
                    "the PyObjC Quartz bridge (pyobjc-framework-Quartz) is not installed, so "
                    f"YazSes cannot observe clicks on this Mac: {exc}"
                ) from exc

            self._mouse_down_types = frozenset(
                int(getattr(quartz, name)) for name in _MOUSE_DOWN_TYPES
            )
            self._disabled_types = frozenset(
                (
                    int(quartz.kCGEventTapDisabledByTimeout),
                    int(quartz.kCGEventTapDisabledByUserInput),
                )
            )
            mask = 0
            for event_type in self._mouse_down_types:
                mask |= quartz.CGEventMaskBit(event_type)

            tap = quartz.CGEventTapCreate(
                quartz.kCGSessionEventTap,
                quartz.kCGHeadInsertEventTap,
                quartz.kCGEventTapOptionListenOnly,  # never an active filter -- see module doc
                mask,
                self._on_event,
                None,
            )
            if not tap:
                raise ClickObserverError(TAP_DENIED)

            self._tap = tap
            self._on_click = on_click
            self._stop_requested = False
            self._callback_failures = 0
            self._source = quartz.CFMachPortCreateRunLoopSource(None, tap, 0)
            ready = threading.Event()
            thread = threading.Thread(
                target=self._run, args=(quartz, ready), name=THREAD_NAME, daemon=True
            )
            self._thread = thread
            thread.start()
        # Outside the lock: the loop thread needs nothing from it, and a caller's stop()
        # racing this start must be able to take the lock.
        if not ready.wait(timeout=JOIN_TIMEOUT_S):
            log.warning("macOS click observer: the run-loop thread did not report ready")
        else:
            log.info("macOS click observer: listen-only mouse-down tap enabled")

    def stop(self) -> None:
        """Disable the tap, stop its run loop, release the port. Idempotent; never raises."""
        with self._lock:
            thread = self._thread
            if thread is None:
                return
            self._thread = None
            self._stop_requested = True
            self._on_click = None  # a late event from a tap not yet torn down is dropped
            tap, runloop, quartz = self._tap, self._runloop, self._quartz
        try:
            if tap is not None:
                quartz.CGEventTapEnable(tap, False)
        except Exception:
            log.exception("macOS click observer: CGEventTapEnable(False) raised")
        try:
            if runloop is not None:
                quartz.CFRunLoopStop(runloop)
        except Exception:
            log.exception("macOS click observer: CFRunLoopStop raised")
        if thread is not threading.current_thread():
            thread.join(timeout=JOIN_TIMEOUT_S)
            if thread.is_alive():
                log.warning("macOS click observer: run-loop thread did not exit in time")
        try:
            if tap is not None:
                quartz.CFMachPortInvalidate(tap)
        except Exception:
            log.exception("macOS click observer: CFMachPortInvalidate raised")
        with self._lock:
            self._tap = None
            self._source = None
            self._runloop = None

    # -- internals --------------------------------------------------------- #

    def _q(self) -> Any:
        if self._quartz is None:
            self._quartz = self._load_quartz()
        return self._quartz

    def _run(self, quartz: Any, ready: threading.Event) -> None:
        """The dedicated thread: own run loop, source attached, tap enabled, then serve."""
        try:
            runloop = quartz.CFRunLoopGetCurrent()
            with self._lock:
                self._runloop = runloop
                source, tap = self._source, self._tap
            quartz.CFRunLoopAddSource(runloop, source, quartz.kCFRunLoopCommonModes)
            quartz.CGEventTapEnable(tap, True)
        except Exception:
            log.exception("macOS click observer: could not attach the tap to a run loop")
            ready.set()
            return
        ready.set()
        try:
            # Slices, not CFRunLoopRun: CFRunLoopStop on a loop that is not running yet is
            # a no-op, and a stop() that raced this thread's start must still be seen.
            while not self._stop_requested:
                quartz.CFRunLoopRunInMode(quartz.kCFRunLoopDefaultMode, RUN_LOOP_SLICE_S, False)
        except Exception:
            log.exception("macOS click observer: run loop raised; clicks stop here")
        finally:
            try:
                quartz.CFRunLoopRemoveSource(runloop, source, quartz.kCFRunLoopCommonModes)
            except Exception:
                log.exception("macOS click observer: CFRunLoopRemoveSource raised")

    def _on_event(self, _proxy: Any, event_type: Any, event: Any, _refcon: Any) -> Any:
        """The ``CGEventTap`` callback. Listen-only: the return value is ignored by macOS."""
        try:
            kind = int(event_type)
            if kind in self._disabled_types:
                # macOS disabled the tap (slow callback, or on user input). A notification,
                # not a click: re-enable and emit nothing.
                tap = self._tap
                if tap is not None:
                    self._q().CGEventTapEnable(tap, True)
                return event
            if kind not in self._mouse_down_types:
                return event  # belt and braces over the mask
            on_click = self._on_click
            if on_click is None:
                return event  # stopped; a late event is dropped
            location = self._q().CGEventGetLocation(event)
            try:
                click = ClickEvent(time.monotonic(), float(location.x), float(location.y))
            except (TypeError, ValueError) as exc:
                log.warning("macOS click observer: dropped a click with a non-finite location: %s", exc)
                return event
            try:
                on_click(click)
            except Exception:
                self._callback_failures += 1
                if self._callback_failures == 1:
                    log.exception(
                        "macOS click observer: on_click raised; further failures are counted, "
                        "not logged"
                    )
                else:
                    log.debug(
                        "macOS click observer: on_click raised again (%d so far)",
                        self._callback_failures,
                    )
        except Exception:
            # Nothing may escape into the Quartz bridge from here.
            log.exception("macOS click observer: event callback raised")
        return event
