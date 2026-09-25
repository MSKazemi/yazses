"""The macOS pointer backend, on Linux, against a fake CoreGraphics (ADR-v2-146).

Two halves, matching the two layers in `src/yazses/platform/macos/pointer.py`.

`TestMacosPointerSink` inherits the shared contract from `tests/pointer_contract.py` and
runs it against the real `MacosPointerSink` with a recording double in place of Quartz, so
macOS is held to exactly the behaviour every other backend is.

The rest drives the real `QuartzMouseApi` against a hand-written stand-in for the PyObjC
`Quartz` module, which is how the event types, the button constants, the read-add-post
shape of relative motion and the flipped scroll sign get covered on a machine that has no
CoreGraphics at all.

**What these tests do not prove.** Nothing here has spoken to a real `CGEventPost`. They
prove this backend asks for the right thing; whether macOS then does it — whether the
Accessibility grant is enough, whether a click without `kCGMouseEventClickState` registers
everywhere — is hardware evidence and no test in this repository has it. A green run here
is a green run against a fake by construction, and the module docstring of the backend says
the same thing.
"""

from __future__ import annotations

import sys
from typing import Any

import pytest

from tests.pointer_contract import PointerSinkContract
from tests.pointer_fake import PointerAction
from yazses.platform.macos.pointer import (
    MACOS_POINTER_CAPABILITIES,
    MacosPointerSink,
    QuartzMouseApi,
)
from yazses.pointer.base import (
    PointerBackendError,
    PointerButton,
    PointerUnsupportedError,
)


class _RecordingQuartzApi:
    """A `QuartzPointerApi` that records instead of posting, and can be made to fail.

    It records the same `PointerAction` values every other backend's double records, which
    is what lets the shared contract assert identical sequences everywhere. An operation
    that raises records nothing: the contract's promise is that a failed action did not
    happen, and a recorder that logged attempts would let this backend "succeed" at
    something no pointer did.

    `fail_with` raises a plain `OSError`, deliberately not a `PointerError` — PyObjC raises
    bridge errors, and the sink's job is to translate them. Injecting an already-correct
    error would test nothing.
    """

    def __init__(self) -> None:
        self.actions: list[PointerAction] = []
        self.failure: Exception | None = None

    def fail_with(self, error: Exception | None) -> None:
        self.failure = error

    def _record(self, action: PointerAction) -> None:
        if self.failure is not None:
            raise self.failure
        self.actions.append(action)

    def move_relative(self, dx: float, dy: float) -> None:
        self._record(PointerAction.move_relative(dx, dy))

    def move_absolute(self, x: float, y: float) -> None:
        self._record(PointerAction.move_absolute(x, y))

    def press(self, button: PointerButton) -> None:
        self._record(PointerAction.press(button))

    def release(self, button: PointerButton) -> None:
        self._record(PointerAction.release(button))

    def scroll(self, dx: float, dy: float) -> None:
        self._record(PointerAction.scroll(dx, dy))

    def close(self) -> None:
        self.actions.append(PointerAction.close())


class TestMacosPointerSink(PointerSinkContract):
    """The shared contract, applied to the real sink over a fake CoreGraphics."""

    def setup_method(self) -> None:
        self._apis: dict[int, _RecordingQuartzApi] = {}

    def make_sink(self) -> MacosPointerSink:
        api = _RecordingQuartzApi()
        sink = MacosPointerSink(api=api)
        self._apis[id(sink)] = api
        return sink

    def recorded(self, sink: Any) -> list[PointerAction]:
        return list(self._apis[id(sink)].actions)

    def induce_failure(self, sink: Any) -> None:
        self._apis[id(sink)].fail_with(OSError("CGEventPost refused"))

    def clear_failure(self, sink: Any) -> None:
        self._apis[id(sink)].fail_with(None)


# --------------------------------------------------------------------------- #
# The sink's own promises, beyond the shared contract
# --------------------------------------------------------------------------- #


def test_the_backend_identifier_is_the_one_the_protocol_documents() -> None:
    assert MACOS_POINTER_CAPABILITIES.backend == "quartz"


def test_horizontal_scroll_is_reported_absent_and_refused() -> None:
    """Deliberate: Apple documents no sign for scroll axis 2 and we cannot verify one.

    An inverted horizontal scroll makes a head-driven pointer fight its user, so the axis
    is declared missing rather than guessed. This test is the record of that decision --
    if someone verifies the sign on a Mac, it changes with the capability.
    """
    assert MACOS_POINTER_CAPABILITIES.scroll_horizontal is False
    sink = MacosPointerSink(api=_RecordingQuartzApi())
    with pytest.raises(PointerUnsupportedError):
        sink.scroll(2.0, 0.0)


def test_a_bridge_error_becomes_a_pointer_backend_error() -> None:
    """A caller holding a `PointerSink` catches `PointerError`, not `objc.error`."""
    api = _RecordingQuartzApi()
    api.fail_with(OSError("the window server went away"))
    sink = MacosPointerSink(api=api)
    with pytest.raises(PointerBackendError) as caught:
        sink.move_relative(1.0, 1.0)
    assert "the window server went away" in str(caught.value)


def test_a_release_that_fails_says_the_button_may_still_be_down() -> None:
    """The press landed and the release did not; the user needs to know which button."""

    class _PressOnly(_RecordingQuartzApi):
        def release(self, button: PointerButton) -> None:
            raise OSError("release refused")

    sink = MacosPointerSink(api=_PressOnly())
    with pytest.raises(PointerBackendError) as caught:
        sink.click(PointerButton.RIGHT)
    assert "release the right button" in str(caught.value)


def test_constructing_the_sink_imports_no_pyobjc(monkeypatch: pytest.MonkeyPatch) -> None:
    """The base install on Linux must import this module and build the sink regardless.

    Rule 3 in AGENTS.md: heavy platform dependencies are imported inside the function that
    needs them. Quartz is not merely absent here, it is unobtainable — so the loader is
    replaced with one that explodes, and construction must still not reach it.
    """
    import yazses.platform.macos.pointer as backend

    def _explode() -> Any:
        raise AssertionError("constructing a pointer sink must not import PyObjC")

    monkeypatch.setattr(backend, "_load_quartz", _explode)
    MacosPointerSink()
    QuartzMouseApi()
    assert "Quartz" not in sys.modules


def test_the_real_api_only_reaches_for_quartz_when_it_is_used() -> None:
    calls: list[str] = []

    class _Sentinel(QuartzMouseApi):
        def _q(self) -> Any:
            calls.append("loaded")
            raise ImportError("no PyObjC here")

    api = _Sentinel()
    assert calls == []
    with pytest.raises(ImportError):
        api.move_absolute(1.0, 2.0)
    assert calls == ["loaded"]


# --------------------------------------------------------------------------- #
# The native layer, against a fake Quartz module
# --------------------------------------------------------------------------- #


class _Point:
    """A stand-in for `CGPoint`, which PyObjC exposes with `.x` / `.y`."""

    def __init__(self, x: float, y: float) -> None:
        self.x = x
        self.y = y


class _FakeQuartz:
    """The handful of CoreGraphics names `QuartzMouseApi` touches, and nothing else.

    Every constant is a distinct string so an assertion can tell which event type was
    posted without knowing the real numeric values — which is the honest position, since
    nothing here has ever seen the real ones.
    """

    kCGEventMouseMoved = "mouse-moved"
    kCGEventLeftMouseDown = "left-down"
    kCGEventLeftMouseUp = "left-up"
    kCGEventRightMouseDown = "right-down"
    kCGEventRightMouseUp = "right-up"
    kCGEventOtherMouseDown = "other-down"
    kCGEventOtherMouseUp = "other-up"
    kCGMouseButtonLeft = "button-left"
    kCGMouseButtonRight = "button-right"
    kCGMouseButtonCenter = "button-center"
    kCGHIDEventTap = "hid-tap"
    kCGScrollEventUnitLine = "unit-line"

    def __init__(self, cursor: tuple[float, float] = (100.0, 200.0)) -> None:
        self.cursor = cursor
        self.posted: list[tuple[str, Any]] = []
        self.mouse_event_returns_null = False
        self.scroll_event_returns_null = False
        self.probe_returns_null = False

    # -- the API surface QuartzMouseApi uses ------------------------------- #

    def CGEventCreate(self, source: Any) -> Any:  # noqa: N802 - Apple's spelling
        return None if self.probe_returns_null else ("probe", self.cursor)

    def CGEventGetLocation(self, event: Any) -> _Point:  # noqa: N802
        return _Point(*event[1])

    def CGEventCreateMouseEvent(  # noqa: N802
        self, source: Any, event_type: str, point: tuple[float, float], button: str
    ) -> Any:
        if self.mouse_event_returns_null:
            return None
        return ("mouse", event_type, point, button)

    def CGEventCreateScrollWheelEvent(  # noqa: N802
        self, source: Any, unit: str, wheel_count: int, *wheels: int
    ) -> Any:
        if self.scroll_event_returns_null:
            return None
        return ("scroll", unit, wheel_count, wheels)

    def CGEventPost(self, tap: str, event: Any) -> None:  # noqa: N802
        self.posted.append((tap, event))


def _api(**kwargs: Any) -> tuple[QuartzMouseApi, _FakeQuartz]:
    quartz = _FakeQuartz(**kwargs)
    return QuartzMouseApi(quartz=quartz), quartz


def test_relative_motion_reads_the_cursor_and_posts_the_sum() -> None:
    """CoreGraphics has no relative mouse event; this is the read-add-post it requires."""
    api, quartz = _api(cursor=(100.0, 200.0))
    api.move_relative(5.0, -2.5)
    assert quartz.posted == [
        ("hid-tap", ("mouse", "mouse-moved", (105.0, 197.5), "button-left")),
    ]


def test_absolute_motion_posts_the_coordinates_untouched() -> None:
    api, quartz = _api()
    api.move_absolute(12.5, 34.0)
    assert quartz.posted == [("hid-tap", ("mouse", "mouse-moved", (12.5, 34.0), "button-left"))]


@pytest.mark.parametrize(
    ("button", "down_type", "up_type", "constant"),
    [
        (PointerButton.LEFT, "left-down", "left-up", "button-left"),
        (PointerButton.RIGHT, "right-down", "right-up", "button-right"),
        (PointerButton.MIDDLE, "other-down", "other-up", "button-center"),
    ],
)
def test_each_button_posts_its_own_event_types_at_the_cursor(
    button: PointerButton, down_type: str, up_type: str, constant: str
) -> None:
    """The middle button is `OtherMouse*` plus a button number, not a `MiddleMouse*`."""
    api, quartz = _api(cursor=(7.0, 8.0))
    api.press(button)
    api.release(button)
    assert quartz.posted == [
        ("hid-tap", ("mouse", down_type, (7.0, 8.0), constant)),
        ("hid-tap", ("mouse", up_type, (7.0, 8.0), constant)),
    ]


def test_scrolling_down_posts_a_negative_line_count() -> None:
    """The sign flip lives here: Apple's axis 1 is up-positive, the boundary is down."""
    api, quartz = _api()
    api.scroll(0.0, 3.0)
    assert quartz.posted == [("hid-tap", ("scroll", "unit-line", 1, (-3,)))]


def test_scrolling_up_posts_a_positive_line_count() -> None:
    api, quartz = _api()
    api.scroll(0.0, -2.0)
    assert quartz.posted == [("hid-tap", ("scroll", "unit-line", 1, (2,)))]


def test_a_fraction_of_a_line_is_carried_not_dropped() -> None:
    """A slow head-driven scroll must still scroll, one accumulated line at a time."""
    api, quartz = _api()
    api.scroll(0.0, 0.4)
    assert quartz.posted == []
    api.scroll(0.0, 0.4)
    assert quartz.posted == [("hid-tap", ("scroll", "unit-line", 1, (-1,)))]


def test_a_null_mouse_event_is_an_error_not_a_silent_skip() -> None:
    """The keyboard injector logs and returns here. A pointer sink may not: ADR-v2-146."""
    api, quartz = _api()
    quartz.mouse_event_returns_null = True
    with pytest.raises(PointerBackendError):
        api.move_absolute(1.0, 1.0)
    assert quartz.posted == []


def test_a_null_scroll_event_is_an_error() -> None:
    api, quartz = _api()
    quartz.scroll_event_returns_null = True
    with pytest.raises(PointerBackendError):
        api.scroll(0.0, 1.0)
    assert quartz.posted == []


def test_an_unreadable_cursor_position_is_an_error() -> None:
    api, quartz = _api()
    quartz.probe_returns_null = True
    with pytest.raises(PointerBackendError):
        api.move_relative(1.0, 1.0)
    assert quartz.posted == []


def test_closing_the_real_api_drops_the_scroll_remainder() -> None:
    api, quartz = _api()
    api.scroll(0.0, 0.4)
    api.close()
    api.scroll(0.0, 0.4)
    assert quartz.posted == [], "a residual kept across close would leak into the next session"


def test_the_sink_over_the_real_api_still_satisfies_the_protocol() -> None:
    """The sink built the way `build_platform()` builds it, with no api argument.

    `isinstance` against a `runtime_checkable` protocol is a shape check only, so this
    needs no PyObjC — and it is the check that would fail if `PointerSink` grew a method
    this backend did not implement.
    """
    from yazses.pointer.base import PointerSink

    assert isinstance(MacosPointerSink(), PointerSink)
