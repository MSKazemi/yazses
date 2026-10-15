"""Windows pointer output — `SendInput` mouse events (ADR-v2-146).

The Windows half of the `PointerSink` boundary defined in `src/yazses/pointer/base.py`.
It reuses the `INPUT` / `MOUSEINPUT` structures and the `user32` loader that
`platform/windows/injector.py` already built for keyboard injection — one copy of those
declarations, not two that can drift, and the `use_last_error=True` handle there is what
makes a failure report a real Win32 error code instead of zero.

**Three layers, and the seams are why CI needs no PC.**

1. :class:`WindowsPointerSink` holds the contract: capabilities, edge validation,
   press-then-release ordering, close semantics, failure translation. It knows nothing
   about Win32 and takes its API object as a constructor argument.
2. :func:`move_events`, :func:`button_events` and :func:`scroll_events` are pure: whole
   steps in, `MOUSEINPUT` field values out. The whole sign convention and the
   `WHEEL_DELTA` scaling live there and are unit-tested directly.
3. :class:`SendInputMouseApi` packs those values into the real ctypes array and calls
   `SendInput`. ctypes works on Linux, so even the packing is covered — the only thing a
   test cannot do is make the call land.

**What this backend reports, and why it is not everything.**

* Relative motion — `MOUSEEVENTF_MOVE` takes a signed integer delta, and Microsoft's
  `MOUSEINPUT` page calls it "the number of pixels moved". **It is not 1:1 on a real
  desktop:** the same page's Remarks say relative motion "is subject to the effects of the
  mouse speed and the two-mouse threshold values" and can be multiplied "up to four
  times" (https://learn.microsoft.com/en-us/windows/win32/api/winuser/ns-winuser-mouseinput).
  Those are the user's Pointer Speed / "Enhance pointer precision" settings, so the same
  head movement can travel a different distance on two PCs. That page describes the
  legacy threshold rule only; the curve Windows applies when "Enhance pointer precision"
  is on is not documented there, so this backend does not try to undo it. Instead
  :class:`SendInputMouseApi` reads the settings once (`SystemParametersInfo`,
  https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-systemparametersinfow)
  and logs a warning when they are not neutral, so the cause is visible. The honest fix
  (an absolute `SetCursorPos` path, which ballistics do not touch) needs a Windows machine
  to validate and is deliberately not guessed at here. Sub-pixel deltas accumulate (see
  `src/yazses/pointer/subpixel.py`) rather than rounding to nothing.
* Absolute motion — **reported as unavailable, deliberately.** `MOUSEEVENTF_ABSOLUTE`
  does not take pixels; it takes coordinates normalised to 0-65535, over the primary
  monitor unless `MOUSEEVENTF_VIRTUALDESK` is also set, on a desktop whose monitors can
  each have their own DPI. ADR-v2-146 names multi-monitor and HiDPI absolute coordinates
  as the case that is easy to get wrong, and no Windows machine is available to check a
  conversion against. An explicit `PointerUnsupportedError` costs the voice mouse grid a
  future capability; a wrong conversion would fling a motor-impaired user's pointer to
  the wrong screen. Relative motion, which Head-Pointer actually needs, is unaffected.
* Left, right and middle buttons — all three have documented flag pairs.
* Vertical scroll — supported, **negated here.** Microsoft documents `mouseData` for
  `MOUSEEVENTF_WHEEL` as positive when the wheel turns *forward, away from the user*,
  i.e. scrolling up; the boundary is down-positive, so ``scroll(0, +1)`` sends ``-120``.
* Horizontal scroll — supported and **not** negated. Microsoft documents `MOUSEEVENTF_HWHEEL`
  as positive for a tilt *to the right*, which is already the boundary's ``+dx``.

**Never executed on Windows, and one trap worth naming.** `SendInput` returns the number
of events it *inserted into the input stream*. That is not the number that reached an
application: UIPI silently drops input aimed at a more-privileged window, and this project
has already shipped a Unicode injection bug where one application typed perfectly while
another received rows of `?` with nothing in any log. So a full return count is treated
here as "Windows accepted the events", never as "the pointer moved". A short count raises;
a dropped-after-acceptance event is undetectable from this side and only hardware testing
can find it. Microsoft says so itself: `SendInput` "fails when it is blocked by UIPI. Note
that neither GetLastError nor the return value will indicate the failure was caused by UIPI
blocking" (https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput),
and a zero return means "the input was already blocked by another thread". So a short count
is *not* a UIPI diagnosis, and the error message no longer claims it is.
"""

from __future__ import annotations

import ctypes
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from yazses.platform.windows.injector import (
    _INPUT,
    _MOUSEINPUT,
    INJECTED_TAG,
    _load_user32,
)
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
from yazses.pointer.subpixel import SubPixelAccumulator

log = logging.getLogger(__name__)

# WinAPI constants for the mouse half of SendInput (winuser.h). Values from Microsoft's
# MOUSEINPUT documentation; MOUSEEVENTF_ABSOLUTE and MOUSEEVENTF_VIRTUALDESK are
# deliberately absent because this backend reports no absolute motion.
INPUT_MOUSE = 0
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x1000

#: One wheel click, as `winuser.h` defines it. A scroll of 1.0 in the boundary's units is
#: one click, so the conversion is a multiplication by this and nothing more.
WHEEL_DELTA = 120

#: `SystemParametersInfo` actions that read the pointer-ballistics settings (winuser.h).
SPI_GETMOUSE = 0x0003
SPI_GETMOUSESPEED = 0x0070

#: `MOUSEINPUT.dx` / `.dy` are `LONG`, a signed 32-bit integer on every Windows ABI.
_INT32_MIN = -(2**31)
_INT32_MAX = 2**31 - 1

#: ``PointerButton`` -> (down flag, up flag).
_BUTTON_FLAGS: dict[PointerButton, tuple[int, int]] = {
    PointerButton.LEFT: (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
    PointerButton.RIGHT: (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
    PointerButton.MIDDLE: (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
}

#: What this backend honestly offers. See the module docstring for why absolute motion is
#: absent; `backend` is the short stable identifier the protocol asks for.
WINDOWS_POINTER_CAPABILITIES = PointerCapabilities(
    backend="sendinput",
    relative_motion=True,
    absolute_motion=False,
    buttons=frozenset(PointerButton),
    scroll_vertical=True,
    scroll_horizontal=True,
)


@dataclass(frozen=True)
class MouseEvent:
    """One `MOUSEINPUT` worth of field values, before any ctypes exists.

    ``mouse_data`` is **signed** here. The Win32 field is a `DWORD`, so
    :func:`pack_inputs` masks it to two's complement on the way in — keeping the sign
    readable at this layer is what lets a test assert "scrolling down sends a negative
    wheel delta" instead of asserting against ``0xFFFFFF88``.
    """

    flags: int
    dx: int = 0
    dy: int = 0
    mouse_data: int = 0


def _require_int32(**values: int) -> None:
    """Refuse a value a 32-bit `LONG`/`DWORD` field cannot hold.

    ctypes does not range-check an integer assigned to a structure field: on Windows a
    `c_long` simply wraps, so a finite but enormous delta would reach `SendInput` as a
    small or *negative* one and send the pointer the opposite way. `check_finite` at the
    sink edge cannot catch it — the value is finite — so the builders, which own the
    field values, refuse it. The caller sees a :class:`PointerBackendError`.
    """
    for name, value in values.items():
        if not _INT32_MIN <= value <= _INT32_MAX:
            raise ValueError(f"{name} {value} does not fit a 32-bit Win32 field")


def move_events(steps_x: int, steps_y: int) -> list[MouseEvent]:
    """Relative motion, in pixels. ``+x`` right and ``+y`` down, as Win32 already is.

    No event at all for ``(0, 0)``: the sub-pixel accumulator is still holding that
    motion and will emit it as soon as it reaches a whole pixel, so sending a zero-delta
    `MOUSEEVENTF_MOVE` would only wake every window's mouse-move handler for nothing.
    """
    if not steps_x and not steps_y:
        return []
    _require_int32(dx=steps_x, dy=steps_y)
    return [MouseEvent(flags=MOUSEEVENTF_MOVE, dx=steps_x, dy=steps_y)]


def button_events(button: PointerButton, *, down: bool) -> list[MouseEvent]:
    """The one event that presses or releases *button*."""
    press_flag, release_flag = _BUTTON_FLAGS[button]
    return [MouseEvent(flags=press_flag if down else release_flag)]


def scroll_events(notches_x: int, notches_y: int) -> list[MouseEvent]:
    """Scroll, in whole wheel clicks, in the boundary's signs: ``+y`` down, ``+x`` right.

    Vertical is negated because Win32's positive wheel delta means *forward, away from the
    user* — scrolling up. Horizontal is not, because Win32's positive tilt already means
    right. Both axes in one call produce two events, sent together.
    """
    events: list[MouseEvent] = []
    _require_int32(wheel=notches_y * WHEEL_DELTA, hwheel=notches_x * WHEEL_DELTA)
    if notches_y:
        events.append(
            MouseEvent(flags=MOUSEEVENTF_WHEEL, mouse_data=-notches_y * WHEEL_DELTA)
        )
    if notches_x:
        events.append(
            MouseEvent(flags=MOUSEEVENTF_HWHEEL, mouse_data=notches_x * WHEEL_DELTA)
        )
    return events


def _last_error() -> int:
    """Win32's per-library last error code, or 0 where the platform has no such thing.

    `ctypes.get_last_error` exists only on Windows. Reached through ``getattr`` so that the
    hermetic tests, which run on Linux, can exercise the short-count failure path and read
    its message instead of dying on an `AttributeError` inside the error handler — a
    failure path that fails is worse than no failure path.
    """
    getter = getattr(ctypes, "get_last_error", None)
    return int(getter()) if getter is not None else 0


def pack_inputs(events: list[MouseEvent]) -> Any:
    """Build the ctypes `INPUT[]` array `SendInput` takes.

    Every event carries the same ``dwExtraInfo`` stamp the keyboard injector uses, so any
    future low-level mouse hook can tell YazSes' own pointer events from the user's hand
    on the mouse — the self-capture problem the keyboard side already solved.
    """
    array = (_INPUT * len(events))()
    for index, event in enumerate(events):
        array[index].type = INPUT_MOUSE
        array[index].mi = _MOUSEINPUT(
            dx=event.dx,
            dy=event.dy,
            mouseData=event.mouse_data & 0xFFFFFFFF,
            dwFlags=event.flags,
            time=0,
            dwExtraInfo=INJECTED_TAG,
        )
    return array


@dataclass(frozen=True)
class MouseBallistics:
    """The user's pointer-speed settings, as `SystemParametersInfo` reports them.

    ``threshold1``, ``threshold2`` and ``acceleration`` are the three integers of
    `SPI_GETMOUSE`; ``speed`` is `SPI_GETMOUSESPEED` (1-20, 10 the documented default).
    """

    threshold1: int
    threshold2: int
    acceleration: int
    speed: int

    def scales_relative_motion(self) -> bool:
        """True when a relative `MOUSEEVENTF_MOVE` may not travel its nominal distance.

        Conservative on purpose: anything but "no acceleration, default speed" counts.
        Microsoft documents that acceleration multiplies relative motion; whether speed 10
        with acceleration off is exactly 1:1 is an inference, which is why the consumer of
        this is a log warning and not a correction.
        """
        return self.acceleration != 0 or self.speed != 10


def read_mouse_ballistics(user32: Any) -> MouseBallistics | None:
    """Read the pointer settings from *user32*, or ``None`` if either query fails."""
    params = (ctypes.c_int * 3)()
    speed = ctypes.c_int()
    if not user32.SystemParametersInfoW(SPI_GETMOUSE, 0, params, 0):
        return None
    if not user32.SystemParametersInfoW(SPI_GETMOUSESPEED, 0, ctypes.byref(speed), 0):
        return None
    return MouseBallistics(params[0], params[1], params[2], speed.value)


def ballistics_warning(b: MouseBallistics) -> str:
    """The one-line warning for settings that scale relative motion, else ``""``."""
    if not b.scales_relative_motion():
        return ""
    return (
        "Windows pointer: relative mouse motion is scaled by the user's pointer settings "
        f"(thresholds {b.threshold1}/{b.threshold2}, acceleration {b.acceleration}, "
        f"speed {b.speed}/20), so Head-Pointer may move the cursor a different distance "
        "than intended. Turn off 'Enhance pointer precision' and set the pointer speed to "
        "6/11 (Settings > Bluetooth & devices > Mouse) to remove the distortion."
    )


class WindowsMouseApi(Protocol):
    """The Win32 operations :class:`WindowsPointerSink` needs, and no others.

    No ``move_absolute``: this backend reports no absolute motion, so the sink refuses
    that call before any API is reached, and a method here would imply a capability the
    platform layer does not have.

    Not ``runtime_checkable`` on purpose — see the same note in
    `src/yazses/platform/macos/pointer.py`.
    """

    def move_relative(self, dx: float, dy: float) -> None: ...

    def press(self, button: PointerButton) -> None: ...

    def release(self, button: PointerButton) -> None: ...

    def scroll(self, dx: float, dy: float) -> None: ...

    def close(self) -> None: ...


class SendInputMouseApi:
    """Every `SendInput` call this backend makes.

    *send_input* replaces the real `user32.SendInput` in tests. Its signature is that
    function's: ``(count, inputs, size) -> inserted``. Injecting at exactly that level is
    deliberate — the struct packing, the flags and the two's-complement wheel delta are
    all inside the tested region, and a double can return a short count to prove the
    failure path.
    """

    def __init__(
        self,
        send_input: Any | None = None,
        ballistics: Callable[[], MouseBallistics | None] | None = None,
    ) -> None:
        self._send_input = send_input
        self._user32: Any = None
        # With an injected `send_input` the process is a test: do not reach for user32
        # to read settings unless the test supplied a reader too.
        self._ballistics = ballistics if ballistics is not None else (
            self._read_real_ballistics if send_input is None else None
        )
        self._ballistics_checked = False
        self._motion = SubPixelAccumulator()
        self._notches = SubPixelAccumulator()

    def move_relative(self, dx: float, dy: float) -> None:
        steps = self._motion.take(dx, dy)
        if steps != (0, 0):
            self._warn_once_about_ballistics()
        self._send(move_events(*steps))

    def press(self, button: PointerButton) -> None:
        self._send(button_events(button, down=True))

    def release(self, button: PointerButton) -> None:
        self._send(button_events(button, down=False))

    def scroll(self, dx: float, dy: float) -> None:
        steps_x, steps_y = self._notches.take(dx, dy)
        self._send(scroll_events(steps_x, steps_y))

    def close(self) -> None:
        """Nothing to release — `SendInput` holds no handle. Drop the residuals."""
        self._motion.reset()
        self._notches.reset()

    # -- internals --------------------------------------------------------- #

    def _get_user32(self) -> Any:
        """`user32`, loaded on first use and then kept — not rebuilt for every frame."""
        if self._user32 is None:
            self._user32 = _load_user32()
        return self._user32

    def _read_real_ballistics(self) -> MouseBallistics | None:
        return read_mouse_ballistics(self._get_user32())

    def _warn_once_about_ballistics(self) -> None:
        """Log, once, if the user's pointer settings will distort relative motion.

        Reading settings must never be the reason the pointer fails, so any error here is
        swallowed at debug level.
        """
        if self._ballistics_checked or self._ballistics is None:
            return
        self._ballistics_checked = True
        try:
            found = self._ballistics()
            message = ballistics_warning(found) if found is not None else ""
        except Exception:  # deliberately broad -- see the docstring
            log.debug("Windows pointer: could not read pointer settings", exc_info=True)
            return
        if message:
            log.warning(message)

    def _send(self, events: list[MouseEvent]) -> None:
        """Send *events* in one `SendInput` call, or raise.

        A short return count is the only failure this side can see. Its cause is *not*
        reliably UIPI — Microsoft says neither the return value nor `GetLastError`
        identifies a UIPI block — and the full count is not proof of anything beyond
        acceptance. See the module docstring.
        """
        if not events:
            return
        array = pack_inputs(events)
        send = self._send_input if self._send_input is not None else self._get_user32().SendInput
        inserted = send(len(array), array, ctypes.sizeof(_INPUT))
        if inserted != len(array):
            raise PointerBackendError(
                f"SendInput inserted {inserted}/{len(array)} mouse events "
                f"(lastError={_last_error()}). Windows documents a zero return as input "
                "already blocked by another thread (for example BlockInput or a secure "
                "desktop). It does not report UIPI blocking at all, so an elevated "
                "window can still drop events that were counted as inserted."
            )


class WindowsPointerSink:
    """`PointerSink` for Windows, over an injectable `SendInput` API.

    Pass *api* to test it; leave it out and the real :class:`SendInputMouseApi` is used,
    which loads `user32` on its first call and not before.
    """

    def __init__(self, api: WindowsMouseApi | None = None) -> None:
        self._api: WindowsMouseApi = api if api is not None else SendInputMouseApi()
        self._closed = False

    def capabilities(self) -> PointerCapabilities:
        return WINDOWS_POINTER_CAPABILITIES

    def move_relative(self, dx: float, dy: float) -> None:
        check_finite(dx=dx, dy=dy)
        require_relative(WINDOWS_POINTER_CAPABILITIES)
        self._guard_open()
        self._attempt(lambda: self._api.move_relative(dx, dy), "move the pointer")

    def move_absolute(self, x: float, y: float) -> None:
        """Always raises `PointerUnsupportedError` — see the module docstring.

        Defined rather than omitted: the protocol is ``runtime_checkable``, so a backend
        missing a method would stop being a `PointerSink` at all, and an unsupported
        operation must be an error the caller can read, not a missing attribute.
        """
        check_finite(x=x, y=y)
        require_absolute(WINDOWS_POINTER_CAPABILITIES)
        # Unreachable while the capability says False, and deliberately not a bare
        # `return`: someone who flips that flag without writing the normalised-coordinate
        # conversion must get an error, not a pointer that quietly refuses to move.
        raise PointerUnsupportedError(
            "absolute motion is not implemented for the Windows SendInput backend"
        )

    def click(self, button: PointerButton = PointerButton.LEFT) -> None:
        """Press then release *button* once.

        If the release fails after the press succeeded, the button is left down and this
        raises saying so, without retrying — same reasoning as the macOS backend: ADR-v2-146
        forbids repeating a command after a backend failure, and a second call down the
        same blocked path fails the same way.
        """
        require_button(WINDOWS_POINTER_CAPABILITIES, button)
        self._guard_open()
        self._attempt(lambda: self._api.press(button), f"press the {button.value} button")
        try:
            self._attempt(lambda: self._api.release(button), f"release the {button.value} button")
        except PointerError:
            log.error(
                "Windows pointer: the %s button was pressed but its release failed; it may "
                "still be held down.",
                button.value,
            )
            raise

    def scroll(self, dx: float, dy: float) -> None:
        check_finite(dx=dx, dy=dy)
        require_scroll(WINDOWS_POINTER_CAPABILITIES, dx, dy)
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
            raise PointerBackendError("Windows pointer sink is closed")

    def _attempt(self, action: Any, what: str) -> None:
        """Run one platform call, translating anything it raises into a pointer error.

        ctypes raises `OSError` and friends, and a caller holding a `PointerSink` can only
        be expected to catch `PointerError`. An untranslated one escaping into the daemon's
        frame loop is how a pointer failure becomes a crash.
        """
        try:
            action()
        except PointerError:
            raise
        except Exception as exc:  # deliberately broad -- see the docstring
            raise PointerBackendError(f"Windows pointer could not {what}: {exc}") from exc
