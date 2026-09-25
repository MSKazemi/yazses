"""A deterministic, in-memory ``PointerSink`` and the action vocabulary it records.

Test infrastructure, and it lives in the test tree on purpose. It implements
:mod:`yazses.pointer.base` completely and is the reference every backend is measured
against, but nothing in ``src/`` consumes it and nothing should: a sink that accepts
every operation and moves no pointer is precisely the silent no-op ADR-v2-146 forbids,
and shipping one in the wheel is an invitation to select it by accident.

It moves nothing, touches no platform, and writes every operation it is given into a
list. Two jobs follow from that.

**It keeps feature tests hermetic.** Head-Pointer, the voice mouse grid and anything else
that produces pointer intent can be tested end to end against a fake sink, asserting on
exact deltas and click ordering, with no display server, no permissions prompt and no
pointer skidding across the developer's screen.

**It is the shape real backends are measured against.** The shared contract suite in
``tests/pointer_contract.py`` runs against this fake first; each platform backend then
supplies its own recorder that emits the same :class:`PointerAction` values and inherits
the identical assertions. A behaviour the fake has and a backend does not is a bug in the
backend, and the suite is where that is found.

The fake models the contract rather than flattering it: unsupported operations raise,
non-finite values raise, a click records a press *and* a release, use after
:meth:`FakePointerSink.close` raises, and :meth:`FakePointerSink.fail_with` makes the
next operations fail the way a platform does — so a caller that would replay a stale
command is caught here rather than on a user's desktop.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from yazses.pointer.base import (
    PointerBackendError,
    PointerButton,
    PointerCapabilities,
    PointerError,
    check_finite,
    require_absolute,
    require_button,
    require_relative,
    require_scroll,
)


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
    A click is deliberately *two* actions — press then release — because "press and
    release exactly once, in that order" is the contract, and a single ``CLICK`` record
    could not tell a correct backend from one that released without pressing.

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


#: What an unrestricted fake can do: everything the protocol defines. Tests that need a
#: partial backend — no absolute motion, two buttons, no horizontal axis — pass their own
#: :class:`~yazses.pointer.base.PointerCapabilities` instead, which is how the contract
#: suite checks that "unsupported" is reported honestly.
FULL_CAPABILITIES = PointerCapabilities(
    backend="fake",
    relative_motion=True,
    absolute_motion=True,
    buttons=frozenset(PointerButton),
    scroll_vertical=True,
    scroll_horizontal=True,
)


class FakePointerSink:
    """A :class:`~yazses.pointer.base.PointerSink` that records instead of moving.

    ``sink.actions`` is the ordered list of everything it was asked to do and did. An
    operation that raised is not in it: the contract says a failed action does not
    happen, and a recorder that logged attempts would let a backend "succeed" at
    something the user never saw.
    """

    def __init__(self, capabilities: PointerCapabilities = FULL_CAPABILITIES) -> None:
        self._caps = capabilities
        self._actions: list[PointerAction] = []
        self._closed = False
        self._failure: PointerError | None = None

    # -- inspection -------------------------------------------------------- #

    @property
    def actions(self) -> list[PointerAction]:
        """Everything this sink did, oldest first. A copy: callers cannot rewrite it."""
        return list(self._actions)

    @property
    def closed(self) -> bool:
        return self._closed

    def clear(self) -> None:
        """Forget the recorded actions, keeping capabilities and closed/failure state."""
        self._actions.clear()

    # -- failure injection ------------------------------------------------- #

    def fail_with(self, error: PointerError | None = None) -> None:
        """Make every following operation fail the way a dead backend would.

        The failure persists until :meth:`clear_failure`, because a display server does
        not come back for the next call either. Pass a specific error to model one.
        """
        self._failure = error or PointerBackendError("fake backend failure")

    def clear_failure(self) -> None:
        """Stop failing; the sink works again from the next call."""
        self._failure = None

    # -- the protocol ------------------------------------------------------ #

    def capabilities(self) -> PointerCapabilities:
        return self._caps

    def move_relative(self, dx: float, dy: float) -> None:
        check_finite(dx=dx, dy=dy)
        require_relative(self._caps)
        self._emit(PointerAction.move_relative(dx, dy))

    def move_absolute(self, x: float, y: float) -> None:
        check_finite(x=x, y=y)
        require_absolute(self._caps)
        self._emit(PointerAction.move_absolute(x, y))

    def click(self, button: PointerButton = PointerButton.LEFT) -> None:
        require_button(self._caps, button)
        self._emit(PointerAction.press(button), PointerAction.release(button))

    def scroll(self, dx: float, dy: float) -> None:
        check_finite(dx=dx, dy=dy)
        require_scroll(self._caps, dx, dy)
        self._emit(PointerAction.scroll(dx, dy))

    def close(self) -> None:
        """Close the sink. Idempotent, and it records the *first* close only.

        Closing does not raise even mid-failure: a caller cleaning up after an error
        must be able to let go of a backend that is already gone.
        """
        if self._closed:
            return
        self._closed = True
        self._actions.append(PointerAction.close())

    # -- internals --------------------------------------------------------- #

    def _emit(self, *actions: PointerAction) -> None:
        """Guard, then record. Nothing is recorded unless every guard passed."""
        if self._closed:
            raise PointerBackendError("pointer sink is closed")
        if self._failure is not None:
            raise self._failure
        self._actions.extend(actions)
