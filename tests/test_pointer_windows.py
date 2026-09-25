"""The Windows pointer backend, on Linux, against a fake `SendInput` (ADR-v2-146).

Three parts, matching the three layers in `src/yazses/platform/windows/pointer.py`.

`TestWindowsPointerSink` inherits the shared contract from `tests/pointer_contract.py` and
runs it against the real `WindowsPointerSink` with a recording double in place of Win32.

The pure event builders are then tested directly — they hold the whole sign convention and
the `WHEEL_DELTA` scaling, and they need nothing mocked.

Finally `SendInputMouseApi` is driven with a stand-in for `user32.SendInput`. ctypes works
on Linux, so this part packs the real `INPUT[]` array and reads the real struct fields back
out: the flags, the signed pixel deltas and the two's-complement wheel delta are all
genuinely exercised.

**What these tests do not prove.** No `SendInput` has been called. Worse, the real one
cannot tell us much even when it is: it returns the number of events it *inserted into the
input stream*, which UIPI and window focus can silently discard afterwards — this project
has already shipped an injection bug where one application typed perfectly and another
received rows of `?` with nothing in any log. So the failure path asserted below is the
only one visible from this side, and "the pointer moved on Windows" is not a claim any test
in this repository makes.
"""

from __future__ import annotations

import ctypes
from typing import Any

import pytest

from tests.pointer_contract import PointerSinkContract
from tests.pointer_fake import PointerAction
from yazses.platform.windows.injector import _INPUT, INJECTED_TAG
from yazses.platform.windows.pointer import (
    INPUT_MOUSE,
    MOUSEEVENTF_HWHEEL,
    MOUSEEVENTF_LEFTDOWN,
    MOUSEEVENTF_LEFTUP,
    MOUSEEVENTF_MIDDLEDOWN,
    MOUSEEVENTF_MIDDLEUP,
    MOUSEEVENTF_MOVE,
    MOUSEEVENTF_RIGHTDOWN,
    MOUSEEVENTF_RIGHTUP,
    MOUSEEVENTF_WHEEL,
    WHEEL_DELTA,
    WINDOWS_POINTER_CAPABILITIES,
    MouseEvent,
    SendInputMouseApi,
    WindowsPointerSink,
    button_events,
    move_events,
    pack_inputs,
    scroll_events,
)
from yazses.pointer.base import (
    PointerBackendError,
    PointerButton,
    PointerUnsupportedError,
)


class _RecordingMouseApi:
    """A `WindowsMouseApi` that records instead of sending, and can be made to fail.

    It records the same `PointerAction` values every other backend's double records, so the
    shared contract asserts identical sequences everywhere. A failed operation records
    nothing, because the contract's promise is that a failed action did not happen.

    `fail_with` raises a plain `OSError`, deliberately not a `PointerError`: ctypes raises
    `OSError`, and translating it is the sink's job. Injecting an already-correct error
    would test nothing.
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

    def press(self, button: PointerButton) -> None:
        self._record(PointerAction.press(button))

    def release(self, button: PointerButton) -> None:
        self._record(PointerAction.release(button))

    def scroll(self, dx: float, dy: float) -> None:
        self._record(PointerAction.scroll(dx, dy))

    def close(self) -> None:
        self.actions.append(PointerAction.close())


class TestWindowsPointerSink(PointerSinkContract):
    """The shared contract, applied to the real sink over a fake Win32."""

    def setup_method(self) -> None:
        self._apis: dict[int, _RecordingMouseApi] = {}

    def make_sink(self) -> WindowsPointerSink:
        api = _RecordingMouseApi()
        sink = WindowsPointerSink(api=api)
        self._apis[id(sink)] = api
        return sink

    def recorded(self, sink: Any) -> list[PointerAction]:
        return list(self._apis[id(sink)].actions)

    def induce_failure(self, sink: Any) -> None:
        self._apis[id(sink)].fail_with(OSError("SendInput refused"))

    def clear_failure(self, sink: Any) -> None:
        self._apis[id(sink)].fail_with(None)


# --------------------------------------------------------------------------- #
# The sink's own promises, beyond the shared contract
# --------------------------------------------------------------------------- #


def test_the_backend_identifier_is_the_one_the_protocol_documents() -> None:
    assert WINDOWS_POINTER_CAPABILITIES.backend == "sendinput"


def test_absolute_motion_is_reported_absent_and_refused() -> None:
    """Deliberate: `MOUSEEVENTF_ABSOLUTE` takes 0-65535 over a multi-DPI virtual desktop.

    ADR-v2-146 names exactly that as the case absolute coordinates get wrong, and no
    Windows machine is available to check a conversion against. An explicit error costs a
    future capability; a wrong conversion would fling the pointer onto another screen.
    """
    assert WINDOWS_POINTER_CAPABILITIES.absolute_motion is False
    sink = WindowsPointerSink(api=_RecordingMouseApi())
    with pytest.raises(PointerUnsupportedError):
        sink.move_absolute(10.0, 20.0)


def test_a_ctypes_error_becomes_a_pointer_backend_error() -> None:
    """A caller holding a `PointerSink` catches `PointerError`, not `OSError`."""
    api = _RecordingMouseApi()
    api.fail_with(OSError("user32 went away"))
    sink = WindowsPointerSink(api=api)
    with pytest.raises(PointerBackendError) as caught:
        sink.move_relative(1.0, 1.0)
    assert "user32 went away" in str(caught.value)


def test_a_release_that_fails_says_the_button_may_still_be_down() -> None:
    class _PressOnly(_RecordingMouseApi):
        def release(self, button: PointerButton) -> None:
            raise OSError("release refused")

    sink = WindowsPointerSink(api=_PressOnly())
    with pytest.raises(PointerBackendError) as caught:
        sink.click(PointerButton.MIDDLE)
    assert "release the middle button" in str(caught.value)


def test_constructing_the_sink_loads_no_user32(monkeypatch: pytest.MonkeyPatch) -> None:
    """A base install on Linux must build this sink; `user32` is loaded on first use only."""
    import yazses.platform.windows.pointer as backend

    def _explode() -> Any:
        raise AssertionError("constructing a pointer sink must not load user32")

    monkeypatch.setattr(backend, "_load_user32", _explode)
    WindowsPointerSink()
    SendInputMouseApi()


# --------------------------------------------------------------------------- #
# The pure event builders
# --------------------------------------------------------------------------- #


def test_motion_events_carry_the_pixel_delta_with_win32_signs() -> None:
    assert move_events(3, -4) == [MouseEvent(flags=MOUSEEVENTF_MOVE, dx=3, dy=-4)]


def test_a_zero_step_produces_no_event_at_all() -> None:
    """The accumulator still holds that motion; a zero-delta move would be pure noise."""
    assert move_events(0, 0) == []


@pytest.mark.parametrize(
    ("button", "down_flag", "up_flag"),
    [
        (PointerButton.LEFT, MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
        (PointerButton.RIGHT, MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
        (PointerButton.MIDDLE, MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
    ],
)
def test_each_button_has_its_own_documented_flag_pair(
    button: PointerButton, down_flag: int, up_flag: int
) -> None:
    assert button_events(button, down=True) == [MouseEvent(flags=down_flag)]
    assert button_events(button, down=False) == [MouseEvent(flags=up_flag)]


def test_scrolling_down_sends_a_negative_wheel_delta() -> None:
    """Microsoft: a positive wheel delta is *forward, away from the user* — that is up."""
    assert scroll_events(0, 1) == [
        MouseEvent(flags=MOUSEEVENTF_WHEEL, mouse_data=-WHEEL_DELTA)
    ]


def test_scrolling_up_sends_a_positive_wheel_delta() -> None:
    assert scroll_events(0, -2) == [
        MouseEvent(flags=MOUSEEVENTF_WHEEL, mouse_data=2 * WHEEL_DELTA)
    ]


def test_scrolling_right_is_not_negated() -> None:
    """Microsoft documents a positive `MOUSEEVENTF_HWHEEL` delta as a tilt to the right."""
    assert scroll_events(1, 0) == [
        MouseEvent(flags=MOUSEEVENTF_HWHEEL, mouse_data=WHEEL_DELTA)
    ]


def test_scrolling_left_sends_a_negative_horizontal_delta() -> None:
    assert scroll_events(-1, 0) == [
        MouseEvent(flags=MOUSEEVENTF_HWHEEL, mouse_data=-WHEEL_DELTA)
    ]


def test_both_axes_at_once_produce_two_events_vertical_first() -> None:
    assert scroll_events(1, 1) == [
        MouseEvent(flags=MOUSEEVENTF_WHEEL, mouse_data=-WHEEL_DELTA),
        MouseEvent(flags=MOUSEEVENTF_HWHEEL, mouse_data=WHEEL_DELTA),
    ]


def test_no_notches_means_no_scroll_events() -> None:
    assert scroll_events(0, 0) == []


# --------------------------------------------------------------------------- #
# The real ctypes packing
# --------------------------------------------------------------------------- #


def _as_signed(mouse_data: int) -> int:
    """Read a `DWORD` back as the signed value it encodes."""
    return mouse_data - 0x100000000 if mouse_data >= 0x80000000 else mouse_data


def test_packing_fills_the_real_mouseinput_fields() -> None:
    array = pack_inputs([MouseEvent(flags=MOUSEEVENTF_MOVE, dx=7, dy=-9)])
    assert len(array) == 1
    assert array[0].type == INPUT_MOUSE
    assert array[0].mi.dwFlags == MOUSEEVENTF_MOVE
    assert array[0].mi.dx == 7
    assert array[0].mi.dy == -9
    assert array[0].mi.time == 0


def test_every_packed_event_carries_the_injected_tag() -> None:
    """The same stamp the keyboard injector uses, so a future mouse hook can tell ours."""
    array = pack_inputs(button_events(PointerButton.LEFT, down=True))
    assert array[0].mi.dwExtraInfo == INJECTED_TAG


def test_a_negative_wheel_delta_packs_as_twos_complement() -> None:
    """`mouseData` is a `DWORD`; the sign has to survive the unsigned field."""
    array = pack_inputs(scroll_events(0, 1))
    assert _as_signed(array[0].mi.mouseData) == -WHEEL_DELTA


# --------------------------------------------------------------------------- #
# SendInputMouseApi, against a fake user32.SendInput
# --------------------------------------------------------------------------- #


class _FakeSendInput:
    """Stands in for `user32.SendInput`, recording the array it is handed.

    *inserted* controls the return value, which is how the short-count failure path gets
    exercised: `None` means "report every event inserted", an int means report that many.
    """

    def __init__(self, inserted: int | None = None) -> None:
        self.inserted = inserted
        self.calls: list[list[tuple[int, int, int, int]]] = []

    def __call__(self, count: int, array: Any, size: int) -> int:
        assert size == ctypes.sizeof(_INPUT), "SendInput was handed the wrong struct size"
        assert count == len(array)
        self.calls.append(
            [
                (array[i].mi.dwFlags, array[i].mi.dx, array[i].mi.dy,
                 _as_signed(array[i].mi.mouseData))
                for i in range(count)
            ]
        )
        return count if self.inserted is None else self.inserted


def test_relative_motion_sends_one_move_event() -> None:
    send = _FakeSendInput()
    SendInputMouseApi(send_input=send).move_relative(3.0, -4.0)
    assert send.calls == [[(MOUSEEVENTF_MOVE, 3, -4, 0)]]


def test_sub_pixel_motion_accumulates_instead_of_vanishing() -> None:
    """Head-driven motion arrives in fractions of a pixel; rounding each call loses it."""
    send = _FakeSendInput()
    api = SendInputMouseApi(send_input=send)
    api.move_relative(0.4, 0.0)
    assert send.calls == []
    api.move_relative(0.4, 0.0)
    assert send.calls == [[(MOUSEEVENTF_MOVE, 1, 0, 0)]]


def test_a_click_is_two_calls_press_then_release() -> None:
    send = _FakeSendInput()
    api = SendInputMouseApi(send_input=send)
    api.press(PointerButton.LEFT)
    api.release(PointerButton.LEFT)
    assert send.calls == [
        [(MOUSEEVENTF_LEFTDOWN, 0, 0, 0)],
        [(MOUSEEVENTF_LEFTUP, 0, 0, 0)],
    ]


def test_scroll_signs_reach_sendinput_negated_vertically_only() -> None:
    send = _FakeSendInput()
    api = SendInputMouseApi(send_input=send)
    api.scroll(0.0, 1.0)
    api.scroll(1.0, 0.0)
    assert send.calls == [
        [(MOUSEEVENTF_WHEEL, 0, 0, -WHEEL_DELTA)],
        [(MOUSEEVENTF_HWHEEL, 0, 0, WHEEL_DELTA)],
    ]


def test_both_scroll_axes_go_out_in_one_call() -> None:
    send = _FakeSendInput()
    SendInputMouseApi(send_input=send).scroll(1.0, 1.0)
    assert send.calls == [
        [(MOUSEEVENTF_WHEEL, 0, 0, -WHEEL_DELTA),
         (MOUSEEVENTF_HWHEEL, 0, 0, WHEEL_DELTA)],
    ]


def test_a_short_insert_count_raises_and_names_the_likely_cause() -> None:
    """The only failure this side can see. A full count still proves nothing landed."""
    send = _FakeSendInput(inserted=0)
    with pytest.raises(PointerBackendError) as caught:
        SendInputMouseApi(send_input=send).move_relative(5.0, 5.0)
    message = str(caught.value)
    assert "0/1" in message
    assert "ACCESS_DENIED" in message


def test_a_failed_motion_is_not_folded_into_the_next_one() -> None:
    """ADR-v2-146 rule 4: a stale command is never repeated after a backend failure.

    The pointer must not glide to catch up once the backend recovers, so a delta whose
    `SendInput` failed is spent, not re-offered.
    """
    send = _FakeSendInput(inserted=0)
    api = SendInputMouseApi(send_input=send)
    with pytest.raises(PointerBackendError):
        api.move_relative(10.0, 0.0)
    send.inserted = None
    send.calls.clear()
    api.move_relative(2.0, 0.0)
    assert send.calls == [[(MOUSEEVENTF_MOVE, 2, 0, 0)]], "the lost 10 px came back"


def test_closing_drops_both_residuals() -> None:
    send = _FakeSendInput()
    api = SendInputMouseApi(send_input=send)
    api.move_relative(0.4, 0.0)
    api.scroll(0.0, 0.4)
    api.close()
    api.move_relative(0.4, 0.0)
    api.scroll(0.0, 0.4)
    assert send.calls == [], "a residual kept across close leaks into the next session"


def test_the_sink_over_the_real_api_still_satisfies_the_protocol() -> None:
    """`isinstance` against a `runtime_checkable` protocol is a shape check, so no Win32.

    This is the check that would fail if `PointerSink` grew a method this backend lacked.
    """
    from yazses.pointer.base import PointerSink

    assert isinstance(WindowsPointerSink(), PointerSink)
