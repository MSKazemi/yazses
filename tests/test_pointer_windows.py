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
    SPI_GETMOUSE,
    SPI_GETMOUSESPEED,
    WHEEL_DELTA,
    WINDOWS_POINTER_CAPABILITIES,
    MouseBallistics,
    MouseEvent,
    SendInputMouseApi,
    WindowsPointerSink,
    ballistics_warning,
    button_events,
    move_events,
    pack_inputs,
    read_mouse_ballistics,
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


def test_a_short_insert_count_raises_and_states_only_what_microsoft_documents() -> None:
    """The only failure this side can see. A full count still proves nothing landed.

    Microsoft's `SendInput` page: a zero return means "the input was already blocked by
    another thread", and "neither GetLastError nor the return value will indicate the
    failure was caused by UIPI blocking". The message must not tell the user a short count
    is a UIPI/elevation problem — that sends them to the wrong fix.
    """
    send = _FakeSendInput(inserted=0)
    with pytest.raises(PointerBackendError) as caught:
        SendInputMouseApi(send_input=send).move_relative(5.0, 5.0)
    message = str(caught.value)
    assert "0/1" in message
    assert "blocked by another thread" in message
    assert "ACCESS_DENIED" not in message
    assert "means the focused window runs elevated" not in message


def test_a_partial_insert_count_names_how_many_went_in() -> None:
    """Two scroll axes go out in one call; 1 of 2 inserted is a failure, not a success."""
    send = _FakeSendInput(inserted=1)
    with pytest.raises(PointerBackendError) as caught:
        SendInputMouseApi(send_input=send).scroll(1.0, 1.0)
    assert "1/2" in str(caught.value)


# --------------------------------------------------------------------------- #
# Struct layout: what Linux ctypes cannot tell us
# --------------------------------------------------------------------------- #


def _llp64_size_align(ctype: Any, pointer_bytes: int) -> tuple[int, int]:
    """Size and alignment of a field type under Windows' LLP64 model.

    On Windows `long` and `DWORD` are 4 bytes and a pointer is 4 (x86) or 8 (x64). On this
    Linux box `c_long` is 8, which is why ``ctypes.sizeof(_INPUT)`` is 56 here and 40 there:
    the tests above pack the right *fields* but a layout assertion against the host's
    ``sizeof`` would be vacuous. This recomputes the layout from the declared field types.
    """
    if ctype is ctypes.c_void_p:
        return pointer_bytes, pointer_bytes
    if ctype in (ctypes.c_long, ctypes.c_ulong):  # LONG, DWORD
        return 4, 4
    if ctype in (ctypes.c_ushort,):  # WORD
        return 2, 2
    raise AssertionError(f"unmodelled field type {ctype!r}")


def _llp64_struct(fields: list[tuple[str, Any]], pointer_bytes: int) -> tuple[int, int]:
    offset = max_align = 0
    for _name, ctype in fields:
        size, align = _llp64_size_align(ctype, pointer_bytes)
        offset = -(-offset // align) * align + size
        max_align = max(max_align, align)
    return -(-offset // max_align) * max_align, max_align


@pytest.mark.parametrize(("pointer_bytes", "mouseinput", "input_size"), [(8, 32, 40), (4, 24, 28)])
def test_mouseinput_field_order_and_types_give_the_documented_win32_sizes(
    pointer_bytes: int, mouseinput: int, input_size: int
) -> None:
    """`MOUSEINPUT` is LONG, LONG, DWORD, DWORD, DWORD, ULONG_PTR; `INPUT` is 40 bytes on
    x64 and 28 on x86 (the `cbSize` `SendInput` insists on). Microsoft's field list:
    https://learn.microsoft.com/en-us/windows/win32/api/winuser/ns-winuser-mouseinput
    """
    from yazses.platform.windows.injector import _KEYBDINPUT, _MOUSEINPUT

    assert [n for n, _ in _MOUSEINPUT._fields_] == [
        "dx", "dy", "mouseData", "dwFlags", "time", "dwExtraInfo",
    ]
    assert _llp64_struct(list(_MOUSEINPUT._fields_), pointer_bytes) == (
        mouseinput, pointer_bytes,
    )
    # The union is as big as its largest member, which is the mouse one on both ABIs.
    keyboard, _ = _llp64_struct(list(_KEYBDINPUT._fields_), pointer_bytes)
    assert keyboard <= mouseinput
    union_align = pointer_bytes
    header = -(-4 // union_align) * union_align  # DWORD type, padded up to the union
    assert header + mouseinput == input_size


# --------------------------------------------------------------------------- #
# Range of the 32-bit fields (ctypes does not check it)
# --------------------------------------------------------------------------- #


def test_a_motion_delta_that_does_not_fit_a_long_is_refused_not_wrapped() -> None:
    """ctypes wraps an out-of-range `c_long` on Windows: +3e9 would arrive as about -1.29e9."""
    with pytest.raises(ValueError, match="32-bit"):
        move_events(3_000_000_000, 0)
    with pytest.raises(ValueError, match="32-bit"):
        move_events(0, -3_000_000_000)


def test_the_largest_legal_delta_is_still_sent() -> None:
    assert move_events(2**31 - 1, -(2**31)) == [
        MouseEvent(flags=MOUSEEVENTF_MOVE, dx=2**31 - 1, dy=-(2**31))
    ]


def test_a_scroll_whose_wheel_delta_overflows_is_refused_not_wrapped() -> None:
    # 20_000_000 notches * 120 = 2.4e9 > 2**31 - 1
    with pytest.raises(ValueError, match="32-bit"):
        scroll_events(0, 20_000_000)
    with pytest.raises(ValueError, match="32-bit"):
        scroll_events(20_000_000, 0)


def test_an_overflowing_motion_through_the_sink_is_a_backend_error_and_sends_nothing() -> None:
    send = _FakeSendInput()
    sink = WindowsPointerSink(api=SendInputMouseApi(send_input=send))
    with pytest.raises(PointerBackendError):
        sink.move_relative(3.0e9, 0.0)
    assert send.calls == []


# --------------------------------------------------------------------------- #
# Pointer ballistics: relative motion is NOT guaranteed 1:1
# --------------------------------------------------------------------------- #


def test_neutral_pointer_settings_do_not_warn() -> None:
    assert ballistics_warning(MouseBallistics(0, 0, 0, 10)) == ""


@pytest.mark.parametrize(
    "settings",
    [MouseBallistics(6, 10, 1, 10), MouseBallistics(0, 0, 0, 14), MouseBallistics(0, 0, 0, 3)],
)
def test_acceleration_or_a_non_default_speed_warns(settings: MouseBallistics) -> None:
    assert "scaled by the user's pointer settings" in ballistics_warning(settings)


def test_the_first_real_move_warns_once_when_pointer_settings_distort_it(
    caplog: pytest.LogCaptureFixture,
) -> None:
    calls: list[int] = []

    def reader() -> MouseBallistics:
        calls.append(1)
        return MouseBallistics(6, 10, 1, 10)

    api = SendInputMouseApi(send_input=_FakeSendInput(), ballistics=reader)
    with caplog.at_level("WARNING", logger="yazses.platform.windows.pointer"):
        api.move_relative(3.0, 0.0)
        api.move_relative(3.0, 0.0)
    warnings = [r for r in caplog.records if "pointer settings" in r.getMessage()]
    assert len(warnings) == 1
    assert calls == [1], "the settings are read once, not once per frame"


def test_a_sub_pixel_move_that_sends_nothing_does_not_trigger_the_probe() -> None:
    calls: list[int] = []
    api = SendInputMouseApi(
        send_input=_FakeSendInput(), ballistics=lambda: calls.append(1)  # type: ignore[arg-type,return-value]
    )
    api.move_relative(0.2, 0.0)
    assert calls == []


def test_a_reader_that_raises_never_fails_the_move() -> None:
    def reader() -> MouseBallistics:
        raise OSError("SystemParametersInfo unavailable")

    send = _FakeSendInput()
    SendInputMouseApi(send_input=send, ballistics=reader).move_relative(2.0, 0.0)
    assert send.calls == [[(MOUSEEVENTF_MOVE, 2, 0, 0)]]


def test_a_test_double_for_send_input_never_reaches_for_user32(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import yazses.platform.windows.pointer as backend

    def _explode() -> Any:
        raise AssertionError("an injected SendInput must not load user32")

    monkeypatch.setattr(backend, "_load_user32", _explode)
    SendInputMouseApi(send_input=_FakeSendInput()).move_relative(2.0, 0.0)


class _FakeUser32:
    """Just `SystemParametersInfoW`, writing what Windows would."""

    def __init__(self, params: tuple[int, int, int], speed: int, ok: bool = True) -> None:
        self.params, self.speed, self.ok = params, speed, ok
        self.actions: list[int] = []

    def SystemParametersInfoW(  # noqa: N802 - Win32's spelling
        self, action: int, ui_param: int, pv_param: Any, win_ini: int
    ) -> int:
        self.actions.append(action)
        if not self.ok:
            return 0
        if action == SPI_GETMOUSE:
            for i, v in enumerate(self.params):
                pv_param[i] = v
        elif action == SPI_GETMOUSESPEED:
            pv_param._obj.value = self.speed
        return 1


def test_the_settings_reader_uses_the_documented_actions_and_buffers() -> None:
    assert (SPI_GETMOUSE, SPI_GETMOUSESPEED) == (0x0003, 0x0070)
    user32 = _FakeUser32((6, 10, 1), 12)
    assert read_mouse_ballistics(user32) == MouseBallistics(6, 10, 1, 12)
    assert user32.actions == [0x0003, 0x0070]


def test_a_failed_settings_query_is_none_not_a_guess() -> None:
    assert read_mouse_ballistics(_FakeUser32((0, 0, 0), 10, ok=False)) is None


def test_user32_is_loaded_once_and_kept(monkeypatch: pytest.MonkeyPatch) -> None:
    """The keyboard injector reloads per call; at 30 Hz the pointer must not."""
    import yazses.platform.windows.pointer as backend

    loads: list[int] = []

    class _U32:
        def SendInput(self, count: int, array: Any, size: int) -> int:  # noqa: N802
            return count

    def _load() -> Any:
        loads.append(1)
        return _U32()

    monkeypatch.setattr(backend, "_load_user32", _load)
    api = SendInputMouseApi(ballistics=lambda: None)
    for _ in range(5):
        api.move_relative(1.0, 0.0)
    assert len(loads) == 1


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
