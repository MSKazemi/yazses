"""Pointer output — one cross-platform seam for moving, clicking and scrolling.

ADR-v2-146 and `design/specs/eye-pointer-output.md`. Head-Pointer, the voice mouse grid
and future gaze-assisted control all need to drive a pointer; none of them should know
which display server is listening. :mod:`yazses.pointer.base` is that boundary — a
``PointerSink`` protocol, a capability record and explicit errors, with no camera, gaze
or head-pose concept in it and nothing imported beyond the standard library.

Platform backends land beside it one at a time (X11, the existing XDG RemoteDesktop
portal session, macOS, Windows) and are chosen through the platform factory, so enabling
a pointer feature never drags four backends into the process.

No fake ships here. The deterministic recording sink that keeps feature tests hermetic
lives in the test tree, as ``tests/pointer_fake.py``: a sink that accepts every
operation and moves no pointer is exactly the silent no-op this ADR forbids, and one in
the wheel could be selected by accident. Every implementation, fake or real, is held to
the same shared contract suite in ``tests/pointer_contract.py``.
"""

from yazses.pointer.base import (
    REQUIRED_BUTTONS,
    PointerBackendError,
    PointerButton,
    PointerCapabilities,
    PointerError,
    PointerSink,
    PointerUnsupportedError,
)

__all__ = [
    "REQUIRED_BUTTONS",
    "PointerBackendError",
    "PointerButton",
    "PointerCapabilities",
    "PointerError",
    "PointerSink",
    "PointerUnsupportedError",
]
