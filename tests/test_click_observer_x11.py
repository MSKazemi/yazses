"""The X11 click observer: XInput2 raw button presses, faked at the python-xlib boundary (#607).

Two depths, the way ``tests/test_pointer_x11.py`` does it.

**The observer, over a recorded connection.** ``X11ClickObserver`` never imports Xlib; it
drives an ``X11ClickConnection``, so a scripted stand-in proves the lifecycle — one event
per left/middle/right press, nothing for the wheel, a callback that raises does not kill
the loop, ``stop`` is idempotent and leaves no thread behind, ``start`` twice opens one
connection.

**The one class that touches python-xlib.** ``XInputClickConnection`` gets a fake display
whose ``fileno()`` is a real socket, so the ``select``-then-``pending_events`` wait is the
code that actually runs, with no X server, no ``DISPLAY`` and nothing clicked on a
developer's desktop. Opening is tested the same way: every refusal names itself and raises
``ClickObserverError``, never an Xlib traceback.

**Privacy is asserted structurally**, not by inspection: the event the observer emits is a
``ClickEvent``, and that dataclass has exactly three fields. A backend that learned the
button, the window or the text under the pointer would have nowhere to put it.

**Registration.** The Linux bundle offers the factory on an X11 session and ``None`` plus a
stated reason on Wayland; the refinement builder and ``doctor`` repeat that reason.
"""

from __future__ import annotations

import ast
import dataclasses
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from yazses.gaze.clicks import ClickEvent, ClickObserver, ClickObserverError
from yazses.platform.linux import click_observer_x11
from yazses.platform.linux.click_observer_x11 import (
    CLICK_BUTTONS,
    X11_CLICK_BACKEND_NAME,
    X11ClickObserver,
    XInputClickConnection,
    open_xinput_connection,
)


# --------------------------------------------------------------------------- #
# A scripted connection: buttons arrive in order, the pointer is wherever we say.
# --------------------------------------------------------------------------- #
class _ScriptedConnection:
    """Yields the scripted buttons one per ``next_button`` call, then idles.

    ``delivered`` is set once every scripted button has been handed over, so a test can wait
    for the loop to have *seen* its input instead of sleeping and hoping. ``position`` is
    what ``pointer_position`` answers, in root-window pixels.
    """

    def __init__(self, buttons: list[int], position: tuple[int, int] = (640, 360)) -> None:
        self._buttons = list(buttons)
        self.position = position
        self.closed = 0
        self.position_queries = 0
        self.delivered = threading.Event()
        self.fail_with: Exception | None = None
        if not self._buttons:
            self.delivered.set()

    def next_button(self, timeout_s: float) -> int | None:
        if self.fail_with is not None:
            raise self.fail_with
        if self._buttons:
            button = self._buttons.pop(0)
            if not self._buttons:
                self.delivered.set()
            return button
        time.sleep(min(timeout_s, 0.005))
        return None

    def pointer_position(self) -> tuple[int, int]:
        self.position_queries += 1
        return self.position

    def close(self) -> None:
        self.closed += 1


def _wait(predicate, timeout_s: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return predicate()


def _observer(connection: _ScriptedConnection, **kwargs: Any) -> X11ClickObserver:
    return X11ClickObserver(open_connection=lambda: connection, poll_interval_s=0.01, **kwargs)


def test_the_observer_satisfies_the_protocol_and_names_its_backend() -> None:
    observer = _observer(_ScriptedConnection([]))
    assert isinstance(observer, ClickObserver)
    assert X11_CLICK_BACKEND_NAME == "x11-xinput2"


def test_a_left_press_is_exactly_one_click_at_the_queried_root_position() -> None:
    connection = _ScriptedConnection([1], position=(1234, 567))
    clock_reads = iter([100.5, 101.0, 102.0])
    observer = _observer(connection, clock=lambda: next(clock_reads))
    got: list[ClickEvent] = []
    observer.start(got.append)
    try:
        assert connection.delivered.wait(2.0)
        assert _wait(lambda: len(got) == 1)
    finally:
        observer.stop()
    assert got == [ClickEvent(100.5, 1234.0, 567.0)]
    assert connection.position_queries == 1, "the position is asked once per click, at the click"


@pytest.mark.parametrize("button", sorted(CLICK_BUTTONS))
def test_every_mouse_button_counts_as_a_click(button: int) -> None:
    connection = _ScriptedConnection([button])
    observer = _observer(connection)
    got: list[ClickEvent] = []
    observer.start(got.append)
    try:
        assert connection.delivered.wait(2.0)
        assert _wait(lambda: len(got) == 1)
    finally:
        observer.stop()
    assert len(got) == 1


def test_the_wheel_and_the_thumb_buttons_yield_nothing() -> None:
    """4–7 are the wheel as X11 spells it; 8 and 9 are browser back/forward. None of them is
    an aim point, and a wheel notch over a page is the commonest 'click' a desktop sees."""
    connection = _ScriptedConnection([4, 5, 6, 7, 8, 9])
    observer = _observer(connection)
    got: list[ClickEvent] = []
    observer.start(got.append)
    try:
        assert connection.delivered.wait(2.0)
        time.sleep(0.05)
    finally:
        observer.stop()
    assert got == []
    assert connection.position_queries == 0, "a wheel notch must not even query the pointer"


def test_a_click_carries_exactly_a_time_and_a_place() -> None:
    """The structural privacy rule, pinned here too: whatever XInput2 knows about a press —
    the button, the device, the window under it — the emitted value has no field for it."""
    connection = _ScriptedConnection([3], position=(10, 20))
    observer = _observer(connection, clock=lambda: 7.0)
    got: list[ClickEvent] = []
    observer.start(got.append)
    try:
        assert connection.delivered.wait(2.0)
        assert _wait(lambda: len(got) == 1)
    finally:
        observer.stop()
    (event,) = got
    assert type(event) is ClickEvent
    assert {f.name for f in dataclasses.fields(event)} == {"timestamp_s", "x", "y"}
    assert dataclasses.asdict(event) == {"timestamp_s": 7.0, "x": 10.0, "y": 20.0}


def test_the_timestamp_is_the_injected_monotonic_clock_by_default() -> None:
    """The association subtracts click time from gaze time, so both must be
    ``time.monotonic`` readings — not the X server's millisecond ``time`` field."""
    connection = _ScriptedConnection([1])
    observer = _observer(connection)
    got: list[ClickEvent] = []
    before = time.monotonic()
    observer.start(got.append)
    try:
        assert connection.delivered.wait(2.0)
        assert _wait(lambda: len(got) == 1)
    finally:
        observer.stop()
    after = time.monotonic()
    assert before <= got[0].timestamp_s <= after


def test_a_raising_callback_does_not_kill_the_loop_and_is_logged_once(caplog) -> None:
    connection = _ScriptedConnection([1, 1, 1])
    observer = _observer(connection)
    seen: list[int] = []

    def explode(event: ClickEvent) -> None:
        seen.append(1)
        raise RuntimeError("consumer bug")

    import logging

    with caplog.at_level(logging.DEBUG, logger=click_observer_x11.__name__):
        observer.start(explode)
        try:
            assert connection.delivered.wait(2.0)
            assert _wait(lambda: len(seen) == 3)
            assert observer.is_running
        finally:
            observer.stop()
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warnings) == 1, "one warning for a broken consumer, then silence — not a line per click"


def test_start_twice_opens_one_connection_and_stop_is_idempotent() -> None:
    connection = _ScriptedConnection([])
    opened = 0

    def open_connection():
        nonlocal opened
        opened += 1
        return connection

    observer = X11ClickObserver(open_connection=open_connection, poll_interval_s=0.01)
    observer.start(lambda e: None)
    observer.start(lambda e: None)
    assert opened == 1
    assert observer.is_running
    observer.stop()
    observer.stop()
    assert not observer.is_running
    assert connection.closed == 1, "the display is released exactly once"


def test_stop_unblocks_the_loop_and_leaves_no_thread_behind() -> None:
    connection = _ScriptedConnection([])
    observer = _observer(connection)
    before = {t.name for t in threading.enumerate()}
    observer.start(lambda e: None)
    assert _wait(lambda: any("click-observer" in t.name for t in threading.enumerate()))
    observer.stop()
    assert _wait(lambda: {t.name for t in threading.enumerate()} == before)


def test_stop_without_start_and_after_a_failed_start_never_raises() -> None:
    observer = X11ClickObserver(open_connection=lambda: (_ for _ in ()).throw(
        ClickObserverError("no display")
    ))
    observer.stop()
    with pytest.raises(ClickObserverError, match="no display"):
        observer.start(lambda e: None)
    observer.stop()
    assert not observer.is_running


def test_a_connection_that_dies_mid_loop_ends_the_loop_with_one_warning(caplog) -> None:
    """A display that goes away is reported once and the observer winds down; dictation
    is not this thread's concern and must not be touched by its failure."""
    import logging

    connection = _ScriptedConnection([])
    observer = _observer(connection)
    with caplog.at_level(logging.WARNING, logger=click_observer_x11.__name__):
        observer.start(lambda e: None)
        connection.fail_with = ConnectionResetError("X connection broken")
        assert _wait(lambda: not observer.is_running)
    observer.stop()
    assert connection.closed == 1
    assert sum("X11 click observer" in r.getMessage() for r in caplog.records) == 1


def test_a_failed_start_releases_nothing_it_did_not_open() -> None:
    """``start`` raises before a thread exists, so there is nothing to stop and no
    connection to leak — the daemon turns the message into the dormant reason."""
    before = set(threading.enumerate())
    observer = X11ClickObserver(open_connection=lambda: (_ for _ in ()).throw(
        ClickObserverError("the X11 server on ':9' has no XInputExtension")
    ))
    with pytest.raises(ClickObserverError, match="XInputExtension"):
        observer.start(lambda e: None)
    assert set(threading.enumerate()) == before
    assert not observer.is_running


# --------------------------------------------------------------------------- #
# The one class that touches python-xlib, with a fake display and a real pipe.
# --------------------------------------------------------------------------- #
class _FakeX:
    GenericEvent = 35


class _FakeXInput:
    """The handful of ``Xlib.ext.xinput`` names the backend uses."""

    RawButtonPress = 15
    RawButtonPressMask = 1 << 15
    AllDevices = 0

    class _Reply:
        major_version = 2
        minor_version = 0

    @staticmethod
    def DEVICEID(name: str) -> Any:  # noqa: N802 - python-xlib's spelling
        return ("Card16", name)


class _FakeEvent:
    def __init__(self, *, type: int, extension: int, evtype: int, data: Any) -> None:
        self.type = type
        self.extension = extension
        self.evtype = evtype
        self.data = data


class _RawData:
    def __init__(self, detail: int) -> None:
        self.detail = detail


class _FakeRoot:
    def __init__(self, position: tuple[int, int] = (300, 200)) -> None:
        self.selected: list[Any] = []
        self.position = position
        self.queries = 0

    def xinput_select_events(self, masks: Any) -> None:
        self.selected.append(masks)

    def query_pointer(self) -> Any:
        self.queries += 1

        class _Reply:
            root_x, root_y = self.position

        return _Reply()


class _FakeDisplay:
    """A display whose event queue is fed by the test and whose ``fileno`` is a real socket,
    so the backend's ``select`` wait runs for real.

    A socket pair, not a pipe: Windows' ``select`` accepts only sockets (WinError 10038 on a
    pipe), and this test runs on every OS even though the backend only ever runs on Linux —
    as an X display connection's fd is a socket there too."""

    XI_OPCODE = 131

    def __init__(self, *, xinput: bool = True, version: tuple[int, int] = (2, 0)) -> None:
        self._reader, self._writer = socket.socketpair()
        self._reader.setblocking(False)  # python-xlib's pending_events never blocks
        self.queue: list[Any] = []
        self.root = _FakeRoot()
        self.closed = 0
        self.synced = 0
        self.registered: list[tuple[int, int]] = []
        self._xinput = xinput
        self._version = version

    # -- feeding events ---------------------------------------------------- #

    def push(self, event: Any) -> None:
        self.queue.append(event)
        self._writer.send(b"x")

    def push_raw_press(self, detail: int, *, extension: int | None = None) -> None:
        self.push(_FakeEvent(
            type=_FakeX.GenericEvent,
            extension=self.XI_OPCODE if extension is None else extension,
            evtype=_FakeXInput.RawButtonPress,
            data=_RawData(detail),
        ))

    # -- the python-xlib surface ------------------------------------------- #

    def fileno(self) -> int:
        return self._reader.fileno()

    def pending_events(self) -> int:
        try:
            self._reader.recv(64)
        except BlockingIOError:
            pass
        return len(self.queue)

    def next_event(self) -> Any:
        return self.queue.pop(0)

    def has_extension(self, name: str) -> bool:
        return self._xinput and name == "XInputExtension"

    def get_extension_major(self, name: str) -> int:
        return self.XI_OPCODE

    def xinput_query_version(self) -> Any:
        major, minor = self._version

        class _Reply:
            major_version, minor_version = major, minor

        return _Reply()

    def ge_add_event_data(self, extension: int, evtype: int, estruct: Any) -> None:
        self.registered.append((extension, evtype))

    def screen(self) -> Any:
        root = self.root

        class _Screen:
            pass

        screen = _Screen()
        screen.root = root  # type: ignore[attr-defined]
        return screen

    def sync(self) -> None:
        self.synced += 1

    def close(self) -> None:
        self.closed += 1
        for sock in (self._reader, self._writer):
            sock.close()


def _connection(display: _FakeDisplay) -> XInputClickConnection:
    return XInputClickConnection(
        display=display, root=display.root, x=_FakeX, xinput=_FakeXInput, opcode=display.XI_OPCODE
    )


def test_a_raw_press_comes_back_as_its_button_number() -> None:
    display = _FakeDisplay()
    connection = _connection(display)
    display.push_raw_press(2)
    assert connection.next_button(timeout_s=1.0) == 2


def test_an_idle_display_returns_none_within_the_timeout_not_never() -> None:
    display = _FakeDisplay()
    connection = _connection(display)
    started = time.monotonic()
    assert connection.next_button(timeout_s=0.05) is None
    assert time.monotonic() - started < 1.0


def test_events_that_are_not_raw_xi2_button_presses_are_skipped() -> None:
    display = _FakeDisplay()
    connection = _connection(display)
    display.push(_FakeEvent(type=4, extension=0, evtype=0, data=None))               # core ButtonPress
    display.push(_FakeEvent(type=35, extension=99, evtype=15, data=_RawData(1)))     # another extension
    display.push(_FakeEvent(type=35, extension=display.XI_OPCODE, evtype=17, data=_RawData(1)))  # RawMotion
    assert connection.next_button(timeout_s=0.05) is None
    assert connection.next_button(timeout_s=0.05) is None
    assert connection.next_button(timeout_s=0.05) is None


def test_an_unparsed_raw_event_is_decoded_from_its_wire_bytes() -> None:
    """When python-xlib hands the generic event's payload back as bytes (no struct was
    registered), ``detail`` is the Card32 at offset 6 of XIRawEvent."""
    import struct

    display = _FakeDisplay()
    connection = _connection(display)
    wire = struct.pack("=HIIHHI", 7, 123456, 3, 9, 0, 0) + b"\0" * 4
    display.push(_FakeEvent(type=35, extension=display.XI_OPCODE, evtype=15, data=wire))
    assert connection.next_button(timeout_s=1.0) == 3


def test_the_pointer_position_is_the_root_window_query() -> None:
    display = _FakeDisplay()
    display.root.position = (-1280, 42)
    connection = _connection(display)
    assert connection.pointer_position() == (-1280, 42)
    assert display.root.queries == 1


def test_close_closes_the_display_once() -> None:
    display = _FakeDisplay()
    connection = _connection(display)
    connection.close()
    assert display.closed == 1


# --------------------------------------------------------------------------- #
# Opening a real connection: every refusal names itself.
# --------------------------------------------------------------------------- #
class _DisplayModule:
    def __init__(self, result: Any) -> None:
        self._result = result

    def Display(self) -> Any:  # noqa: N802 - python-xlib's spelling
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


class _FakeRq:
    """Enough of ``Xlib.protocol.rq`` to build the raw-event struct."""

    @staticmethod
    def Struct(*fields: Any) -> Any:  # noqa: N802
        return ("Struct", fields)

    @staticmethod
    def Card32(name: str) -> Any:  # noqa: N802
        return ("Card32", name)

    @staticmethod
    def Card16(name: str) -> Any:  # noqa: N802
        return ("Card16", name)

    @staticmethod
    def Pad(n: int) -> Any:  # noqa: N802
        return ("Pad", n)


def _patch_xlib(monkeypatch: pytest.MonkeyPatch, xdisplay: Any) -> None:
    monkeypatch.setattr(
        click_observer_x11, "_load_xlib", lambda: (_FakeX, xdisplay, _FakeXInput, _FakeRq)
    )


def test_no_display_is_refused_with_the_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_xlib(monkeypatch, _DisplayModule(_FakeDisplay()))
    monkeypatch.delenv("DISPLAY", raising=False)
    with pytest.raises(ClickObserverError, match="DISPLAY"):
        open_xinput_connection()


def test_a_display_that_refuses_the_connection_names_it(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_xlib(monkeypatch, _DisplayModule(ConnectionError("no protocol specified")))
    monkeypatch.setenv("DISPLAY", ":0")
    with pytest.raises(ClickObserverError, match="':0'"):
        open_xinput_connection()


def test_a_server_without_xinput_is_refused_and_released(monkeypatch: pytest.MonkeyPatch) -> None:
    display = _FakeDisplay(xinput=False)
    _patch_xlib(monkeypatch, _DisplayModule(display))
    monkeypatch.setenv("DISPLAY", ":0")
    with pytest.raises(ClickObserverError, match="XInputExtension"):
        open_xinput_connection()
    assert display.closed == 1


def test_an_xinput_older_than_2_is_refused_and_released(monkeypatch: pytest.MonkeyPatch) -> None:
    display = _FakeDisplay(version=(1, 5))
    _patch_xlib(monkeypatch, _DisplayModule(display))
    monkeypatch.setenv("DISPLAY", ":0")
    with pytest.raises(ClickObserverError, match="XInput 2"):
        open_xinput_connection()
    assert display.closed == 1


def test_missing_python_xlib_is_a_click_observer_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "Xlib", None)
    with pytest.raises(ClickObserverError, match="python-xlib"):
        click_observer_x11._load_xlib()


def test_opening_selects_raw_presses_for_all_devices_on_the_root_and_grabs_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """XI_RawButtonPress on the root window for AllDevices: the only selection that sees a
    press in any window without a grab, and one that carries no window at all."""
    display = _FakeDisplay()
    _patch_xlib(monkeypatch, _DisplayModule(display))
    monkeypatch.setenv("DISPLAY", ":0")
    connection = open_xinput_connection()
    assert display.root.selected == [[(_FakeXInput.AllDevices, _FakeXInput.RawButtonPressMask)]]
    assert (display.XI_OPCODE, _FakeXInput.RawButtonPress) in display.registered
    assert display.synced >= 1, "the selection must reach the server before the loop waits"
    assert not any("grab" in n.lower() for n in dir(display.root) if not n.startswith("_"))
    display.push_raw_press(1)
    assert connection.next_button(timeout_s=1.0) == 1
    connection.close()


def test_the_default_observer_opens_through_open_xinput_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    display = _FakeDisplay()
    _patch_xlib(monkeypatch, _DisplayModule(display))
    monkeypatch.setenv("DISPLAY", ":0")
    observer = X11ClickObserver(poll_interval_s=0.01)
    got: list[ClickEvent] = []
    observer.start(got.append)
    try:
        display.push_raw_press(1)
        assert _wait(lambda: len(got) == 1)
    finally:
        observer.stop()
    assert (got[0].x, got[0].y) == (300.0, 200.0)
    assert display.closed == 1


# --------------------------------------------------------------------------- #
# Registration: the Linux bundle, the refinement builder and doctor say the same thing.
# --------------------------------------------------------------------------- #
def _linux_env(monkeypatch: pytest.MonkeyPatch, **env: str) -> None:
    for name in ("XDG_SESSION_TYPE", "WAYLAND_DISPLAY", "DISPLAY", "XDG_CURRENT_DESKTOP"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)


@pytest.mark.skipif(sys.platform != "linux", reason="Linux-specific bundle")
def test_the_linux_bundle_offers_the_x11_observer_on_an_x11_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from yazses.platform.linux import build_platform

    _linux_env(monkeypatch, XDG_SESSION_TYPE="x11", DISPLAY=":0")
    platform = build_platform()
    assert platform.click_observer_factory is not None
    assert platform.click_observer_unavailable_reason is None
    observer = platform.click_observer_factory()
    assert isinstance(observer, X11ClickObserver)
    assert not observer.is_running, "building the platform must open no display connection"


@pytest.mark.skipif(sys.platform != "linux", reason="Linux-specific bundle")
@pytest.mark.parametrize(
    "env",
    [
        {"XDG_SESSION_TYPE": "wayland", "WAYLAND_DISPLAY": "wayland-0", "DISPLAY": ":0"},
        {"WAYLAND_DISPLAY": "wayland-0", "DISPLAY": ":1"},   # no session variable: still Wayland
    ],
)
def test_the_linux_bundle_offers_none_and_a_reason_on_wayland(
    monkeypatch: pytest.MonkeyPatch, env: dict[str, str]
) -> None:
    """XWayland sets ``DISPLAY`` too, and an XI2 observer on it would see only X clients'
    clicks — a plausible, wrong sample stream. Wayland is None, with the reason spelled out."""
    from yazses.platform.linux import WAYLAND_CLICK_REASON, build_platform

    _linux_env(monkeypatch, **env)
    platform = build_platform()
    assert platform.click_observer_factory is None
    assert platform.click_observer_unavailable_reason == WAYLAND_CLICK_REASON
    assert "Wayland" in WAYLAND_CLICK_REASON and "portal" in WAYLAND_CLICK_REASON


@pytest.mark.skipif(sys.platform != "linux", reason="Linux-specific bundle")
def test_the_linux_bundle_offers_none_and_a_reason_headless(monkeypatch: pytest.MonkeyPatch) -> None:
    from yazses.platform.linux import build_platform

    _linux_env(monkeypatch)
    platform = build_platform()
    assert platform.click_observer_factory is None
    assert platform.click_observer_unavailable_reason
    assert "no desktop session" in platform.click_observer_unavailable_reason


def test_the_platform_carries_an_optional_unavailable_reason_defaulting_to_none() -> None:
    from yazses.platform.base import Platform

    by_name = {f.name: f for f in dataclasses.fields(Platform)}
    assert by_name["click_observer_unavailable_reason"].default is None


def test_the_refinement_builder_repeats_the_platform_reason() -> None:
    from yazses.config import Config
    from yazses.gaze.refine_runtime import build_refinement_runtime

    cfg = Config()
    cfg.gaze_refine.enabled = True
    runtime, reason = build_refinement_runtime(
        cfg.gaze_refine,
        targeter=object(),
        perception=object(),
        gaze_on_shared_source=True,
        observer_factory=None,
        observer_unavailable_reason="a native Wayland session exposes no global click stream",
        data_dir=Path("/nonexistent"),
        calibration_verified=True,
    )
    assert runtime is None
    assert "no click observer" in reason and "Wayland" in reason


def test_the_refinement_builder_keeps_its_generic_reason_without_one() -> None:
    from yazses.config import Config
    from yazses.gaze.refine_runtime import build_refinement_runtime

    cfg = Config()
    cfg.gaze_refine.enabled = True
    _runtime, reason = build_refinement_runtime(
        cfg.gaze_refine,
        targeter=object(),
        perception=object(),
        gaze_on_shared_source=True,
        observer_factory=None,
        data_dir=Path("/nonexistent"),
        calibration_verified=True,
    )
    assert "no click observer" in reason


class _DoctorPlatform:
    def __init__(self, factory: Any, reason: str | None) -> None:
        self.click_observer_factory = factory
        self.click_observer_unavailable_reason = reason


def test_doctor_says_nothing_about_the_click_observer_on_a_default_install() -> None:
    from yazses.config import Config
    from yazses.system.doctor import _click_observer_check

    assert _click_observer_check(Config(), _DoctorPlatform(None, "whatever")) is None


def test_doctor_names_the_reason_when_refinement_is_on_but_no_clicks_can_be_seen() -> None:
    from yazses.config import Config
    from yazses.system.doctor import _click_observer_check

    cfg = Config()
    cfg.gaze_refine.enabled = True
    row = _click_observer_check(cfg, _DoctorPlatform(None, "a native Wayland session exposes no global click stream"))
    assert row is not None
    name, status, detail = row
    assert status == "WARN"
    assert "Wayland" in detail and "dormant" in detail


def test_doctor_reports_a_registered_observer_as_ok() -> None:
    from yazses.config import Config
    from yazses.system.doctor import _click_observer_check

    cfg = Config()
    cfg.gaze_refine.enabled = True
    row = _click_observer_check(cfg, _DoctorPlatform(lambda: None, None))
    assert row is not None and row[1] == "OK"


# --------------------------------------------------------------------------- #
# The import stays lazy, because three other platforms import this file's siblings.
# --------------------------------------------------------------------------- #
def test_python_xlib_is_imported_only_inside_a_function() -> None:
    source = Path(click_observer_x11.__file__)
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    nested: set[ast.AST] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            nested.update(ast.walk(node))
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        if any(name.split(".")[0] == "Xlib" for name in names):
            assert node in nested, "python-xlib is imported at module scope"
