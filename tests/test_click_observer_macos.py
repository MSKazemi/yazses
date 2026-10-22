"""The macOS click observer, on Linux, against a fake Quartz (#607, the macOS part).

`src/yazses/platform/macos/click_observer.py` is the first real producer behind the
`ClickObserver` seam #397 shipped. These tests drive the real :class:`MacClickObserver`
through the callback it registers with a hand-written stand-in for the PyObjC ``Quartz``
module, so the event mask, the tap option, the coordinate pass-through, the re-enable on a
disabled tap and the stop/teardown order are covered on a machine without CoreGraphics.

The one assertion that matters most is the tap option: ``kCGEventTapOptionListenOnly`` is
what makes this backend structurally unable to swallow or alter a click. The rest pins the
privacy contract from ``tests/test_gaze_click_capture.py`` at the platform edge -- each
mouse-down becomes exactly ``(monotonic timestamp, x, y)`` and nothing else.

**What these tests do not prove.** Nothing here has spoken to a real ``CGEventTapCreate``.
A green run says the backend asks CoreGraphics for the right thing; whether macOS then
delivers clicks -- whether Input Monitoring plus Accessibility is the whole set of grants,
whether a tap created from a daemon thread's run loop stays enabled -- is hardware evidence
no test in this repository has. A CI runner's TCC is permissive, so a runner saying ``[OK]``
proves nothing either.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pytest

from yazses.gaze.clicks import ClickEvent, ClickObserver, ClickObserverError

# --------------------------------------------------------------------------- #
# A fake Quartz module
# --------------------------------------------------------------------------- #


class _FakeTap:
    def __init__(self, callback: Callable[..., Any]) -> None:
        self.callback = callback


class _FakeRunLoop:
    def __init__(self) -> None:
        self.stopped = threading.Event()


class _FakeQuartz:
    """Just enough of PyObjC's ``Quartz`` for the observer: constants and the calls it makes.

    Every call is recorded by name so a test can assert both what was asked and what was
    *not*. ``CFRunLoopRunInMode`` blocks until ``CFRunLoopStop`` or its slice elapses,
    which is what lets the observer's dedicated thread behave as on a Mac.
    """

    # CGEventType values, as CoreGraphics numbers them.
    kCGEventLeftMouseDown = 1
    kCGEventLeftMouseUp = 2
    kCGEventRightMouseDown = 3
    kCGEventRightMouseUp = 4
    kCGEventMouseMoved = 5
    kCGEventLeftMouseDragged = 6
    kCGEventScrollWheel = 22
    kCGEventOtherMouseDown = 25
    kCGEventOtherMouseUp = 26
    kCGEventTapDisabledByTimeout = 0xFFFFFFFE
    kCGEventTapDisabledByUserInput = 0xFFFFFFFF
    # Tap placement and options; distinct sentinels so a mix-up is visible.
    kCGSessionEventTap = "session-tap"
    kCGHIDEventTap = "hid-tap"
    kCGHeadInsertEventTap = "head-insert"
    kCGEventTapOptionDefault = "option-default-ACTIVE-FILTER"
    kCGEventTapOptionListenOnly = "option-listen-only"
    kCFRunLoopCommonModes = "common-modes"
    kCFRunLoopDefaultMode = "default-mode"

    def __init__(self, *, create_tap: bool = True) -> None:
        self.create_tap = create_tap
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.tap: _FakeTap | None = None
        self.loop = _FakeRunLoop()
        self.run_loop_thread_names: list[str] = []
        self.on_slice: Callable[[], None] | None = None

    def _record(self, name: str, *args: Any) -> None:
        self.calls.append((name, args))

    def named(self, name: str) -> list[tuple[Any, ...]]:
        return [args for called, args in self.calls if called == name]

    # -- event taps -------------------------------------------------------- #

    def CGEventMaskBit(self, event_type: int) -> int:
        return 1 << event_type

    def CGEventTapCreate(
        self, location: Any, place: Any, options: Any, mask: int, callback: Any, refcon: Any
    ) -> _FakeTap | None:
        self._record("CGEventTapCreate", location, place, options, mask, callback, refcon)
        if not self.create_tap:
            return None
        self.tap = _FakeTap(callback)
        return self.tap

    def CGEventTapEnable(self, tap: Any, enabled: bool) -> None:
        self._record("CGEventTapEnable", tap, enabled)

    def CFMachPortCreateRunLoopSource(self, allocator: Any, tap: Any, order: int) -> Any:
        self._record("CFMachPortCreateRunLoopSource", allocator, tap, order)
        return ("source-for", tap)

    def CFMachPortInvalidate(self, tap: Any) -> None:
        self._record("CFMachPortInvalidate", tap)

    def CGEventGetLocation(self, event: Any) -> Any:
        return event.location

    # -- run loop ---------------------------------------------------------- #

    def CFRunLoopGetCurrent(self) -> _FakeRunLoop:
        self.run_loop_thread_names.append(threading.current_thread().name)
        return self.loop

    def CFRunLoopAddSource(self, loop: Any, source: Any, mode: Any) -> None:
        self._record("CFRunLoopAddSource", loop, source, mode)

    def CFRunLoopRemoveSource(self, loop: Any, source: Any, mode: Any) -> None:
        self._record("CFRunLoopRemoveSource", loop, source, mode)

    def CFRunLoopRunInMode(self, mode: Any, seconds: float, return_after_source: bool) -> int:
        self._record("CFRunLoopRunInMode", mode)
        # A real run loop serves the tap from *this* thread. `on_slice` lets a test deliver
        # an event from the loop thread, as macOS would; then the fake sits until stopped
        # or the slice elapses (capped so a broken stop() cannot hang the suite).
        on_slice, self.on_slice = self.on_slice, None
        if on_slice is not None:
            on_slice()
        self.loop.stopped.wait(timeout=min(seconds, 0.2))
        return 0

    def CFRunLoopStop(self, loop: Any) -> None:
        self._record("CFRunLoopStop", loop)
        loop.stopped.set()


def _mouse_event(x: float, y: float) -> Any:
    return SimpleNamespace(location=SimpleNamespace(x=x, y=y))


def _observer_thread_alive() -> bool:
    from yazses.platform.macos.click_observer import THREAD_NAME

    return any(t.name == THREAD_NAME and t.is_alive() for t in threading.enumerate())


@pytest.fixture
def quartz() -> _FakeQuartz:
    return _FakeQuartz()


@pytest.fixture
def started(quartz: _FakeQuartz) -> Any:
    """A started observer over the fake, torn down after the test whatever happened."""
    from yazses.platform.macos.click_observer import MacClickObserver

    received: list[ClickEvent] = []
    observer = MacClickObserver(quartz=quartz)
    observer.start(received.append)
    assert quartz.tap is not None
    yield SimpleNamespace(observer=observer, received=received, quartz=quartz)
    observer.stop()
    assert not _observer_thread_alive()


def _deliver(quartz: _FakeQuartz, event_type: int, event: Any = None) -> Any:
    assert quartz.tap is not None
    return quartz.tap.callback(None, event_type, event, None)


# --------------------------------------------------------------------------- #
# Importability and the Protocol
# --------------------------------------------------------------------------- #


def test_the_module_imports_and_constructs_without_quartz() -> None:
    """A base install on Linux must import this; PyObjC is loaded at start(), not before."""
    from yazses.platform.macos.click_observer import MacClickObserver

    observer = MacClickObserver()
    assert isinstance(observer, ClickObserver)


def test_a_missing_quartz_bridge_is_a_click_observer_error_not_an_import_error() -> None:
    from yazses.platform.macos.click_observer import MacClickObserver

    def _missing() -> Any:
        raise ImportError("no PyObjC here")

    observer = MacClickObserver(load_quartz=_missing)
    with pytest.raises(ClickObserverError, match="pyobjc-framework-Quartz"):
        observer.start(lambda e: None)
    assert not _observer_thread_alive()
    observer.stop()  # nothing started, nothing raised


# --------------------------------------------------------------------------- #
# The tap: listen-only, mouse-down only
# --------------------------------------------------------------------------- #


def test_the_tap_is_created_listen_only_on_the_session_tap(started: Any) -> None:
    """The privacy guarantee: a listen-only tap cannot swallow, delay or alter a click.

    The exact option constant is asserted, not just "some option", because the active
    default would make this process a filter in front of every click on the Mac.
    """
    quartz = started.quartz
    (create,) = quartz.named("CGEventTapCreate")
    location, place, options, _mask, callback, refcon = create
    assert options == _FakeQuartz.kCGEventTapOptionListenOnly
    assert options != _FakeQuartz.kCGEventTapOptionDefault
    assert location == _FakeQuartz.kCGSessionEventTap
    assert place == _FakeQuartz.kCGHeadInsertEventTap
    assert callable(callback)
    assert refcon is None


def test_the_mask_names_exactly_the_three_mouse_down_types(started: Any) -> None:
    """Mouse-up, motion, drag and scroll are not even asked for: the observer wants
    *that a click happened*, and nothing about what the hand did before or after."""
    quartz = started.quartz
    (create,) = quartz.named("CGEventTapCreate")
    mask = create[3]
    expected = (
        quartz.CGEventMaskBit(_FakeQuartz.kCGEventLeftMouseDown)
        | quartz.CGEventMaskBit(_FakeQuartz.kCGEventRightMouseDown)
        | quartz.CGEventMaskBit(_FakeQuartz.kCGEventOtherMouseDown)
    )
    assert mask == expected


def test_the_tap_is_enabled_and_attached_to_a_run_loop_on_a_dedicated_daemon_thread(
    started: Any,
) -> None:
    from yazses.platform.macos.click_observer import THREAD_NAME

    quartz = started.quartz
    assert quartz.named("CGEventTapEnable") == [(quartz.tap, True)]
    assert quartz.named("CFRunLoopAddSource") == [
        (quartz.loop, ("source-for", quartz.tap), _FakeQuartz.kCFRunLoopCommonModes)
    ]
    # The run loop is the observer thread's own, never the caller's.
    assert quartz.run_loop_thread_names == [THREAD_NAME]
    assert threading.current_thread().name != THREAD_NAME
    thread = next(t for t in threading.enumerate() if t.name == THREAD_NAME)
    assert thread.daemon


# --------------------------------------------------------------------------- #
# What is emitted, and what is not
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "event_type",
    [
        _FakeQuartz.kCGEventLeftMouseDown,
        _FakeQuartz.kCGEventRightMouseDown,
        _FakeQuartz.kCGEventOtherMouseDown,
    ],
)
def test_each_mouse_down_becomes_exactly_one_click_event_with_time_and_place(
    started: Any, event_type: int
) -> None:
    """Three buttons, one shape: the event carries no field saying which button it was."""
    before = time.monotonic()
    _deliver(started.quartz, event_type, _mouse_event(640.5, 350.25))
    after = time.monotonic()

    assert len(started.received) == 1
    (event,) = started.received
    assert isinstance(event, ClickEvent)
    assert (event.x, event.y) == (640.5, 350.25)
    assert before <= event.timestamp_s <= after
    assert set(vars(event)) == {"timestamp_s", "x", "y"}


def test_coordinates_pass_through_in_the_canonical_space_without_a_y_flip(
    started: Any,
) -> None:
    """``CGEventGetLocation`` is already the ADR-v2-149 space for macOS: points, origin at
    the main display's top-left, y down, negative on a monitor left of or above it
    (``gaze/topology.py``). A Cocoa-style flip here would mirror every click."""
    _deliver(started.quartz, _FakeQuartz.kCGEventLeftMouseDown, _mouse_event(-1200.0, -80.0))
    (event,) = started.received
    assert (event.x, event.y) == (-1200.0, -80.0)


@pytest.mark.parametrize(
    "event_type",
    [
        _FakeQuartz.kCGEventLeftMouseUp,
        _FakeQuartz.kCGEventRightMouseUp,
        _FakeQuartz.kCGEventOtherMouseUp,
        _FakeQuartz.kCGEventMouseMoved,
        _FakeQuartz.kCGEventLeftMouseDragged,
        _FakeQuartz.kCGEventScrollWheel,
    ],
)
def test_anything_that_is_not_a_mouse_down_emits_nothing(started: Any, event_type: int) -> None:
    """Belt and braces over the mask: a type the mask did not ask for still emits nothing."""
    _deliver(started.quartz, event_type, _mouse_event(10.0, 10.0))
    assert started.received == []


def test_a_disabled_tap_is_re_enabled_and_no_click_is_invented(started: Any) -> None:
    """macOS disables a tap whose callback was slow (``...ByTimeout``) or on user input
    (``...ByUserInput``). Either is a notification, not a click: re-enable, emit nothing."""
    quartz = started.quartz
    enables_before = len(quartz.named("CGEventTapEnable"))

    _deliver(quartz, _FakeQuartz.kCGEventTapDisabledByTimeout, None)
    _deliver(quartz, _FakeQuartz.kCGEventTapDisabledByUserInput, None)

    assert started.received == []
    assert quartz.named("CGEventTapEnable")[enables_before:] == [
        (quartz.tap, True),
        (quartz.tap, True),
    ]
    # And the tap still delivers afterwards.
    _deliver(quartz, _FakeQuartz.kCGEventLeftMouseDown, _mouse_event(1.0, 2.0))
    assert len(started.received) == 1


def test_a_non_finite_location_emits_nothing_rather_than_raising_into_quartz(
    started: Any, caplog: pytest.LogCaptureFixture
) -> None:
    """``ClickEvent`` refuses NaN; the refusal must stay inside the callback."""
    with caplog.at_level(logging.WARNING, logger="yazses.platform.macos.click_observer"):
        _deliver(started.quartz, _FakeQuartz.kCGEventLeftMouseDown, _mouse_event(float("nan"), 1.0))
    assert started.received == []
    assert any("finite" in record.getMessage() for record in caplog.records)


# --------------------------------------------------------------------------- #
# A raising callback
# --------------------------------------------------------------------------- #


def test_a_raising_callback_is_contained_logged_once_and_later_clicks_still_arrive(
    quartz: _FakeQuartz, caplog: pytest.LogCaptureFixture
) -> None:
    from yazses.platform.macos.click_observer import MacClickObserver

    seen: list[ClickEvent] = []

    def flaky(event: ClickEvent) -> None:
        seen.append(event)
        if len(seen) <= 2:
            raise RuntimeError("consumer bug")

    observer = MacClickObserver(quartz=quartz)
    observer.start(flaky)
    try:
        with caplog.at_level(logging.DEBUG, logger="yazses.platform.macos.click_observer"):
            for i in range(4):
                _deliver(quartz, _FakeQuartz.kCGEventLeftMouseDown, _mouse_event(float(i), 0.0))
    finally:
        observer.stop()

    assert [e.x for e in seen] == [0.0, 1.0, 2.0, 3.0]
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(errors) == 1, [r.getMessage() for r in errors]
    assert "consumer bug" in (errors[0].exc_text or "") or errors[0].exc_info is not None


# --------------------------------------------------------------------------- #
# A NULL tap: no permission
# --------------------------------------------------------------------------- #


def test_a_null_tap_raises_naming_both_panes_and_starts_no_thread() -> None:
    """``CGEventTapCreate`` returning NULL is what a missing Input Monitoring or
    Accessibility grant looks like (#182, #562). NULL does not say which, so the message
    names both panes and the command that reports them separately."""
    from yazses.platform.macos.click_observer import MacClickObserver

    quartz = _FakeQuartz(create_tap=False)
    observer = MacClickObserver(quartz=quartz)

    with pytest.raises(ClickObserverError) as excinfo:
        observer.start(lambda e: None)

    message = str(excinfo.value)
    assert "Input Monitoring" in message
    assert "Accessibility" in message
    assert "System Settings -> Privacy & Security -> Input Monitoring" in message
    assert "yazses doctor" in message
    assert not _observer_thread_alive()
    assert quartz.named("CFRunLoopAddSource") == []
    assert quartz.named("CGEventTapEnable") == []
    assert quartz.named("CFMachPortCreateRunLoopSource") == []
    # stop() after a failed start is a no-op and never raises.
    observer.stop()
    assert quartz.named("CFRunLoopStop") == []


def test_a_failed_start_leaves_the_observer_able_to_try_again() -> None:
    """A grant followed by a restart is the remedy; the object must not be poisoned."""
    from yazses.platform.macos.click_observer import MacClickObserver

    quartz = _FakeQuartz(create_tap=False)
    observer = MacClickObserver(quartz=quartz)
    with pytest.raises(ClickObserverError):
        observer.start(lambda e: None)

    quartz.create_tap = True
    received: list[ClickEvent] = []
    observer.start(received.append)
    try:
        _deliver(quartz, _FakeQuartz.kCGEventLeftMouseDown, _mouse_event(5.0, 6.0))
        assert len(received) == 1
    finally:
        observer.stop()


# --------------------------------------------------------------------------- #
# start twice, stop twice
# --------------------------------------------------------------------------- #


def test_starting_twice_creates_one_tap_and_keeps_the_first_callback(started: Any) -> None:
    other: list[ClickEvent] = []
    started.observer.start(other.append)

    assert len(started.quartz.named("CGEventTapCreate")) == 1
    _deliver(started.quartz, _FakeQuartz.kCGEventLeftMouseDown, _mouse_event(1.0, 1.0))
    assert len(started.received) == 1
    assert other == []


def test_stop_disables_the_tap_stops_the_run_loop_once_and_releases_the_port(
    quartz: _FakeQuartz,
) -> None:
    from yazses.platform.macos.click_observer import MacClickObserver

    observer = MacClickObserver(quartz=quartz)
    observer.start(lambda e: None)
    tap = quartz.tap

    observer.stop()
    observer.stop()
    observer.stop()

    assert not _observer_thread_alive()
    assert quartz.named("CFRunLoopStop") == [(quartz.loop,)]
    assert quartz.named("CGEventTapEnable") == [(tap, True), (tap, False)]
    assert quartz.named("CFMachPortInvalidate") == [(tap,)]
    assert quartz.named("CFRunLoopRemoveSource") == [
        (quartz.loop, ("source-for", tap), _FakeQuartz.kCFRunLoopCommonModes)
    ]
    # Teardown happened in order: the loop was told to stop before the port died.
    names = [name for name, _ in quartz.calls]
    assert names.index("CFRunLoopStop") < names.index("CFMachPortInvalidate")


def test_stop_never_raises_even_when_quartz_does(quartz: _FakeQuartz) -> None:
    from yazses.platform.macos.click_observer import MacClickObserver

    observer = MacClickObserver(quartz=quartz)
    observer.start(lambda e: None)

    def _boom(*_args: Any) -> None:
        raise RuntimeError("bridge exploded")

    quartz.CFMachPortInvalidate = _boom  # type: ignore[method-assign]
    observer.stop()  # must not raise
    assert not _observer_thread_alive()


def test_a_click_after_stop_is_dropped(quartz: _FakeQuartz) -> None:
    """A late event from a tap macOS has not yet torn down must not reach a consumer that
    believes it unsubscribed."""
    from yazses.platform.macos.click_observer import MacClickObserver

    received: list[ClickEvent] = []
    observer = MacClickObserver(quartz=quartz)
    observer.start(received.append)
    observer.stop()
    _deliver(quartz, _FakeQuartz.kCGEventLeftMouseDown, _mouse_event(1.0, 1.0))
    assert received == []


def test_stop_can_be_called_from_the_run_loop_thread_without_deadlocking(
    quartz: _FakeQuartz,
) -> None:
    """A consumer may call stop() from inside its own on_click, which runs on the observer
    thread. ``Thread.join`` on the current thread raises ``RuntimeError``; the observer
    must skip the join there, still tear down, and let the thread run out on its own."""
    from yazses.platform.macos.click_observer import THREAD_NAME, MacClickObserver

    observer = MacClickObserver(quartz=quartz)
    stopped_on: list[str] = []
    done = threading.Event()

    def on_click(_event: ClickEvent) -> None:
        stopped_on.append(threading.current_thread().name)
        observer.stop()
        done.set()

    # Delivered from inside the fake run loop, i.e. on the observer's own thread.
    quartz.on_slice = lambda: _deliver(
        quartz, _FakeQuartz.kCGEventLeftMouseDown, _mouse_event(1.0, 1.0)
    )
    observer.start(on_click)
    assert done.wait(timeout=3.0), "the click never reached on_click from the loop thread"
    assert stopped_on == [THREAD_NAME]

    loop_thread = next((t for t in threading.enumerate() if t.name == THREAD_NAME), None)
    if loop_thread is not None:
        loop_thread.join(timeout=3.0)
    assert not _observer_thread_alive()
    assert quartz.named("CFRunLoopStop") == [(quartz.loop,)]
    assert quartz.named("CFMachPortInvalidate") == [(quartz.tap,)]
    observer.stop()  # idempotent after a self-stop too
    assert quartz.named("CFRunLoopStop") == [(quartz.loop,)]


# --------------------------------------------------------------------------- #
# Registration
# --------------------------------------------------------------------------- #


def test_the_macos_platform_bundle_exposes_the_click_observer_factory() -> None:
    """Without this the backend exists and the refiner never constructs it."""
    from yazses.platform.macos import build_platform
    from yazses.platform.macos.click_observer import MacClickObserver

    platform = build_platform()
    assert platform.click_observer_factory is MacClickObserver


def test_the_factory_builds_an_unstarted_observer_and_imports_no_quartz() -> None:
    """``get_platform()`` merely running must not touch Input Monitoring (base.py)."""
    import sys

    from yazses.platform.macos import build_platform

    factory = build_platform().click_observer_factory
    assert factory is not None
    observer = factory()
    assert isinstance(observer, ClickObserver)
    assert "Quartz" not in sys.modules
    assert not _observer_thread_alive()
