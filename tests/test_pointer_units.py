"""What one pointer unit is, per backend -- declared, pinned, and not silently converted
(EYE-DISPLAY-001, #415).

The pointer boundary (ADR-v2-146) used to claim that ``move_relative`` takes "logical
desktop pointer units, already scaled for HiDPI by the compositor/server". That is true of
macOS and false of X11 (whose coordinates have no scale factor) and of Windows (whose
relative motion is mouse counts run through the pointer-speed setting). Head-Pointer's
speed caps are "units per second", so the sentence matters: the same cap crosses a
1920-unit desktop twice as fast as a 3840-unit one.

These tests do not claim to *measure* any platform -- no Mac, no Windows PC, no scaled
Wayland session was available, and the module docs say so. They pin what each backend
*declares*, and that the sinks pass a delta through untouched, so the declaration cannot
drift away from the behaviour without a test failing.
"""
from __future__ import annotations

import inspect

import pytest

import yazses.pointer.base as pointer_base
from yazses.inject.portal import PORTAL_POINTER_CAPABILITIES
from yazses.platform.linux.pointer_x11 import X11_CAPABILITIES, X11PointerSink
from yazses.platform.macos.pointer import MACOS_POINTER_CAPABILITIES, MacosPointerSink
from yazses.platform.windows.pointer import (
    WINDOWS_POINTER_CAPABILITIES,
    SendInputMouseApi,
    WindowsPointerSink,
)
from yazses.pointer.base import MotionUnit, PointerCapabilities

DECLARED = {
    "x11": (X11_CAPABILITIES, MotionUnit.FRAMEBUFFER_PIXEL),
    "quartz": (MACOS_POINTER_CAPABILITIES, MotionUnit.LOGICAL_POINT),
    "sendinput": (WINDOWS_POINTER_CAPABILITIES, MotionUnit.DEVICE_COUNT),
    "portal": (PORTAL_POINTER_CAPABILITIES, MotionUnit.COMPOSITOR_LOGICAL),
}


@pytest.mark.parametrize("name", sorted(DECLARED))
def test_every_shipped_backend_declares_its_unit(name: str) -> None:
    caps, unit = DECLARED[name]
    assert caps.backend == name
    assert caps.motion_unit is unit
    assert caps.motion_unit is not MotionUnit.UNSPECIFIED


def test_an_undeclared_backend_is_visibly_undeclared_not_assumed_logical() -> None:
    assert PointerCapabilities(backend="new").motion_unit is MotionUnit.UNSPECIFIED


def test_the_boundary_documentation_names_every_declared_unit() -> None:
    """The table in the module docstring is the thing a feature author reads."""
    doc = inspect.getdoc(pointer_base) or ""
    for unit in MotionUnit:
        if unit is MotionUnit.UNSPECIFIED:
            continue
        assert f"MotionUnit.{unit.name}" in doc, f"{unit.name} is missing from the unit table"
    for backend in DECLARED:
        assert f"``{backend}``" in doc


def test_the_old_blanket_claim_is_gone() -> None:
    doc = inspect.getdoc(pointer_base) or ""
    assert "already scaled for HiDPI by the compositor/server" not in doc


class _XConn:
    def __init__(self) -> None:
        self.moves: list[tuple[str, float, float]] = []

    def motion_relative(self, dx, dy):
        self.moves.append(("rel", dx, dy))

    def motion_absolute(self, x, y):
        self.moves.append(("abs", x, y))

    def button(self, code, press):
        pass

    def sync(self):
        pass

    def close(self):
        pass


def test_x11_passes_a_delta_through_with_no_hidpi_factor() -> None:
    conn = _XConn()
    X11PointerSink(conn).move_relative(100.0, -40.0)
    assert conn.moves == [("rel", 100.0, -40.0)]


def test_x11_absolute_is_in_framebuffer_coordinates_so_the_origin_is_not_the_primary() -> None:
    """A point on a primary at +1920+0 is x=1920 + local, not local. Nothing shifts it."""
    conn = _XConn()
    X11PointerSink(conn).move_absolute(1920.0 + 10.0, 5.0)
    assert conn.moves == [("abs", 1930.0, 5.0)]


class _MacApi:
    def __init__(self) -> None:
        self.calls: list[tuple[float, float]] = []

    def move_relative(self, dx, dy):
        self.calls.append((dx, dy))

    def move_absolute(self, x, y):
        pass

    def press(self, button):
        pass

    def release(self, button):
        pass

    def scroll(self, dx, dy):
        pass

    def close(self):
        pass


def test_macos_passes_a_delta_through_in_points_without_a_retina_factor() -> None:
    api = _MacApi()
    MacosPointerSink(api).move_relative(30.0, 12.0)
    assert api.calls == [(30.0, 12.0)]


def test_windows_sends_whole_counts_with_no_dpi_or_speed_conversion_of_its_own() -> None:
    sent: list[list[tuple[int, int, int]]] = []

    def send(count, array, _size):
        sent.append([(array[i].mi.dx, array[i].mi.dy, array[i].mi.dwFlags) for i in range(count)])
        return count

    WindowsPointerSink(SendInputMouseApi(send_input=send)).move_relative(7.0, -3.0)
    assert sent == [[(7, -3, 0x0001)]]
