"""The vocabulary a pointer sink's behaviour is recorded in: ``PointerAction``.

This is *data*, not a sink. It lives in the package (and not in ``tests/``) for one reason:
the shared contract suite (``tests/pointer_contract.py``) compares what a backend did with
what the contract says it must do, and both sides have to speak the same value type. When
that type lived in ``tests/pointer_fake.py`` the suite could not be applied to a backend
written outside this repository without importing this repository's test internals.

Nothing here moves a pointer, opens a connection or imports beyond the standard library and
:mod:`yazses.pointer.base`. The recording *fake* sink still does not ship
(``tests/pointer_fake.py``): a sink that accepts every operation and moves nothing is the
silent no-op ADR-v2-146 forbids, and a vocabulary is not that.

A click is deliberately **two** actions, press then release, because "press and release
exactly once, in that order" is the contract and a single ``CLICK`` record could not tell a
correct backend from one that released without pressing.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from yazses.pointer.base import PointerButton

__all__ = ["PointerAction", "PointerActionKind"]


class PointerActionKind(str, Enum):
    """What a recorded pointer action is."""

    MOVE_RELATIVE = "move_relative"
    MOVE_ABSOLUTE = "move_absolute"
    BUTTON_PRESS = "button_press"
    BUTTON_RELEASE = "button_release"
    SCROLL = "scroll"
    CLOSE = "close"


@dataclass(frozen=True)
class PointerAction:
    """One thing a sink did, as a comparable value.

    ``x``/``y`` are the delta for :attr:`PointerActionKind.MOVE_RELATIVE` and
    :attr:`PointerActionKind.SCROLL`, the position for
    :attr:`PointerActionKind.MOVE_ABSOLUTE`, and zero for the button and close actions.

    Real backends record these in their test doubles so the shared contract suite can
    assert the same sequences against every platform.
    """

    kind: PointerActionKind
    x: float = 0.0
    y: float = 0.0
    button: PointerButton | None = None

    @classmethod
    def move_relative(cls, dx: float, dy: float) -> PointerAction:
        return cls(PointerActionKind.MOVE_RELATIVE, dx, dy)

    @classmethod
    def move_absolute(cls, x: float, y: float) -> PointerAction:
        return cls(PointerActionKind.MOVE_ABSOLUTE, x, y)

    @classmethod
    def press(cls, button: PointerButton) -> PointerAction:
        return cls(PointerActionKind.BUTTON_PRESS, button=button)

    @classmethod
    def release(cls, button: PointerButton) -> PointerAction:
        return cls(PointerActionKind.BUTTON_RELEASE, button=button)

    @classmethod
    def scroll(cls, dx: float, dy: float) -> PointerAction:
        return cls(PointerActionKind.SCROLL, dx, dy)

    @classmethod
    def close(cls) -> PointerAction:
        return cls(PointerActionKind.CLOSE)
