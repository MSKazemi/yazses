"""The X11 pointer backend: the shared contract, then what only X11 can get wrong.

Two halves, and the split is the point.

**The shared contract, unmodified.** ``TestX11PointerSink`` subclasses
``tests/pointer_contract.py`` and supplies its four hooks, so the X11 backend answers
exactly the same twenty-odd assertions the fake and the future macOS, Windows and portal
backends answer. Nothing here weakens or re-states them; a behaviour that differs between
backends is the bug that suite exists to find.

**The X11 dialect, which the shared suite cannot see.** That a left click is button 1, that
a downward scroll is a press-release pair on button 5 while an upward one is button 4, that
a fractional delta is rounded rather than truncated, and that XTEST requests do nothing
until the connection is flushed — those are facts about X11, so they are asserted here.

Everything is hermetic, and deliberately so at two different depths. ``X11PointerSink``
gets a recording stand-in for the display, so the contract runs with no X server, no
``DISPLAY`` and no pointer skidding across a developer's screen. ``XTestPointerConnection``
— the one class that does touch python-xlib — gets a fake display object and a fake
``Xlib.X`` constants module, so even the shape of the ``xtest_fake_input`` call is checked
without a server. The recorder translates X11 calls back into ``PointerAction`` values,
which is the backend's job under the contract's design: only the backend knows that
``xtest_fake_input(ButtonPress, detail=1)`` is a left-button press.

The translator drops anything that was never flushed, on purpose. An unflushed XTEST
request has not reached the server, so counting it as an action performed would let a sink
that forgot to sync pass every assertion in the shared suite while moving no pointer at
all — the exact shape of silent failure this project has shipped before.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import Any

import pytest

from tests.pointer_contract import PointerSinkContract
from tests.pointer_fake import PointerAction
from yazses.platform.linux import pointer_x11
from yazses.platform.linux.pointer_x11 import (
    BUTTON_CODES,
    SCROLL_DOWN_BUTTON,
    SCROLL_LEFT_BUTTON,
    SCROLL_RIGHT_BUTTON,
    SCROLL_UP_BUTTON,
    X11_BACKEND_NAME,
    X11PointerSink,
    XTestPointerConnection,
    build_x11_pointer_sink,
    device_units,
    notches,
    open_xtest_connection,
)
from yazses.pointer.base import (
    PointerBackendError,
    PointerButton,
    PointerSink,
    PointerUnsupportedError,
)

#: One wheel notch, per X11 button, in the boundary's own signs: +dy is down, +dx right.
_SCROLL_DELTAS: dict[int, tuple[float, float]] = {
    SCROLL_UP_BUTTON: (0.0, -1.0),
    SCROLL_DOWN_BUTTON: (0.0, 1.0),
    SCROLL_LEFT_BUTTON: (-1.0, 0.0),
    SCROLL_RIGHT_BUTTON: (1.0, 0.0),
}

_BUTTON_BY_CODE: dict[int, PointerButton] = {code: b for b, code in BUTTON_CODES.items()}


class _RecordingConnection:
    """A stand-in display that records XTEST calls instead of performing them.

    ``fail_with`` models a display that has gone away: by default every later call raises,
    the way a closed X connection does, and ``on=`` narrows it to particular calls so a
    failure *between* the events of one operation can be arranged.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self._failure: Exception | None = None
        self._failing: frozenset[str] | None = None

    # -- failure injection ------------------------------------------------- #

    def fail_with(self, error: Exception, on: frozenset[str] | None = None) -> None:
        self._failure = error
        self._failing = on

    def clear_failure(self) -> None:
        self._failure = None
        self._failing = None

    # -- the connection seam ----------------------------------------------- #

    def motion_relative(self, dx: float, dy: float) -> None:
        self._record("motion_relative", dx, dy)

    def motion_absolute(self, x: float, y: float) -> None:
        self._record("motion_absolute", x, y)

    def button(self, code: int, press: bool) -> None:
        self._record("button", code, press)

    def sync(self) -> None:
        self._record("sync")

    def close(self) -> None:
        self._record("close")

    # -- internals --------------------------------------------------------- #

    def _record(self, name: str, *args: Any) -> None:
        if self._failure is not None and (self._failing is None or name in self._failing):
            raise self._failure
        self.calls.append((name, *args))


def _translate(calls: list[tuple[Any, ...]]) -> list[PointerAction]:
    """Turn recorded X11 calls into the contract's ``PointerAction`` vocabulary.

    Flush boundaries delimit operations, because that is what they are on a real
    connection: one public method call, one ``sync``. A trailing group with no ``sync``
    after it never reached the server and is therefore not an action at all.
    """
    actions: list[PointerAction] = []
    group: list[tuple[Any, ...]] = []
    for call in calls:
        if call[0] == "sync":
            actions.extend(_translate_group(group))
            group = []
        elif call[0] == "close":
            actions.extend(_translate_group(group))
            group = []
            actions.append(PointerAction.close())
        else:
            group.append(call)
    return actions


def _translate_group(group: list[tuple[Any, ...]]) -> list[PointerAction]:
    """One flushed operation's calls, as actions. Wheel notches collapse into one scroll."""
    actions: list[PointerAction] = []
    wheel_dx = wheel_dy = 0.0
    scrolled = False
    for call in group:
        if call[0] == "motion_relative":
            actions.append(PointerAction.move_relative(call[1], call[2]))
        elif call[0] == "motion_absolute":
            actions.append(PointerAction.move_absolute(call[1], call[2]))
        elif call[0] == "button":
            code, press = call[1], call[2]
            if code in _SCROLL_DELTAS:
                if press:  # one notch is a press *and* a release; count it once
                    step_x, step_y = _SCROLL_DELTAS[code]
                    wheel_dx += step_x
                    wheel_dy += step_y
                    scrolled = True
                continue
            button = _BUTTON_BY_CODE[code]
            actions.append(
                PointerAction.press(button) if press else PointerAction.release(button)
            )
    if scrolled:
        actions.append(PointerAction.scroll(wheel_dx, wheel_dy))
    return actions


# --------------------------------------------------------------------------- #
# The shared contract, against the X11 backend.
# --------------------------------------------------------------------------- #
class TestX11PointerSink(PointerSinkContract):
    """Every assertion the fake answers, answered by the real X11 sink."""

    def setup_method(self) -> None:
        # Keyed by identity and holding the sink too, so the key cannot be reused by a
        # later object while the test still needs it.
        self._wired: dict[int, tuple[X11PointerSink, _RecordingConnection]] = {}

    def make_sink(self) -> X11PointerSink:
        connection = _RecordingConnection()
        sink = X11PointerSink(connection)
        self._wired[id(sink)] = (sink, connection)
        return sink

    def recorded(self, sink: PointerSink) -> list[PointerAction]:
        return _translate(self._connection(sink).calls)

    def induce_failure(self, sink: PointerSink) -> None:
        self._connection(sink).fail_with(OSError("X connection to :0 broken"))

    def clear_failure(self, sink: PointerSink) -> None:
        self._connection(sink).clear_failure()

    def _connection(self, sink: PointerSink) -> _RecordingConnection:
        return self._wired[id(sink)][1]


# --------------------------------------------------------------------------- #
# The X11 dialect: what the shared suite cannot see.
# --------------------------------------------------------------------------- #
def _sink() -> tuple[X11PointerSink, _RecordingConnection]:
    connection = _RecordingConnection()
    return X11PointerSink(connection), connection


def test_capabilities_name_x11_and_promise_every_operation() -> None:
    caps = _sink()[0].capabilities()
    assert caps.backend == X11_BACKEND_NAME == "x11"
    assert caps.relative_motion and caps.absolute_motion
    assert caps.buttons == frozenset(PointerButton)
    assert caps.scroll_vertical and caps.scroll_horizontal


@pytest.mark.parametrize(
    ("button", "code"),
    [(PointerButton.LEFT, 1), (PointerButton.MIDDLE, 2), (PointerButton.RIGHT, 3)],
)
def test_clicks_use_the_x11_core_button_numbers(button: PointerButton, code: int) -> None:
    """1/2/3 is the core protocol, not a preference. A shuffled map right-clicks on left."""
    sink, connection = _sink()
    sink.click(button)
    assert connection.calls == [("button", code, True), ("button", code, False), ("sync",)]


@pytest.mark.parametrize(
    ("dx", "dy", "code", "count"),
    [
        (0.0, 1.0, SCROLL_DOWN_BUTTON, 1),
        (0.0, -1.0, SCROLL_UP_BUTTON, 1),
        (0.0, 3.0, SCROLL_DOWN_BUTTON, 3),
        (1.0, 0.0, SCROLL_RIGHT_BUTTON, 1),
        (-2.0, 0.0, SCROLL_LEFT_BUTTON, 2),
    ],
)
def test_the_wheel_is_buttons_four_to_seven_one_pair_per_notch(
    dx: float, dy: float, code: int, count: int
) -> None:
    """+dy is down (5) and +dx is right (7); X11's own axis runs the other way for 4/6.

    The sign is fixed by ADR-v2-146 and must not flip at this boundary, so the negation
    X11 needs happens here, in the button chosen — which is what this asserts.
    """
    sink, connection = _sink()
    sink.scroll(dx, dy)
    expected = [("button", code, press) for _ in range(count) for press in (True, False)]
    assert connection.calls == [*expected, ("sync",)]


def test_a_sub_notch_scroll_emits_no_wheel_event() -> None:
    """Documented quantisation, asserted so it cannot drift into an accumulating sink.

    X11 has no fraction-of-a-notch wheel event. Half a notch rounds up to one; less than
    half moves nothing, and carrying the remainder is the caller's job (see the module
    docstring).
    """
    sink, connection = _sink()
    sink.scroll(0.0, 0.4)
    assert connection.calls == [("sync",)], "a sub-notch scroll invented a wheel event"
    sink.scroll(0.0, 0.5)
    assert connection.calls[1:] == [
        ("button", SCROLL_DOWN_BUTTON, True),
        ("button", SCROLL_DOWN_BUTTON, False),
        ("sync",),
    ]


def test_a_two_axis_scroll_emits_both_axes_in_one_operation() -> None:
    sink, connection = _sink()
    sink.scroll(1.0, 2.0)
    assert connection.calls == [
        ("button", SCROLL_DOWN_BUTTON, True),
        ("button", SCROLL_DOWN_BUTTON, False),
        ("button", SCROLL_DOWN_BUTTON, True),
        ("button", SCROLL_DOWN_BUTTON, False),
        ("button", SCROLL_RIGHT_BUTTON, True),
        ("button", SCROLL_RIGHT_BUTTON, False),
        ("sync",),
    ]


def test_motion_reaches_the_connection_with_the_requested_deltas() -> None:
    """Rounding belongs at the Xlib call, not here: the sink passes the ask through."""
    sink, connection = _sink()
    sink.move_relative(-1.5, 0.25)
    sink.move_absolute(120.0, 48.5)
    assert connection.calls == [
        ("motion_relative", -1.5, 0.25),
        ("sync",),
        ("motion_absolute", 120.0, 48.5),
        ("sync",),
    ]


@pytest.mark.parametrize(
    "operate",
    [
        lambda s: s.move_relative(1.0, 1.0),
        lambda s: s.move_absolute(10.0, 10.0),
        lambda s: s.click(),
        lambda s: s.scroll(0.0, 1.0),
    ],
    ids=["move_relative", "move_absolute", "click", "scroll"],
)
def test_every_operation_is_flushed(operate: Any) -> None:
    """Until the connection is synced the X server has seen nothing.

    python-xlib buffers requests. A backend that emitted perfect XTEST calls and never
    flushed would satisfy every "did you call it" assertion and move no pointer — so the
    flush is asserted per operation, not once.
    """
    sink, connection = _sink()
    operate(sink)
    assert connection.calls[-1] == ("sync",), f"not flushed: {connection.calls}"
    assert connection.calls.count(("sync",)) == 1, "one operation, one flush"


def test_a_fresh_sink_touches_the_display_not_at_all() -> None:
    _, connection = _sink()
    assert connection.calls == []


def test_a_platform_failure_becomes_a_backend_error_that_keeps_the_cause() -> None:
    sink, connection = _sink()
    boom = OSError("X connection to :0 broken (explicit kill or server shutdown)")
    connection.fail_with(boom)
    with pytest.raises(PointerBackendError) as excinfo:
        sink.move_relative(1.0, 1.0)
    assert excinfo.value.__cause__ is boom
    assert "X connection" in str(excinfo.value)


def test_a_failed_request_is_flushed_so_it_cannot_ride_on_the_next_one() -> None:
    """ADR-v2-146 rule 4, in its X11 form.

    A click whose *release* fails has already put the press in python-xlib's buffer. Left
    there, it would be flushed by whatever the user asked for next — a stale button press
    arriving attached to a later action. So the failure path flushes too.
    """
    sink, connection = _sink()
    connection.fail_with(OSError("release refused"), on=frozenset({"button"}))
    with pytest.raises(PointerBackendError, match="left click"):
        sink.click()
    connection.clear_failure()
    assert connection.calls == [("sync",)], "the failed request was not flushed"

    sink.move_relative(2.0, 2.0)
    assert _translate(connection.calls) == [PointerAction.move_relative(2.0, 2.0)], (
        "recovery replayed something, or dragged a stale event along"
    )


def test_a_failed_flush_is_reported_not_swallowed() -> None:
    """The events were emitted and the server never heard them. That is a failure."""
    sink, connection = _sink()
    connection.fail_with(OSError("broken pipe"), on=frozenset({"sync"}))
    with pytest.raises(PointerBackendError, match="not delivered"):
        sink.move_relative(1.0, 1.0)


def test_close_closes_the_display_exactly_once() -> None:
    sink, connection = _sink()
    sink.close()
    sink.close()
    assert connection.calls == [("close",)]


def test_close_does_not_raise_over_a_connection_that_is_already_gone() -> None:
    """Cleanup usually runs *because* the display went away; a second error buries the first."""
    sink, connection = _sink()
    connection.fail_with(OSError("connection already closed"))
    sink.close()
    with pytest.raises(PointerBackendError, match="closed"):
        sink.move_relative(1.0, 1.0)


# --------------------------------------------------------------------------- #
# Rounding helpers.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("value", "expected"),
    [(0.0, 0), (0.4, 0), (0.5, 1), (1.0, 1), (1.5, 2), (2.5, 3), (-0.5, 1), (-3.2, 3)],
)
def test_notches_rounds_half_away_from_zero_and_ignores_sign(
    value: float, expected: int
) -> None:
    assert notches(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0.0, 0), (0.4, 0), (0.5, 1), (1.5, 2), (2.5, 3), (-0.5, -1), (-1.6, -2), (-2.5, -3)],
)
def test_device_units_are_symmetric_about_zero(value: float, expected: int) -> None:
    """``round()`` would send 0.5 to 0 and 1.5 to 2 — the smallest ask silently lost."""
    assert device_units(value) == expected


# --------------------------------------------------------------------------- #
# The one class that touches python-xlib, with a fake display and fake constants.
# --------------------------------------------------------------------------- #
class _FakeX:
    """Stand-in for ``Xlib.X``, with the three event types this backend uses."""

    MotionNotify = 6
    ButtonPress = 4
    ButtonRelease = 5


class _FakeDisplay:
    """Stand-in for an open ``Xlib.display.Display`` with the XTEST extension."""

    def __init__(self, *, xtest: bool = True) -> None:
        self.requests: list[tuple[Any, ...]] = []
        self.synced = 0
        self.closed = 0
        self._xtest = xtest

    def has_extension(self, name: str) -> bool:
        return self._xtest and name == "XTEST"

    def xtest_fake_input(self, event_type: int, detail: int = 0, x: int = 0, y: int = 0) -> None:
        self.requests.append((event_type, detail, x, y))

    def sync(self) -> None:
        self.synced += 1

    def close(self) -> None:
        self.closed += 1


def _connection() -> tuple[XTestPointerConnection, _FakeDisplay]:
    display = _FakeDisplay()
    return XTestPointerConnection(display=display, x=_FakeX), display


def test_relative_motion_sets_the_xtest_relative_flag() -> None:
    """detail != 0 is what makes x/y a distance instead of a position. Without it the
    pointer jumps to the top-left corner on every small head movement."""
    connection, display = _connection()
    connection.motion_relative(3.0, -4.0)
    assert display.requests == [(_FakeX.MotionNotify, 1, 3, -4)]


def test_absolute_motion_is_a_position_not_a_delta() -> None:
    connection, display = _connection()
    connection.motion_absolute(120.0, 48.0)
    assert display.requests == [(_FakeX.MotionNotify, 0, 120, 48)]


def test_fractional_coordinates_are_rounded_at_the_xlib_call() -> None:
    connection, display = _connection()
    connection.motion_relative(1.6, -0.4)
    connection.motion_absolute(10.5, 20.49)
    assert display.requests == [
        (_FakeX.MotionNotify, 1, 2, 0),
        (_FakeX.MotionNotify, 0, 11, 20),
    ]


def test_buttons_use_the_xtest_press_and_release_event_types() -> None:
    connection, display = _connection()
    connection.button(1, True)
    connection.button(1, False)
    assert display.requests == [
        (_FakeX.ButtonPress, 1, 0, 0),
        (_FakeX.ButtonRelease, 1, 0, 0),
    ]


def test_sync_and_close_go_straight_to_the_display() -> None:
    connection, display = _connection()
    connection.sync()
    connection.close()
    assert (display.synced, display.closed) == (1, 1)


# --------------------------------------------------------------------------- #
# Opening a real connection: every refusal names itself.
# --------------------------------------------------------------------------- #
def _patch_xlib(monkeypatch: pytest.MonkeyPatch, xdisplay: Any) -> None:
    monkeypatch.setattr(pointer_x11, "_load_xlib", lambda: (_FakeX, xdisplay))


class _DisplayModule:
    """Stand-in for ``Xlib.display``: a ``Display()`` that yields or refuses."""

    def __init__(self, result: Any) -> None:
        self._result = result

    def Display(self) -> Any:  # python-xlib spells the constructor this way
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


def test_no_display_is_unsupported_not_a_transient_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """There is no X server in this session at all, so no retry will help."""
    _patch_xlib(monkeypatch, _DisplayModule(_FakeDisplay()))
    monkeypatch.delenv("DISPLAY", raising=False)
    with pytest.raises(PointerUnsupportedError, match="DISPLAY"):
        open_xtest_connection()


def test_a_display_that_refuses_the_connection_is_a_backend_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The session has an X server and it said no. That may work next time, so it is
    transient — the distinction a caller uses to choose between fallback and a message."""
    _patch_xlib(monkeypatch, _DisplayModule(ConnectionError("no protocol specified")))
    monkeypatch.setenv("DISPLAY", ":0")
    with pytest.raises(PointerBackendError, match="':0'"):
        open_xtest_connection()


def test_a_server_without_xtest_is_unsupported_and_the_display_is_released(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    display = _FakeDisplay(xtest=False)
    _patch_xlib(monkeypatch, _DisplayModule(display))
    monkeypatch.setenv("DISPLAY", ":0")
    with pytest.raises(PointerUnsupportedError, match="XTEST"):
        open_xtest_connection()
    assert display.closed == 1, "the rejected display connection was leaked"


def test_missing_python_xlib_is_unsupported(monkeypatch: pytest.MonkeyPatch) -> None:
    """The FreeBSD-style dependency-free run and a source tree without the Linux extras
    both land here, and both deserve a sentence rather than an ImportError traceback."""
    monkeypatch.setitem(sys.modules, "Xlib", None)
    with pytest.raises(PointerUnsupportedError, match="python-xlib"):
        pointer_x11._load_xlib()


def test_building_the_sink_opens_the_display_up_front(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A caller choosing a backend must learn now, not from the user's first head turn."""
    display = _FakeDisplay()
    _patch_xlib(monkeypatch, _DisplayModule(display))
    monkeypatch.setenv("DISPLAY", ":0")
    sink = build_x11_pointer_sink()
    assert isinstance(sink, PointerSink)
    assert sink.capabilities().backend == X11_BACKEND_NAME
    sink.move_relative(2.0, 2.0)
    assert display.requests == [(_FakeX.MotionNotify, 1, 2, 2)]
    assert display.synced == 1


def test_the_linux_bundle_offers_the_pointer_sink(monkeypatch: pytest.MonkeyPatch) -> None:
    """`build_pointer_sink` is the seam a pointer consumer will ask, kept out of
    `build_platform` so an ordinary dictation start-up opens no display connection."""
    from yazses.platform import linux as linux_bundle

    display = _FakeDisplay()
    _patch_xlib(monkeypatch, _DisplayModule(display))
    monkeypatch.setenv("DISPLAY", ":0")
    sink = linux_bundle.build_pointer_sink()
    assert sink.capabilities().backend == X11_BACKEND_NAME
    assert "build_pointer_sink" in linux_bundle.__all__


# --------------------------------------------------------------------------- #
# The import stays lazy, because three other platforms import this file's siblings.
# --------------------------------------------------------------------------- #
def test_python_xlib_is_imported_only_inside_a_function() -> None:
    """A module-level `from Xlib import ...` would make this file unimportable on macOS
    and Windows, where python-xlib is correctly absent — and this test module, which the
    shared contract suite runs from, imports it on every platform."""
    source = Path(pointer_x11.__file__)
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
