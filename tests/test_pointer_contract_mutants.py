"""The shared PointerSink contract must FAIL a backend that is wrong -- proven, not assumed.

A contract suite that every backend passes proves nothing until something that *should* fail
it does. ``tests/pointer_contract.py`` is the only thing standing between "a backend that
looks right in its own recorder" and a user's desktop, so this file builds deliberately wrong
sinks ("mutants"), runs the **whole** suite against each, and requires a red result from the
test that is supposed to notice. Each mutant is a mistake real backend code makes:

* swallows a backend error (a ``try/except`` that logs and carries on), in one operation or all;
* reorders press and release, or drops the release;
* holds the last event back in a buffer, so the final move never lands;
* reports success after ``close()``;
* closes twice, raises from ``close()``, or raises from it while the backend is failing;
* repeats the last good action after a failure, or queues failed calls and flushes them later;
* lets NaN reach the platform, or answers an unsupported operation with a silent no-op;
* flips a scroll sign, or answers ``click()`` with the wrong default button;
* changes its capabilities between calls, or moves the pointer while being constructed;
* clamps an absolute position to zero or to the primary display, or caps or splits a large
  relative move -- each of which strands a secondary monitor or a deliberate long move;
* reports a capability it lacks as a passing outage while failing, or as "closed" after close.

``test_the_unmutated_reference_passes_everything`` is the control: without it, a harness that
failed every sink would make every mutant look caught.

The harness calls each ``test_*`` method of the contract class directly. That keeps the
mutants out of pytest's own collection (a deliberately failing test class would turn the
suite red) and gives a precise answer to "which contract test caught it?".
"""

from __future__ import annotations

import pytest

from tests.pointer_contract import PointerSinkContract
from tests.pointer_fake import FULL_CAPABILITIES, FakePointerSink
from yazses.pointer.actions import PointerAction
from yazses.pointer.base import (
    PointerBackendError,
    PointerButton,
    PointerCapabilities,
    PointerError,
    PointerSink,
    PointerUnsupportedError,
    check_finite,
    require_scroll,
)

#: Left and right only, vertical scroll only: lets the "unsupported" mutants have something to
#: be unsupported about.
PARTIAL_CAPABILITIES = PointerCapabilities(
    backend="fake-partial",
    relative_motion=True,
    absolute_motion=False,
    buttons=frozenset({PointerButton.LEFT, PointerButton.RIGHT}),
    scroll_vertical=True,
    scroll_horizontal=False,
)


# --------------------------------------------------------------------------- #
# The harness
# --------------------------------------------------------------------------- #
def contract_for(factory):  # type: ignore[no-untyped-def]
    """A ``PointerSinkContract`` subclass whose sink comes from ``factory()``."""

    class _Bound(PointerSinkContract):
        def make_sink(self) -> PointerSink:
            return factory()  # type: ignore[no-any-return]

        def recorded(self, sink: PointerSink) -> list[PointerAction]:
            return sink.actions  # type: ignore[attr-defined,no-any-return]

        def induce_failure(self, sink: PointerSink) -> None:
            sink.fail_with()  # type: ignore[attr-defined]

        def clear_failure(self, sink: PointerSink) -> None:
            sink.clear_failure()  # type: ignore[attr-defined]

    return _Bound


def run_contract(factory) -> dict[str, BaseException]:  # type: ignore[no-untyped-def]
    """Run every contract test against ``factory``; return ``{test name: why it failed}``."""
    bound = contract_for(factory)
    failures: dict[str, BaseException] = {}
    names = sorted(n for n in dir(bound) if n.startswith("test_"))
    assert len(names) >= 20, "the contract suite shrank or was not found"
    for name in names:
        try:
            getattr(bound(), name)()
        except pytest.skip.Exception:
            continue
        except (Exception, pytest.fail.Exception) as exc:  # noqa: BLE001 - recording, not hiding
            failures[name] = exc
    return failures


def test_the_unmutated_reference_passes_everything() -> None:
    """The control. If this fails the harness is broken and every mutant is 'caught' for free."""
    for caps in (FULL_CAPABILITIES, PARTIAL_CAPABILITIES):
        assert run_contract(lambda caps=caps: FakePointerSink(caps)) == {}


# --------------------------------------------------------------------------- #
# The mutants
# --------------------------------------------------------------------------- #
class SwallowsErrorsInClick(FakePointerSink):
    """``click`` logs the backend error and returns, as if it worked."""

    def click(self, button: PointerButton = PointerButton.LEFT) -> None:
        try:
            super().click(button)
        except PointerBackendError:
            return


class SwallowsErrorsInMotion(FakePointerSink):
    def move_relative(self, dx: float, dy: float) -> None:
        try:
            super().move_relative(dx, dy)
        except PointerBackendError:
            return


class SwallowsErrorsInScroll(FakePointerSink):
    def scroll(self, dx: float, dy: float) -> None:
        try:
            super().scroll(dx, dy)
        except PointerBackendError:
            return


class ReleasesBeforePress(FakePointerSink):
    def click(self, button: PointerButton = PointerButton.LEFT) -> None:
        self._emit(PointerAction.release(button), PointerAction.press(button))


class NeverReleases(FakePointerSink):
    """The last event of a click is dropped: the button stays down."""

    def click(self, button: PointerButton = PointerButton.LEFT) -> None:
        super().click(button)
        self._actions.pop()


class HoldsTheLastMoveBack(FakePointerSink):
    """A one-slot buffer: each move is emitted when the *next* one arrives."""

    def __init__(self, capabilities: PointerCapabilities = FULL_CAPABILITIES) -> None:
        super().__init__(capabilities)
        self._held: PointerAction | None = None

    def move_relative(self, dx: float, dy: float) -> None:
        check_finite(dx=dx, dy=dy)
        if self._held is not None:
            self._emit(self._held)
        self._held = PointerAction.move_relative(dx, dy)


class ScrollIgnoresClose(FakePointerSink):
    """Only ``scroll`` forgot to check whether the sink was closed."""

    def scroll(self, dx: float, dy: float) -> None:
        check_finite(dx=dx, dy=dy)
        require_scroll(self._caps, dx, dy)
        self._actions.append(PointerAction.scroll(dx, dy))


class ClickIgnoresClose(FakePointerSink):
    def click(self, button: PointerButton = PointerButton.LEFT) -> None:
        self._actions.extend([PointerAction.press(button), PointerAction.release(button)])


class MoveIgnoresClose(FakePointerSink):
    def move_relative(self, dx: float, dy: float) -> None:
        check_finite(dx=dx, dy=dy)
        self._actions.append(PointerAction.move_relative(dx, dy))


class ClosesTwice(FakePointerSink):
    """Not idempotent: every ``close()`` releases the platform handle again."""

    def close(self) -> None:
        self._closed = True
        self._actions.append(PointerAction.close())


class RaisesOnSecondClose(FakePointerSink):
    def close(self) -> None:
        if self._closed:
            raise PointerBackendError("already closed")
        super().close()


class RaisesFromCloseWhileFailing(FakePointerSink):
    """Cleanup after an error throws a second error on top of the first."""

    def close(self) -> None:
        if self._failure is not None:
            raise self._failure
        super().close()


class ReplaysTheLastActionOnFailure(FakePointerSink):
    """The ADR's rule 4 broken in the most direct way: the failed call repeats the last good one."""

    def move_relative(self, dx: float, dy: float) -> None:
        try:
            super().move_relative(dx, dy)
        except PointerError:
            if self._actions:
                self._actions.append(self._actions[-1])
            raise


class QueuesFailedCallsAndFlushesLater(FakePointerSink):
    """Failed moves are kept and delivered with the next one that works."""

    def __init__(self, capabilities: PointerCapabilities = FULL_CAPABILITIES) -> None:
        super().__init__(capabilities)
        self._backlog: list[PointerAction] = []

    def move_relative(self, dx: float, dy: float) -> None:
        try:
            self._emit(*self._backlog, PointerAction.move_relative(dx, dy))
            self._backlog.clear()
        except PointerError:
            self._backlog.append(PointerAction.move_relative(dx, dy))
            raise


class LogsAttemptsNotEffects(FakePointerSink):
    """The recorder notes a click before the backend refuses it."""

    def click(self, button: PointerButton = PointerButton.LEFT) -> None:
        self._actions.append(PointerAction.press(button))
        try:
            super().click(button)
        except PointerError:
            self._actions.append(PointerAction.release(button))
            raise
        else:
            self._actions[-2:] = [PointerAction.press(button), PointerAction.release(button)]


class LetsNaNThrough(FakePointerSink):
    def move_relative(self, dx: float, dy: float) -> None:
        self._emit(PointerAction.move_relative(dx, dy))


class SilentNoOpForAbsolute(FakePointerSink):
    """Does not support absolute motion and says nothing about it."""

    def move_absolute(self, x: float, y: float) -> None:
        return None


class SilentNoOpForMissingButton(FakePointerSink):
    def click(self, button: PointerButton = PointerButton.LEFT) -> None:
        if button not in self._caps.buttons:
            return
        super().click(button)


class SilentNoOpForHorizontalScroll(FakePointerSink):
    def scroll(self, dx: float, dy: float) -> None:
        if dx and not self._caps.scroll_horizontal:
            dx = 0.0
        super().scroll(dx, dy)


class FlipsTheScrollSign(FakePointerSink):
    def scroll(self, dx: float, dy: float) -> None:
        super().scroll(dx, -dy)


class SwapsAxes(FakePointerSink):
    def move_relative(self, dx: float, dy: float) -> None:
        super().move_relative(dy, dx)


class DefaultButtonIsRight(FakePointerSink):
    def click(self, button: PointerButton = PointerButton.RIGHT) -> None:
        super().click(button)


class TruncatesDeltasToIntegers(FakePointerSink):
    """Sub-unit motion lost at the sink: 0.25 becomes 0."""

    def move_relative(self, dx: float, dy: float) -> None:
        check_finite(dx=dx, dy=dy)
        self._emit(PointerAction.move_relative(float(int(dx)), float(int(dy))))


class CapabilitiesDrift(FakePointerSink):
    """After the first operation the sink starts claiming it cannot scroll."""

    def capabilities(self) -> PointerCapabilities:
        caps = super().capabilities()
        if self._actions:
            return PointerCapabilities(
                backend=caps.backend,
                relative_motion=caps.relative_motion,
                absolute_motion=caps.absolute_motion,
                buttons=caps.buttons,
                scroll_vertical=False,
                scroll_horizontal=False,
            )
        return caps


class CapabilitiesVanishAfterClose(FakePointerSink):
    def capabilities(self) -> PointerCapabilities:
        if self._closed:
            return PointerCapabilities(backend="closed")
        return super().capabilities()


class MovesOnConstruction(FakePointerSink):
    """Enabling the feature jiggles the pointer: motion before anyone asked for any."""

    def __init__(self, capabilities: PointerCapabilities = FULL_CAPABILITIES) -> None:
        super().__init__(capabilities)
        self._actions.append(PointerAction.move_relative(0.0, 0.0))


class FailureLatchesForever(FakePointerSink):
    """A transient failure that is never forgotten: the backend stays dead after recovery."""

    def clear_failure(self) -> None:
        return None


class ClampsAbsoluteToNonNegative(FakePointerSink):
    """A display left of or above the primary becomes unreachable: x and y floored at zero."""

    def move_absolute(self, x: float, y: float) -> None:
        check_finite(x=x, y=y)  # validates first, as a real backend would, then clamps
        super().move_absolute(max(0.0, x), max(0.0, y))


class ClampsAbsoluteToThePrimaryDisplay(FakePointerSink):
    """The sink 'knows' the screen is 1920x1080 and pins every position inside it."""

    def move_absolute(self, x: float, y: float) -> None:
        check_finite(x=x, y=y)
        super().move_absolute(min(x, 1919.0), min(y, 1079.0))


class CapsEachRelativeStep(FakePointerSink):
    """A second speed limit, inside the backend: no step may exceed 2000 units per axis."""

    def move_relative(self, dx: float, dy: float) -> None:
        check_finite(dx=dx, dy=dy)
        super().move_relative(max(-2000.0, min(2000.0, dx)), max(-2000.0, min(2000.0, dy)))


class SplitsLargeMotionIntoSteps(FakePointerSink):
    """One long move becomes several short ones: one call, many effects."""

    def move_relative(self, dx: float, dy: float) -> None:
        check_finite(dx=dx, dy=dy)
        steps = int(max(abs(dx), abs(dy)) // 1000) + 1
        self._emit(*[PointerAction.move_relative(dx / steps, dy / steps)] * steps)


class UnsupportedLooksLikeAnOutageWhileFailing(FakePointerSink):
    """Checks "am I up?" before "can I do this at all?": a missing capability reads as transient."""

    def move_absolute(self, x: float, y: float) -> None:
        if self._failure is not None:
            raise self._failure
        super().move_absolute(x, y)


class UnsupportedLooksClosedAfterClose(FakePointerSink):
    """After ``close()`` a capability the backend never had is reported as "closed"."""

    def move_absolute(self, x: float, y: float) -> None:
        if self._closed:
            raise PointerBackendError("pointer sink is closed")
        super().move_absolute(x, y)


MUTANTS = [
    pytest.param(SwallowsErrorsInClick, FULL_CAPABILITIES,
                 "test_every_operation_fails_loudly_and_records_nothing_when_the_backend_fails",
                 id="swallows-errors-in-click"),
    pytest.param(SwallowsErrorsInMotion, FULL_CAPABILITIES,
                 "test_a_backend_failure_does_not_replay_the_previous_action",
                 id="swallows-errors-in-motion"),
    pytest.param(SwallowsErrorsInScroll, FULL_CAPABILITIES,
                 "test_every_operation_fails_loudly_and_records_nothing_when_the_backend_fails",
                 id="swallows-errors-in-scroll"),
    pytest.param(ReleasesBeforePress, FULL_CAPABILITIES,
                 "test_click_presses_then_releases_exactly_once", id="release-before-press"),
    pytest.param(NeverReleases, FULL_CAPABILITIES,
                 "test_click_presses_then_releases_exactly_once", id="drops-the-release"),
    pytest.param(HoldsTheLastMoveBack, FULL_CAPABILITIES,
                 "test_relative_motion_is_exact_and_ordered", id="holds-the-last-move-back"),
    pytest.param(ScrollIgnoresClose, FULL_CAPABILITIES,
                 "test_every_operation_after_close_is_an_explicit_error",
                 id="scroll-works-after-close"),
    pytest.param(ClickIgnoresClose, FULL_CAPABILITIES,
                 "test_every_operation_after_close_is_an_explicit_error",
                 id="click-works-after-close"),
    pytest.param(MoveIgnoresClose, FULL_CAPABILITIES,
                 "test_operations_after_close_are_explicit", id="move-works-after-close"),
    pytest.param(ClosesTwice, FULL_CAPABILITIES,
                 "test_close_reaches_the_platform_at_most_once", id="close-is-not-idempotent"),
    pytest.param(RaisesOnSecondClose, FULL_CAPABILITIES,
                 "test_close_is_idempotent", id="second-close-raises"),
    pytest.param(RaisesFromCloseWhileFailing, FULL_CAPABILITIES,
                 "test_close_never_raises_even_while_the_backend_is_failing",
                 id="close-raises-while-failing"),
    pytest.param(ReplaysTheLastActionOnFailure, FULL_CAPABILITIES,
                 "test_a_backend_failure_does_not_replay_the_previous_action",
                 id="replays-last-action-on-failure"),
    pytest.param(QueuesFailedCallsAndFlushesLater, FULL_CAPABILITIES,
                 "test_a_backend_failure_does_not_replay_the_previous_action",
                 id="queues-failed-calls-and-flushes"),
    pytest.param(LogsAttemptsNotEffects, FULL_CAPABILITIES,
                 "test_every_operation_fails_loudly_and_records_nothing_when_the_backend_fails",
                 id="records-attempts-not-effects"),
    pytest.param(LetsNaNThrough, FULL_CAPABILITIES,
                 "test_non_finite_values_are_refused_before_the_platform_sees_them",
                 id="nan-reaches-the-platform"),
    pytest.param(SilentNoOpForAbsolute, PARTIAL_CAPABILITIES,
                 "test_absolute_motion_matches_capabilities", id="silent-noop-absolute"),
    pytest.param(SilentNoOpForMissingButton, PointerCapabilities(
        backend="fake-two-button", relative_motion=True,
        buttons=frozenset({PointerButton.LEFT, PointerButton.RIGHT}),
    ), "test_a_button_the_backend_lacks_is_an_explicit_error", id="silent-noop-middle-button"),
    pytest.param(SilentNoOpForHorizontalScroll, PARTIAL_CAPABILITIES,
                 "test_horizontal_scroll_matches_capabilities", id="silent-noop-horizontal-scroll"),
    pytest.param(FlipsTheScrollSign, FULL_CAPABILITIES,
                 "test_scroll_signs_are_passed_through_unchanged", id="flips-scroll-sign"),
    pytest.param(SwapsAxes, FULL_CAPABILITIES,
                 "test_relative_motion_is_exact_and_ordered", id="swaps-axes"),
    pytest.param(DefaultButtonIsRight, FULL_CAPABILITIES,
                 "test_click_defaults_to_the_left_button", id="default-button-is-right"),
    pytest.param(TruncatesDeltasToIntegers, FULL_CAPABILITIES,
                 "test_relative_motion_is_exact_and_ordered", id="truncates-deltas"),
    pytest.param(CapabilitiesDrift, FULL_CAPABILITIES,
                 "test_capabilities_name_the_backend_and_do_not_change", id="capabilities-drift"),
    pytest.param(CapabilitiesVanishAfterClose, FULL_CAPABILITIES,
                 "test_capabilities_are_still_answerable_after_close",
                 id="capabilities-vanish-after-close"),
    pytest.param(MovesOnConstruction, FULL_CAPABILITIES,
                 "test_a_fresh_sink_has_emitted_nothing", id="moves-on-construction"),
    pytest.param(FailureLatchesForever, FULL_CAPABILITIES,
                 "test_a_backend_failure_does_not_replay_the_previous_action",
                 id="stays-dead-after-recovery"),
    pytest.param(ClampsAbsoluteToNonNegative, FULL_CAPABILITIES,
                 "test_absolute_motion_reaches_negative_and_off_primary_coordinates_unchanged",
                 id="clamps-absolute-to-non-negative"),
    pytest.param(ClampsAbsoluteToThePrimaryDisplay, FULL_CAPABILITIES,
                 "test_absolute_motion_reaches_negative_and_off_primary_coordinates_unchanged",
                 id="clamps-absolute-to-primary-display"),
    pytest.param(CapsEachRelativeStep, FULL_CAPABILITIES,
                 "test_large_relative_motion_is_neither_capped_nor_split",
                 id="caps-each-relative-step"),
    pytest.param(SplitsLargeMotionIntoSteps, FULL_CAPABILITIES,
                 "test_large_relative_motion_is_neither_capped_nor_split",
                 id="splits-large-motion"),
    pytest.param(UnsupportedLooksLikeAnOutageWhileFailing, PARTIAL_CAPABILITIES,
                 "test_an_unsupported_operation_stays_unsupported_while_failing_and_after_close",
                 id="unsupported-looks-transient-while-failing"),
    pytest.param(UnsupportedLooksClosedAfterClose, PARTIAL_CAPABILITIES,
                 "test_an_unsupported_operation_stays_unsupported_while_failing_and_after_close",
                 id="unsupported-looks-closed-after-close"),
]


@pytest.mark.parametrize("mutant,caps,catcher", MUTANTS)
def test_the_contract_fails_a_deliberately_wrong_backend(mutant, caps, catcher) -> None:  # type: ignore[no-untyped-def]
    failures = run_contract(lambda: mutant(caps))
    assert failures, f"{mutant.__name__} passed the whole shared contract -- the suite is blind to it"
    assert catcher in failures, (
        f"{mutant.__name__} was caught by {sorted(failures)}, not by {catcher}; "
        "the test written for this mistake no longer notices it"
    )


def test_there_are_at_least_a_dozen_distinct_mutants() -> None:
    assert len({p.values[0] for p in MUTANTS}) >= 12


def test_every_contract_test_is_the_designated_catcher_of_something_or_a_basic_check() -> None:
    """The mutant table must keep exercising the new tests, not only the old ones."""
    catchers = {p.values[2] for p in MUTANTS}
    for new in (
        "test_every_operation_fails_loudly_and_records_nothing_when_the_backend_fails",
        "test_every_operation_after_close_is_an_explicit_error",
        "test_close_never_raises_even_while_the_backend_is_failing",
        "test_close_reaches_the_platform_at_most_once",
        "test_capabilities_are_still_answerable_after_close",
        "test_absolute_motion_reaches_negative_and_off_primary_coordinates_unchanged",
        "test_large_relative_motion_is_neither_capped_nor_split",
        "test_an_unsupported_operation_stays_unsupported_while_failing_and_after_close",
    ):
        assert new in catchers


# --------------------------------------------------------------------------- #
# Out-of-tree reuse
# --------------------------------------------------------------------------- #
def test_the_contract_module_imports_nothing_from_the_tests_package() -> None:
    """A third-party backend copies ``tests/pointer_contract.py`` and nothing else."""
    import ast
    from pathlib import Path

    path = Path(__file__).resolve().parent / "pointer_contract.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.name)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert not {m for m in imported if m == "tests" or m.startswith("tests.")}, sorted(imported)
    assert {m.split(".")[0] for m in imported} <= {"__future__", "collections", "math", "pytest", "yazses"}


def test_a_backend_in_a_fresh_namespace_can_use_the_contract_through_public_names_only() -> None:
    """The documented recipe: a recorder of ``yazses.pointer.actions`` values, four hooks."""

    class Outsider:
        """Shaped like a third-party backend: its own recorder, no import of tests.pointer_fake."""

        def __init__(self) -> None:
            self.log: list[PointerAction] = []
            self.dead = False
            self.closed = False

        def capabilities(self) -> PointerCapabilities:
            return PointerCapabilities(
                backend="outsider",
                relative_motion=True,
                buttons=frozenset({PointerButton.LEFT, PointerButton.RIGHT}),
                scroll_vertical=True,
            )

        def _guard(self) -> None:
            if self.closed:
                raise PointerBackendError("closed")
            if self.dead:
                raise PointerBackendError("dead")

        def move_relative(self, dx: float, dy: float) -> None:
            check_finite(dx=dx, dy=dy)
            self._guard()
            self.log.append(PointerAction.move_relative(dx, dy))

        def move_absolute(self, x: float, y: float) -> None:
            raise PointerUnsupportedError("no absolute motion")

        def click(self, button: PointerButton = PointerButton.LEFT) -> None:
            if button not in self.capabilities().buttons:
                raise PointerUnsupportedError("no such button")
            self._guard()
            self.log += [PointerAction.press(button), PointerAction.release(button)]

        def scroll(self, dx: float, dy: float) -> None:
            check_finite(dx=dx, dy=dy)
            require_scroll(self.capabilities(), dx, dy)
            self._guard()
            self.log.append(PointerAction.scroll(dx, dy))

        def close(self) -> None:
            self.closed = True

    class OutsiderContract(PointerSinkContract):
        def make_sink(self) -> PointerSink:
            return Outsider()

        def recorded(self, sink: PointerSink) -> list[PointerAction]:
            assert isinstance(sink, Outsider)
            return list(sink.log)

        def induce_failure(self, sink: PointerSink) -> None:
            assert isinstance(sink, Outsider)
            sink.dead = True

        def clear_failure(self, sink: PointerSink) -> None:
            assert isinstance(sink, Outsider)
            sink.dead = False

    failures: dict[str, BaseException] = {}
    for name in sorted(n for n in dir(OutsiderContract) if n.startswith("test_")):
        try:
            getattr(OutsiderContract(), name)()
        except pytest.skip.Exception:
            continue
        except (Exception, pytest.fail.Exception) as exc:  # noqa: BLE001
            failures[name] = exc
    assert failures == {}
