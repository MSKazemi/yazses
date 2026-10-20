"""The shared PointerSink contract — one suite, every backend (ADR-v2-146).

A pointer backend is not interesting on its own; what matters is that X11, the XDG
RemoteDesktop portal, macOS and Windows all behave *the same way* under Head-Pointer, so
a user who moves their head gets the same pointer wherever they are. Four backends with
four hand-written test files would be four dialects of the same contract, and the
differences would only show up on somebody's desktop.

So the behaviour lives here once, and every backend inherits it:

    from tests.pointer_contract import PointerSinkContract
    from tests.pointer_fake import PointerAction

    class TestX11PointerSink(PointerSinkContract):
        def make_sink(self):
            return X11PointerSink(run=self._recorder)      # a fake platform layer

        def recorded(self, sink):
            return self._recorder.actions                  # as PointerAction values

        def induce_failure(self, sink):
            self._recorder.raise_next(OSError("xdotool died"))

        def clear_failure(self, sink):
            self._recorder.raise_next(None)

pytest collects a class whose name starts with ``Test``; ``PointerSinkContract`` does
not, and this module is not named ``test_*.py``, so nothing here runs until a backend
subclasses it. That is the point — the suite is a library, not a test file.

The four hooks are all a backend must write. ``recorded()`` returns the platform calls
the backend actually made, translated into :class:`~tests.pointer_fake.PointerAction`
values; translating is the backend's job because only it knows that its native
``XTestFakeButtonEvent(1, True)`` is a left-button press. ``induce_failure`` /
``clear_failure`` exist because "a stale command is never repeated after backend
failure" is a promise in the ADR, and a promise nothing can make fail is not tested.

**Out-of-tree backends.** This module imports nothing from ``tests/``: the recorded-action
vocabulary is :mod:`yazses.pointer.actions`, which ships in the package. A backend written
outside this repository copies this one file next to its own tests (it needs ``pytest`` and
``yazses`` and nothing else) and writes the four hooks. ``tests/test_pointer_contract.py``
asserts the "imports nothing from tests/" property so it cannot quietly rot, and
``tests/test_pointer_contract_mutants.py`` proves the suite *fails* a backend that is wrong
in each of a dozen specific ways, rather than assuming a green run means a strong suite.

Tests here branch on ``capabilities()`` rather than assuming a full backend, and both
branches assert something: a backend that supports absolute motion is checked for exact
coordinates, one that does not is checked for an explicit
:class:`~yazses.pointer.base.PointerUnsupportedError`. ``tests/test_pointer_contract.py``
runs the suite against a full fake *and* two deliberately partial ones, so neither branch
can quietly rot into a no-op.
"""

from __future__ import annotations

import math
from collections.abc import Callable

import pytest

from yazses.pointer.actions import PointerAction, PointerActionKind
from yazses.pointer.base import (
    REQUIRED_BUTTONS,
    PointerButton,
    PointerCapabilities,
    PointerError,
    PointerSink,
    PointerUnsupportedError,
)


class PointerSinkContract:
    """Behaviour every ``PointerSink`` implementation must show. Subclass to apply."""

    # ------------------------------------------------------------------ hooks
    def make_sink(self) -> PointerSink:
        """Return a fresh sink that has not yet emitted anything."""
        raise NotImplementedError("a PointerSink contract subclass must supply make_sink()")

    def recorded(self, sink: PointerSink) -> list[PointerAction]:
        """Return, in order, the pointer actions *sink* actually performed."""
        raise NotImplementedError("a PointerSink contract subclass must supply recorded()")

    def induce_failure(self, sink: PointerSink) -> None:
        """Arrange for the following operations on *sink* to fail at the backend."""
        raise NotImplementedError(
            "a PointerSink contract subclass must supply induce_failure(); the ADR "
            "promises a failed action is never replayed, and that needs a failure"
        )

    def clear_failure(self, sink: PointerSink) -> None:
        """Undo :meth:`induce_failure` so the backend works again."""
        raise NotImplementedError(
            "a PointerSink contract subclass must supply clear_failure()"
        )

    # ------------------------------------------------------------ the contract
    def test_sink_satisfies_the_protocol(self) -> None:
        sink = self.make_sink()
        assert isinstance(sink, PointerSink)

    def test_a_fresh_sink_has_emitted_nothing(self) -> None:
        """No implicit motion loop, and nothing before the first call.

        A sink that emitted on construction would move the pointer the moment a feature
        was enabled — before consent on Wayland, and before any dwell decision anywhere.
        """
        sink = self.make_sink()
        assert self.recorded(sink) == []

    def test_capabilities_name_the_backend_and_do_not_change(self) -> None:
        sink = self.make_sink()
        caps = sink.capabilities()
        assert isinstance(caps, PointerCapabilities)
        assert caps.backend, "capabilities must carry a non-empty backend identifier"
        sink.move_relative(1.0, 1.0)
        assert sink.capabilities() == caps, "capabilities must be constant for a sink"

    def test_relative_motion_is_the_minimum_every_backend_offers(self) -> None:
        caps = self.make_sink().capabilities()
        assert caps.relative_motion, (
            "relative motion is the minimum requirement (spec-eye-pointer-output); a "
            "backend that cannot do it is not a pointer sink"
        )

    def test_every_backend_offers_left_and_right(self) -> None:
        caps = self.make_sink().capabilities()
        missing = sorted(b.value for b in REQUIRED_BUTTONS - caps.buttons)
        assert not missing, f"backend {caps.backend!r} is missing required buttons {missing}"

    def test_relative_motion_is_exact_and_ordered(self) -> None:
        sink = self.make_sink()
        sink.move_relative(3.0, -4.0)
        sink.move_relative(-1.5, 0.25)
        sink.move_relative(0.0, 2.0)
        assert self.recorded(sink) == [
            PointerAction.move_relative(3.0, -4.0),
            PointerAction.move_relative(-1.5, 0.25),
            PointerAction.move_relative(0.0, 2.0),
        ]

    def test_click_presses_then_releases_exactly_once(self) -> None:
        caps = self.make_sink().capabilities()
        for button in sorted(caps.buttons, key=lambda b: b.value):
            sink = self.make_sink()
            sink.click(button)
            assert self.recorded(sink) == [
                PointerAction.press(button),
                PointerAction.release(button),
            ], f"{button.value} click must be one press then one release"

    def test_click_defaults_to_the_left_button(self) -> None:
        sink = self.make_sink()
        sink.click()
        assert self.recorded(sink) == [
            PointerAction.press(PointerButton.LEFT),
            PointerAction.release(PointerButton.LEFT),
        ]

    def test_a_button_the_backend_lacks_is_an_explicit_error(self) -> None:
        sink = self.make_sink()
        caps = sink.capabilities()
        absent = sorted(set(PointerButton) - caps.buttons, key=lambda b: b.value)
        if not absent:
            # Nothing is missing, so the claim to check is the positive one: every
            # button the enum defines really works. This branch must still assert.
            for button in sorted(caps.buttons, key=lambda b: b.value):
                self.make_sink().click(button)
            assert caps.buttons == frozenset(PointerButton)
            return
        for button in absent:
            sink = self.make_sink()
            with pytest.raises(PointerUnsupportedError):
                sink.click(button)
            assert self.recorded(sink) == [], "a refused click must not half-happen"

    def test_absolute_motion_matches_capabilities(self) -> None:
        sink = self.make_sink()
        caps = sink.capabilities()
        if caps.absolute_motion:
            sink.move_absolute(120.0, 48.5)
            assert self.recorded(sink) == [PointerAction.move_absolute(120.0, 48.5)]
        else:
            with pytest.raises(PointerUnsupportedError):
                sink.move_absolute(120.0, 48.5)
            assert self.recorded(sink) == [], "unsupported absolute motion is not a no-op"

    def test_vertical_scroll_matches_capabilities(self) -> None:
        sink = self.make_sink()
        caps = sink.capabilities()
        if caps.scroll_vertical:
            sink.scroll(0.0, 3.0)
            assert self.recorded(sink) == [PointerAction.scroll(0.0, 3.0)]
        else:
            with pytest.raises(PointerUnsupportedError):
                sink.scroll(0.0, 3.0)
            assert self.recorded(sink) == []

    def test_horizontal_scroll_matches_capabilities(self) -> None:
        sink = self.make_sink()
        caps = sink.capabilities()
        if caps.scroll_horizontal:
            sink.scroll(2.0, 0.0)
            assert self.recorded(sink) == [PointerAction.scroll(2.0, 0.0)]
        else:
            with pytest.raises(PointerUnsupportedError):
                sink.scroll(2.0, 0.0)
            assert self.recorded(sink) == []

    def test_scroll_signs_are_passed_through_unchanged(self) -> None:
        """+dy is down, -dy is up, and the backend does not silently flip them.

        Any backend whose native axis runs the other way negates inside itself; a sign
        that changes at this boundary is what makes a head-controlled scroll fight the
        user.
        """
        caps = self.make_sink().capabilities()
        if not caps.scroll_vertical:
            pytest.skip(f"backend {caps.backend!r} has no vertical scroll axis")
        sink = self.make_sink()
        sink.scroll(0.0, 1.0)
        sink.scroll(0.0, -1.0)
        assert self.recorded(sink) == [
            PointerAction.scroll(0.0, 1.0),
            PointerAction.scroll(0.0, -1.0),
        ]

    def test_non_finite_values_are_refused_before_the_platform_sees_them(self) -> None:
        caps = self.make_sink().capabilities()
        for bad in (math.nan, math.inf, -math.inf):
            sink = self.make_sink()
            with pytest.raises(ValueError):
                sink.move_relative(bad, 0.0)
            with pytest.raises(ValueError):
                sink.move_relative(0.0, bad)
            assert self.recorded(sink) == []
            if caps.absolute_motion:
                sink = self.make_sink()
                with pytest.raises(ValueError):
                    sink.move_absolute(bad, 0.0)
                assert self.recorded(sink) == []
            if caps.scroll_vertical:
                sink = self.make_sink()
                with pytest.raises(ValueError):
                    sink.scroll(0.0, bad)
                assert self.recorded(sink) == []

    def test_close_is_idempotent(self) -> None:
        sink = self.make_sink()
        sink.close()
        sink.close()  # must not raise: cleanup runs twice in real code

    def test_operations_after_close_are_explicit(self) -> None:
        sink = self.make_sink()
        sink.move_relative(1.0, 1.0)
        sink.close()
        before = self.recorded(sink)
        with pytest.raises(PointerError):
            sink.move_relative(2.0, 2.0)
        with pytest.raises(PointerError):
            sink.click()
        assert self.recorded(sink) == before, "a closed sink must not keep emitting"

    def test_a_backend_failure_does_not_replay_the_previous_action(self) -> None:
        """The ADR's rule 4: a stale command is never repeated after a failure."""
        sink = self.make_sink()
        sink.move_relative(3.0, 4.0)
        before = self.recorded(sink)
        assert before == [PointerAction.move_relative(3.0, 4.0)]

        self.induce_failure(sink)
        with pytest.raises(PointerError):
            sink.move_relative(5.0, 6.0)
        after_failure = self.recorded(sink)
        assert after_failure[: len(before)] == before, "the failure rewrote history"
        assert PointerAction.move_relative(3.0, 4.0) not in after_failure[len(before):], (
            "the backend replayed the last good action after a failure"
        )

        self.clear_failure(sink)
        sink.move_relative(7.0, 8.0)
        recovered = self.recorded(sink)
        assert recovered[len(after_failure):] == [PointerAction.move_relative(7.0, 8.0)], (
            "recovery must emit the new action only — no catch-up, no replay"
        )

    # ------------------------------------------------- every operation, not just motion
    def _operations(self, sink: PointerSink) -> list[tuple[str, Callable[[], None]]]:
        """One callable per operation this backend claims, so a rule is checked on all of them.

        A failure test that only drives ``move_relative`` cannot see a backend that swallows
        errors in ``click`` or ``scroll`` alone -- a real shape, because each of those is its
        own code path with its own ``try``.
        """
        caps = sink.capabilities()
        ops: list[tuple[str, Callable[[], None]]] = []
        if caps.relative_motion:
            ops.append(("move_relative", lambda: sink.move_relative(2.0, 3.0)))
        if caps.absolute_motion:
            ops.append(("move_absolute", lambda: sink.move_absolute(10.0, 20.0)))
        if caps.supports_button(PointerButton.LEFT):
            ops.append(("click", lambda: sink.click(PointerButton.LEFT)))
        if caps.scroll_vertical:
            ops.append(("scroll", lambda: sink.scroll(0.0, 2.0)))
        assert ops, "a backend with no operation at all is not a pointer sink"
        return ops

    def test_every_operation_fails_loudly_and_records_nothing_when_the_backend_fails(self) -> None:
        names = [name for name, _ in self._operations(self.make_sink())]
        for index, name in enumerate(names):
            sink = self.make_sink()
            op = self._operations(sink)[index][1]
            before = self.recorded(sink)
            self.induce_failure(sink)
            with pytest.raises(PointerError):
                op()
            assert self.recorded(sink) == before, (
                f"{name}: a failed operation must not be recorded as having happened"
            )

    def test_every_operation_recovers_without_a_catch_up_burst(self) -> None:
        names = [name for name, _ in self._operations(self.make_sink())]
        for index, name in enumerate(names):
            sink = self.make_sink()
            ops = self._operations(sink)
            self.induce_failure(sink)
            for _ in range(3):
                with pytest.raises(PointerError):
                    ops[index][1]()
            self.clear_failure(sink)
            ops[index][1]()
            performed = self.recorded(sink)
            # One successful call, however many failed before it: a backend that queued the
            # failed calls and flushed them on recovery would emit four times that.
            fresh = self.make_sink()
            self._operations(fresh)[index][1]()
            assert performed == self.recorded(fresh), (
                f"{name}: recovery emitted {len(performed)} actions where one call emits "
                f"{len(self.recorded(fresh))} -- failed calls were queued and replayed"
            )

    def test_every_operation_after_close_is_an_explicit_error(self) -> None:
        names = [name for name, _ in self._operations(self.make_sink())]
        for index, name in enumerate(names):
            sink = self.make_sink()
            ops = self._operations(sink)
            sink.close()
            before = self.recorded(sink)
            with pytest.raises(PointerError):
                ops[index][1]()
            assert self.recorded(sink) == before, (
                f"{name}: a closed sink returned success and kept emitting"
            )

    def test_close_never_raises_even_while_the_backend_is_failing(self) -> None:
        """Cleanup runs because something broke; a second error on top of it buries the first."""
        sink = self.make_sink()
        self.induce_failure(sink)
        sink.close()
        sink.close()

    def test_close_reaches_the_platform_at_most_once(self) -> None:
        sink = self.make_sink()
        sink.move_relative(1.0, 1.0)
        sink.close()
        sink.close()
        sink.close()
        closes = [a for a in self.recorded(sink) if a.kind is PointerActionKind.CLOSE]
        assert len(closes) <= 1, "close() released the platform handle more than once"

    def test_close_leaves_no_button_pressed(self) -> None:
        """A click is atomic in this protocol, so nothing may be held at any point we can see."""
        sink = self.make_sink()
        sink.click()
        sink.close()
        held: dict[PointerButton, int] = {}
        for action in self.recorded(sink):
            if action.button is None:
                continue
            if action.kind is PointerActionKind.BUTTON_PRESS:
                held[action.button] = held.get(action.button, 0) + 1
            elif action.kind is PointerActionKind.BUTTON_RELEASE:
                held[action.button] = held.get(action.button, 0) - 1
        assert all(count == 0 for count in held.values()), f"buttons still held: {held}"

    def test_capabilities_are_still_answerable_after_close(self) -> None:
        sink = self.make_sink()
        caps = sink.capabilities()
        sink.close()
        assert sink.capabilities() == caps

    def test_operations_of_different_kinds_arrive_in_the_order_they_were_called(self) -> None:
        """No batching or reordering across kinds: the click lands where the move left it."""
        caps = self.make_sink().capabilities()
        sink = self.make_sink()
        expected: list[PointerAction] = []
        sink.move_relative(5.0, 0.0)
        expected.append(PointerAction.move_relative(5.0, 0.0))
        sink.click(PointerButton.LEFT)
        expected += [PointerAction.press(PointerButton.LEFT), PointerAction.release(PointerButton.LEFT)]
        if caps.scroll_vertical:
            sink.scroll(0.0, 1.0)
            expected.append(PointerAction.scroll(0.0, 1.0))
        sink.move_relative(0.0, -5.0)
        expected.append(PointerAction.move_relative(0.0, -5.0))
        assert self.recorded(sink) == expected

    def test_a_refused_call_does_not_disturb_the_ones_around_it(self) -> None:
        """An unsupported or invalid call between two good ones changes nothing recorded."""
        sink = self.make_sink()
        sink.move_relative(1.0, 1.0)
        with pytest.raises(ValueError):
            sink.move_relative(math.nan, 0.0)
        # The docstring promises "unsupported" too, so drive every unsupported operation
        # this backend has between the same two good calls (none, on a full backend).
        for _, refused in self._unsupported_operations(sink):
            with pytest.raises(PointerUnsupportedError):
                refused()
        sink.move_relative(2.0, 2.0)
        assert self.recorded(sink) == [
            PointerAction.move_relative(1.0, 1.0),
            PointerAction.move_relative(2.0, 2.0),
        ]

    # ------------------------------------- coordinates: no clamping, no re-origin, no cap
    #: A desktop with a 1920x1080 primary, one display to its left and one 4K display to its
    #: lower right. On macOS and Windows the primary's top-left is the origin, so the left
    #: display's x and anything above the primary's y are *negative* -- ADR-v2-149 requires
    #: those to be reachable "if the OS exposes them". The points are chosen so that every
    #: plausible guessed bound (zero, the primary's width or height) moves at least one.
    MULTI_MONITOR_POINTS: tuple[tuple[float, float], ...] = (
        (-1920.0, 0.0),  # the far left edge of the left-hand display
        (-640.5, -1080.0),  # above and left of the primary, with a fraction
        (0.0, -0.5),  # half a unit above the primary's top edge
        (5759.0, 3239.75),  # inside the 4K display beyond the primary's lower right
    )

    def test_absolute_motion_reaches_negative_and_off_primary_coordinates_unchanged(self) -> None:
        """The sink does not clamp, wrap or re-origin a position (spec-eye-pointer-output, Bounds).

        A display left of or above the primary has negative coordinates in the canonical
        desktop space (ADR-v2-149). A sink that clamped to ``>= 0`` or to the primary display
        would make every secondary monitor unreachable, and it cannot know the topology: it
        is deliberately dumb (ADR-v2-146). What lies off every display is the platform's to
        settle -- the OS keeps the cursor on the desktop -- and choosing a sane target is the
        caller's job, with :mod:`yazses.gaze.topology`.
        """
        sink = self.make_sink()
        caps = sink.capabilities()
        if not caps.absolute_motion:
            for x, y in self.MULTI_MONITOR_POINTS:
                with pytest.raises(PointerUnsupportedError):
                    sink.move_absolute(x, y)
            assert self.recorded(sink) == [], "unsupported absolute motion is not a no-op"
            return
        for x, y in self.MULTI_MONITOR_POINTS:
            sink.move_absolute(x, y)
        assert self.recorded(sink) == [
            PointerAction.move_absolute(x, y) for x, y in self.MULTI_MONITOR_POINTS
        ], "absolute positions must reach the platform exactly as given -- no clamping"

    def test_large_relative_motion_is_neither_capped_nor_split(self) -> None:
        """Speed limits live above the sink, in the feature, not in the backend.

        Head-Pointer caps its own velocity (``yazses.headpointer.pointer``) and a voice
        command may legitimately cross two monitors in one step. A sink that also capped,
        or split one call into several, would make the same intent travel a different
        distance per platform -- and a split motion is two effects for one call.
        """
        sink = self.make_sink()
        deltas = [(-3840.0, 2160.0), (2500.0, -1440.25), (-1.0e4, 0.0)]
        for dx, dy in deltas:
            sink.move_relative(dx, dy)
        assert self.recorded(sink) == [PointerAction.move_relative(dx, dy) for dx, dy in deltas]

    # ------------------------------------- unsupported is permanent, whatever the state
    def _unsupported_operations(self, sink: PointerSink) -> list[tuple[str, Callable[[], None]]]:
        """One callable per operation this backend's capabilities say it does **not** have."""
        caps = sink.capabilities()
        ops: list[tuple[str, Callable[[], None]]] = []
        if not caps.absolute_motion:
            ops.append(("move_absolute", lambda: sink.move_absolute(10.0, 20.0)))
        for button in sorted(set(PointerButton) - caps.buttons, key=lambda b: b.value):
            ops.append((f"click({button.value})", lambda b=button: sink.click(b)))
        if not caps.scroll_vertical:
            ops.append(("scroll(vertical)", lambda: sink.scroll(0.0, 1.0)))
        if not caps.scroll_horizontal:
            ops.append(("scroll(horizontal)", lambda: sink.scroll(1.0, 0.0)))
        return ops

    def test_an_unsupported_operation_stays_unsupported_while_failing_and_after_close(self) -> None:
        """The answer to "can this backend do X?" does not change with the backend's health.

        ``PointerUnsupportedError`` means *permanent for this backend* and
        ``PointerBackendError`` *maybe transient*; that difference is why the two exist
        (:mod:`yazses.pointer.base`). A backend that checks "am I up?" before "can I do this
        at all?" reports a missing capability as a passing outage, and its caller retries
        something that will never work, or tells the user to wait for it.
        """
        probe = self.make_sink()
        caps = probe.capabilities()
        names = [name for name, _ in self._unsupported_operations(probe)]
        if not names:
            # A backend with every capability: the claim to check is that it says so.
            assert caps.absolute_motion and caps.scroll_vertical and caps.scroll_horizontal
            assert caps.buttons == frozenset(PointerButton)
            return
        for index, name in enumerate(names):
            failing = self.make_sink()
            self.induce_failure(failing)
            before = self.recorded(failing)
            with pytest.raises(PointerUnsupportedError):
                self._unsupported_operations(failing)[index][1]()
            assert self.recorded(failing) == before, f"{name}: refused, yet something happened"
            self.clear_failure(failing)

            closed = self.make_sink()
            closed.close()
            before = self.recorded(closed)
            with pytest.raises(PointerUnsupportedError):
                self._unsupported_operations(closed)[index][1]()
            assert self.recorded(closed) == before, f"{name}: a closed sink emitted"
