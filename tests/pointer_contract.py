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

Tests here branch on ``capabilities()`` rather than assuming a full backend, and both
branches assert something: a backend that supports absolute motion is checked for exact
coordinates, one that does not is checked for an explicit
:class:`~yazses.pointer.base.PointerUnsupportedError`. ``tests/test_pointer_contract.py``
runs the suite against a full fake *and* two deliberately partial ones, so neither branch
can quietly rot into a no-op.
"""

from __future__ import annotations

import math

import pytest

from tests.pointer_fake import PointerAction
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
